from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from .config_store import ConfigStore, mask_domain
from .schemas import AIConfig, AppConfig, BrandTrainingSample, DomainConfig, SystemConfig

store = ConfigStore(path=Path("data/app_config.json"))
templates = Jinja2Templates(directory="services/web/app/templates")
SESSION_COOKIE_NAME = "nodeseek_admin_session"
SESSION_SECRET = secrets.token_hex(32)
DEFAULT_PASSWORD = "123456"
app = FastAPI(title="NodeSeek Admin")


class RuntimeState:
    """运行期内存状态：帖子缓存与 AI 处理进度。"""

    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []
        self.post_index: set[str] = set()
        self.progress_items: list[dict[str, Any]] = []
        self.running: bool = False
        self.last_fetch_at: str | None = None
        self.last_error: str | None = None
        self.cancelled_uids: set[str] = set()
        self.lock = asyncio.Lock()


runtime = RuntimeState()


async def _poll_loop() -> None:
    while True:
        cfg = store.load()
        await _poll_once(cfg)
        await asyncio.sleep(cfg.system.rss_poll_interval_seconds)


async def _poll_once(cfg: AppConfig) -> None:
    async with runtime.lock:
        if runtime.running:
            return
        runtime.running = True

    try:
        entries = await _fetch_rss_entries(str(cfg.domain.rss_domain), cfg.ai.timeout_seconds)
        for entry in entries:
            uid = _entry_uid(entry)
            async with runtime.lock:
                if uid in runtime.post_index:
                    continue
                if uid in runtime.cancelled_uids:
                    runtime.post_index.add(uid)
                    runtime.cancelled_uids.discard(uid)
                    continue
                progress = {
                    "uid": uid,
                    "title": entry.get("title", ""),
                    "status": "running",
                    "message": "AI 处理中",
                    "started_at": _now_iso(),
                    "finished_at": None,
                }
                runtime.progress_items.insert(0, progress)
                runtime.progress_items = runtime.progress_items[:100]

            async with runtime.lock:
                if uid in runtime.cancelled_uids:
                    progress["status"] = "cancelled"
                    progress["message"] = "已取消"
                    progress["finished_at"] = _now_iso()
                    runtime.post_index.add(uid)
                    runtime.cancelled_uids.discard(uid)
                    continue

            try:
                analyzed = await _analyze_entry(entry, cfg)
            except Exception as exc:  # noqa: BLE001
                async with runtime.lock:
                    runtime.post_index.add(uid)
                    progress["status"] = "failed"
                    progress["message"] = f"失败：{_format_exception(exc)}"
                    progress["finished_at"] = _now_iso()
                continue

            async with runtime.lock:
                if uid in runtime.cancelled_uids:
                    progress["status"] = "cancelled"
                    progress["message"] = "已取消"
                    progress["finished_at"] = _now_iso()
                    runtime.post_index.add(uid)
                    runtime.cancelled_uids.discard(uid)
                    continue
                runtime.post_index.add(uid)
                runtime.posts.insert(0, analyzed)
                runtime.posts = runtime.posts[:300]
                progress["status"] = "done"
                progress["message"] = f"完成：{analyzed['intent']} ({int(analyzed['confidence'] * 100)}%)"
                progress["finished_at"] = _now_iso()

        async with runtime.lock:
            runtime.last_fetch_at = _now_iso()
            runtime.last_error = None
    except Exception as exc:  # noqa: BLE001
        async with runtime.lock:
            runtime.last_error = _format_exception(exc)
    finally:
        async with runtime.lock:
            runtime.running = False


async def _fetch_rss_entries(rss_url: str, timeout_seconds: int) -> list[dict[str, str]]:
    timeout = max(5, min(120, timeout_seconds))
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(rss_url)
        resp.raise_for_status()
        xml = resp.text

    root = ET.fromstring(xml)
    items = root.findall("./channel/item")
    if not items:
        items = root.findall(".//item")

    entries: list[dict[str, str]] = []
    for item in items[:40]:
        title = _clean_text(item.findtext("title", default=""))
        link = _clean_text(item.findtext("link", default=""))
        guid = _clean_text(item.findtext("guid", default=""))
        pub_date = _clean_text(item.findtext("pubDate", default=""))
        desc = _clean_text(item.findtext("description", default=""))
        categories = [_clean_text(c.text or "") for c in item.findall("category") if _clean_text(c.text or "")]
        if not title:
            continue
        if not _is_trade_entry(title=title, link=link, description=desc, categories=categories):
            continue
        entries.append(
            {
                "title": title,
                "link": link,
                "guid": guid,
                "pub_date": pub_date,
                "description": desc,
            }
        )
    return entries


