from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from .config_store import ConfigStore, mask_domain
from .schemas import AIConfig, AppConfig, DomainConfig, SystemConfig

app = FastAPI(title="NodeSeek Admin")
store = ConfigStore(path=Path("data/app_config.json"))
templates = Jinja2Templates(directory="services/web/app/templates")


@app.get("/")
def index() -> RedirectResponse:
    return RedirectResponse(url="/admin/settings", status_code=302)


@app.get("/admin/settings")
def admin_settings(request: Request):
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
    rss_domain: str = Form(...),
    callback_domain: str = Form(""),
    privacy_protection_enabled: bool = Form(False),
):
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
    provider: str = Form(...),
    base_url: str = Form(...),
    api_key: str = Form(""),
    model: str = Form(...),
    timeout_seconds: int = Form(...),
):
    cfg = store.load()
    cfg.ai = AIConfig(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout_seconds,
    )
    store.save(cfg)
    return RedirectResponse(url="/admin/settings?saved=1", status_code=303)


@app.post("/admin/settings/system")
def update_system(
    confidence_threshold: float = Form(...),
    rss_poll_interval_seconds: int = Form(...),
    timezone: str = Form(...),
):
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
    return store.load()
