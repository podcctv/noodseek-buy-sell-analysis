from __future__ import annotations

import hashlib
import hmac
import secrets
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from .config_store import ConfigStore, mask_domain
from .schemas import AIConfig, AppConfig, DomainConfig, SystemConfig

app = FastAPI(title="NodeSeek Admin")
store = ConfigStore(path=Path("data/app_config.json"))
templates = Jinja2Templates(directory="services/web/app/templates")
SESSION_COOKIE_NAME = "nodeseek_admin_session"
SESSION_SECRET = secrets.token_hex(32)
DEFAULT_PASSWORD = "123456"


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