def _is_trade_entry(title: str, link: str, description: str, categories: list[str]) -> bool:
    normalized_categories = {c.strip().lower() for c in categories}
    return "trade" in normalized_categories


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _entry_uid(entry: dict[str, str]) -> str:
    base = entry.get("guid") or entry.get("link") or entry.get("title", "")
    pub = entry.get("pub_date", "")
    return hashlib.sha256(f"{base}|{pub}".encode("utf-8")).hexdigest()


async def _analyze_entry(entry: dict[str, str], cfg: AppConfig) -> dict[str, Any]:
    ai = await _classify_with_ai(entry, cfg.ai)
    if not ai:
        ai = _rule_classify(entry, cfg)

    return {
        "uid": _entry_uid(entry),
        "title": entry.get("title", ""),
        "time": entry.get("pub_date") or "",
        "intent": ai.get("intent", "unknown"),
        "product_name": ai.get("product_name", ""),
        "price": ai.get("price", "-"),
        "confidence": float(ai.get("confidence", 0.5)),
        "summary": ai.get("summary", ""),
        "link": entry.get("link", ""),
    }


async def _classify_with_ai(entry: dict[str, str], ai_cfg: AIConfig) -> dict[str, Any] | None:
    cfg = store.load()
    memory = _build_brand_memory_prompt(cfg)
    prompt = (
        "你是二手交易帖分类器。请严格返回 JSON，不要输出其它文字。\\n"
        "字段: intent(buy/sell/unknown), product_name(商品名称字符串), price(字符串,没有写-), confidence(0-1), summary(<=30字)。\\n"
        f"{memory}"
        f"标题: {entry.get('title', '')}\\n"
        f"描述: {entry.get('description', '')}"
    )
    payload = {
        "model": ai_cfg.model,
        "messages": [
            {"role": "system", "content": "你只返回 JSON"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    headers = dict(ai_cfg.custom_headers)
    api_key = ai_cfg.api_key.get_secret_value().strip()
    if ai_cfg.auth_mode == "bearer" and api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = _build_chat_completions_url(ai_cfg)

    async with httpx.AsyncClient(timeout=ai_cfg.timeout_seconds) as client:
        response = await client.request(ai_cfg.request_method.upper(), url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    raw = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not raw:
        return None

    parsed = _extract_json(raw)
    if not isinstance(parsed, dict):
        return None

    intent = str(parsed.get("intent", "unknown")).lower()
    if intent not in {"buy", "sell", "unknown"}:
        intent = "unknown"

    confidence = parsed.get("confidence", 0.5)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    return {
        "intent": intent,
        "product_name": str(parsed.get("product_name", "") or ""),
        "price": str(parsed.get("price", "-") or "-"),
        "confidence": confidence,
        "summary": str(parsed.get("summary", "") or ""),
    }


def _extract_json(raw: str) -> Any:
    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _build_chat_completions_url(ai_cfg: AIConfig) -> str:
    base = str(ai_cfg.base_url).rstrip("/")
    path = (ai_cfg.chat_completions_path or "").strip()

    if not path or path == "/":
        return base
    if path.startswith("http://") or path.startswith("https://"):
        return path

    normalized_path = path if path.startswith("/") else f"/{path}"
    if base.endswith("/chat/completions") and normalized_path == "/chat/completions":
        return base
    return f"{base}{normalized_path}"


def _format_exception(exc: Exception) -> str:
    detail = str(exc).strip()
    if not detail:
        detail = exc.__class__.__name__

    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        response_text = (exc.response.text or "").strip()
        if response_text:
            compact_text = re.sub(r"\s+", " ", response_text)
            detail = f"{detail} | response: {compact_text[:200]}"
        return f"HTTP {status_code} - {detail}"

    return detail


def _build_brand_memory_prompt(cfg: AppConfig) -> str:
    samples = cfg.training.brand_samples[:20]
    if not samples:
        return ""
    rows = []
    for sample in samples:
        kw = "、".join(sample.keywords[:6])
        rows.append(f"- 品牌:{sample.brand}; 商品:{sample.product_name}; 关键词:{kw}")
    return "品牌识别参考(人工标注优先参考):\\n" + "\\n".join(rows) + "\\n"


def _guess_product_name(entry: dict[str, str], cfg: AppConfig) -> str:
    title = entry.get("title", "")
    normalized = re.sub(r"\[[^\]]+\]", " ", title)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    for sample in cfg.training.brand_samples:
        if sample.product_name and sample.product_name in title:
            return sample.product_name
        for keyword in sample.keywords:
            if keyword and keyword.lower() in title.lower():
                return sample.product_name or keyword
    return normalized[:48]


def _rule_classify(entry: dict[str, str], cfg: AppConfig) -> dict[str, Any]:
    text = f"{entry.get('title', '')} {entry.get('description', '')}".lower()
    buy_keywords = ["求购", "收", "蹲", "want", "buy"]
    sell_keywords = ["出", "出售", "转让", "闲置", "sell"]

    intent = "unknown"
    confidence = 0.55
    if any(k in text for k in buy_keywords):
        intent = "buy"
        confidence = 0.8
    if any(k in text for k in sell_keywords):
        intent = "sell"
        confidence = 0.8

    price_match = re.search(r"([￥¥]?\s?\d{2,6})", text)
    price = price_match.group(1).replace(" ", "") if price_match else "-"
    if price and not price.startswith(("¥", "￥", "-")):
        price = f"¥{price}"

    return {
        "intent": intent,
        "product_name": _guess_product_name(entry, cfg),
        "price": price,
        "confidence": confidence,
        "summary": "规则兜底",
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.on_event("startup")
async def startup_polling() -> None:
    _bootstrap_default_password()
    asyncio.create_task(_poll_loop())


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash or "$" not in password_hash:
        return False
    salt, expected = password_hash.split("$", 1)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()
    return hmac.compare_digest(actual, expected)


def _bootstrap_default_password() -> None:
    cfg = store.load()
    if cfg.auth.password_hash:
        return
    cfg.auth.password_hash = hash_password(DEFAULT_PASSWORD)
    cfg.auth.force_password_change = True
    store.save(cfg)


def _build_session_token() -> str:
    nonce = secrets.token_urlsafe(16)
    sig = hmac.new(SESSION_SECRET.encode("utf-8"), nonce.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{nonce}.{sig}"


def _is_valid_session(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    nonce, sig = token.rsplit(".", 1)
    expected = hmac.new(SESSION_SECRET.encode("utf-8"), nonce.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def _is_authed(request: Request) -> bool:
    return _is_valid_session(request.cookies.get(SESSION_COOKIE_NAME))


def _require_auth_redirect(request: Request) -> RedirectResponse | None:
    _bootstrap_default_password()
    cfg = store.load()
    if cfg.auth.force_password_change and request.url.path != "/admin/change-password":
        return RedirectResponse(url="/admin/change-password", status_code=303)
    if not _is_authed(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    return None


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse(request, "front_dashboard.html", {})


@app.get("/api/v1/dashboard")
async def dashboard_data() -> dict[str, Any]:
    async with runtime.lock:
        posts = list(runtime.posts)

    total = len(posts)
    buy = sum(1 for p in posts if p["intent"] == "buy")
    sell = sum(1 for p in posts if p["intent"] == "sell")
    avg_conf = round(sum(float(p["confidence"]) for p in posts) / total, 2) if total else 0

    hot_counter: dict[str, int] = {}
    for p in posts:
        for token in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{2,16}", p["title"]):
            if token in {"求购", "出售", "闲置", "转让", "国行"}:
                continue
            hot_counter[token] = hot_counter.get(token, 0) + 1

    hot_words = sorted(hot_counter.items(), key=lambda x: x[1], reverse=True)[:8]

    return {
        "metrics": {
            "total": total,
            "buy_rate": round((buy / total) * 100) if total else 0,
            "sell_rate": round((sell / total) * 100) if total else 0,
            "avg_conf": avg_conf,
        },
        "posts": posts[:100],
        "hot_words": hot_words,
    }


@app.get("/api/v1/progress")
async def progress_data() -> dict[str, Any]:
    async with runtime.lock:
        return {
            "running": runtime.running,
            "last_fetch_at": runtime.last_fetch_at,
            "last_error": runtime.last_error,
            "items": list(runtime.progress_items[:20]),
        }


@app.post("/api/v1/progress/{uid}/cancel")
async def cancel_progress(uid: str) -> dict[str, str]:
    async with runtime.lock:
        runtime.cancelled_uids.add(uid)
        for item in runtime.progress_items:
            if item.get("uid") == uid and item.get("status") == "running":
                item["status"] = "cancelled"
                item["message"] = "已取消"
                item["finished_at"] = _now_iso()
                break
    return {"ok": "true"}


@app.post("/api/v1/progress/{uid}/retry")
async def retry_progress(uid: str) -> dict[str, str]:
    cfg = store.load()
    entries = await _fetch_rss_entries(str(cfg.domain.rss_domain), cfg.ai.timeout_seconds)
    target_entry = next((entry for entry in entries if _entry_uid(entry) == uid), None)
    if not target_entry:
        return {"ok": "false", "error": "entry_not_found"}

    progress = {
        "uid": uid,
        "title": target_entry.get("title", ""),
        "status": "running",
        "message": "AI 重试处理中",
        "started_at": _now_iso(),
        "finished_at": None,
    }
    async with runtime.lock:
        runtime.progress_items.insert(0, progress)
        runtime.progress_items = runtime.progress_items[:100]

    try:
        analyzed = await _analyze_entry(target_entry, cfg)
    except Exception as exc:  # noqa: BLE001
        async with runtime.lock:
            progress["status"] = "failed"
            progress["message"] = f"重试失败：{_format_exception(exc)}"
            progress["finished_at"] = _now_iso()
        return {"ok": "false", "error": "retry_failed"}

    async with runtime.lock:
        runtime.post_index.add(uid)
        runtime.posts = [post for post in runtime.posts if post.get("uid") != uid]
        runtime.posts.insert(0, analyzed)
        runtime.posts = runtime.posts[:300]
        progress["status"] = "done"
        progress["message"] = f"重试完成：{analyzed['intent']} ({int(analyzed['confidence'] * 100)}%)"
        progress["finished_at"] = _now_iso()
    return {"ok": "true"}


@app.post("/api/v1/poll-now")
async def poll_now() -> dict[str, str]:
    cfg = store.load()
    asyncio.create_task(_poll_once(cfg))
    return {"ok": "true"}


@app.get("/admin/login")
def login_page(request: Request):
    _bootstrap_default_password()
    if _is_authed(request):
        return RedirectResponse(url="/admin/settings", status_code=303)
    return templates.TemplateResponse(
        request,
        "admin_login.html",
        {"error": request.query_params.get("error") == "1"},
    )


@app.post("/admin/login")
def login(password: str = Form(...)):
    _bootstrap_default_password()
    cfg = store.load()
    if not verify_password(password, cfg.auth.password_hash):
        return RedirectResponse(url="/admin/login?error=1", status_code=303)

    target = "/admin/change-password" if cfg.auth.force_password_change else "/admin/settings"
    resp = RedirectResponse(url=target, status_code=303)
    resp.set_cookie(SESSION_COOKIE_NAME, _build_session_token(), httponly=True, samesite="lax")
    return resp


@app.post("/admin/logout")
def logout():
    resp = RedirectResponse(url="/admin/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE_NAME)
    return resp


@app.get("/admin/change-password")
def change_password_page(request: Request):
    if not _is_authed(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "admin_change_password.html",
        {"error": request.query_params.get("error") == "1"},
    )


@app.post("/admin/change-password")
def change_password(
    request: Request,
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    if not _is_authed(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    if len(new_password) < 6 or new_password != confirm_password:
        return RedirectResponse(url="/admin/change-password?error=1", status_code=303)
    cfg = store.load()
    cfg.auth.password_hash = hash_password(new_password)
    cfg.auth.force_password_change = False
    store.save(cfg)
    return RedirectResponse(url="/admin/settings?saved=1", status_code=303)


@app.get("/admin/settings")
def admin_settings(request: Request):
    redirect = _require_auth_redirect(request)
    if redirect:
        return redirect
    cfg = store.load()
    masked_rss = mask_domain(str(cfg.domain.rss_domain)) if cfg.domain.privacy_protection_enabled else str(cfg.domain.rss_domain)
    masked_callback = (
        mask_domain(str(cfg.domain.callback_domain))
        if cfg.domain.callback_domain and cfg.domain.privacy_protection_enabled
        else str(cfg.domain.callback_domain or "")
    )
    return templates.TemplateResponse(
        request,
        "admin_settings.html",
        {
            "config": cfg,
            "masked_rss": masked_rss,
            "masked_callback": masked_callback,
            "saved": request.query_params.get("saved") == "1",
        },
    )


@app.get("/admin/brand-training")
def brand_training_page(request: Request):
    redirect = _require_auth_redirect(request)
    if redirect:
        return redirect
    cfg = store.load()
    return templates.TemplateResponse(
        request,
        "admin_brand_training.html",
        {
            "samples": cfg.training.brand_samples,
            "saved": request.query_params.get("saved") == "1",
        },
    )


@app.post("/admin/brand-training/add")
def add_brand_training_sample(
    request: Request,
    brand: str = Form(...),
    product_name: str = Form(""),
    keywords: str = Form(""),
    note: str = Form(""),
):
    redirect = _require_auth_redirect(request)
    if redirect:
        return redirect
    cfg = store.load()
    sample = BrandTrainingSample(
        id=secrets.token_hex(8),
        brand=brand.strip(),
        product_name=product_name.strip(),
        keywords=[k.strip() for k in re.split(r"[,\n，、]", keywords) if k.strip()],
        note=note.strip(),
        created_at=_now_iso(),
    )
    cfg.training.brand_samples.insert(0, sample)
    cfg.training.brand_samples = cfg.training.brand_samples[:500]
    store.save(cfg)
    return RedirectResponse(url="/admin/brand-training?saved=1", status_code=303)


@app.post("/admin/brand-training/{sample_id}/delete")
def delete_brand_training_sample(request: Request, sample_id: str):
    redirect = _require_auth_redirect(request)
    if redirect:
        return redirect
    cfg = store.load()
    cfg.training.brand_samples = [s for s in cfg.training.brand_samples if s.id != sample_id]
    store.save(cfg)
    return RedirectResponse(url="/admin/brand-training?saved=1", status_code=303)


@app.get("/api/v1/brand-training")
def list_brand_training() -> dict[str, Any]:
    cfg = store.load()
    samples = [s.model_dump(mode="json") for s in cfg.training.brand_samples[:200]]
    return {"items": samples, "total": len(cfg.training.brand_samples)}


@app.post("/admin/settings/domain")
def update_domain(
    request: Request,
    rss_domain: str = Form(...),
    callback_domain: str = Form(""),
    privacy_protection_enabled: bool = Form(False),
):
    redirect = _require_auth_redirect(request)
    if redirect:
        return redirect
    cfg = store.load()
    cfg.domain = DomainConfig(
        rss_domain=rss_domain,
        callback_domain=callback_domain or None,
        privacy_protection_enabled=privacy_protection_enabled,
    )
    store.save(cfg)
    return RedirectResponse(url="/admin/settings?saved=1", status_code=303)


@app.post("/admin/settings/ai")
def update_ai(
    request: Request,
    provider: str = Form(...),
    base_url: str = Form(...),
    chat_completions_path: str = Form("/chat/completions"),
    request_method: str = Form("POST"),
    auth_mode: str = Form("none"),
    api_key: str = Form(""),
    custom_headers_text: str = Form(""),
    model: str = Form(...),
    timeout_seconds: int = Form(...),
):
    redirect = _require_auth_redirect(request)
    if redirect:
        return redirect
    custom_headers: dict[str, str] = {}
    for line in custom_headers_text.splitlines():
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        if name.strip():
            custom_headers[name.strip()] = value.strip()
    cfg = store.load()
    cfg.ai = AIConfig(
        provider=provider,
        base_url=base_url,
        chat_completions_path=chat_completions_path,
        request_method=request_method.upper(),
        auth_mode=auth_mode.lower(),
        api_key=api_key,
        custom_headers=custom_headers,
        model=model,
        timeout_seconds=timeout_seconds,
    )
    store.save(cfg)
    return RedirectResponse(url="/admin/settings?saved=1", status_code=303)


@app.post("/admin/settings/system")
def update_system(
    request: Request,
    confidence_threshold: float = Form(...),
    rss_poll_interval_seconds: int = Form(...),
    timezone: str = Form(...),
):
    redirect = _require_auth_redirect(request)
    if redirect:
        return redirect
    cfg = store.load()
    cfg.system = SystemConfig(
        confidence_threshold=confidence_threshold,
        rss_poll_interval_seconds=rss_poll_interval_seconds,
        timezone=timezone,
    )
    store.save(cfg)
    return RedirectResponse(url="/admin/settings?saved=1", status_code=303)


@app.get("/api/v1/config", response_model=AppConfig)
def get_config() -> AppConfig:
    _bootstrap_default_password()
    return store.load()
