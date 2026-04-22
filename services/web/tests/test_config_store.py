from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.config_store import ConfigStore, mask_domain
from app.main import (
    _build_chat_completions_url,
    _extract_text_from_html,
    _fetch_post_content_with_browser,
    _format_exception,
    _is_trade_entry,
    _load_runtime_config,
    _should_retry_exception,
    app,
)
from app.schemas import AIConfig, AppConfig


def test_mask_domain():
    assert mask_domain("https://rss.nodeseek.com/").startswith("https://r")
    assert "*" in mask_domain("node.example.com")


def test_config_store_roundtrip(tmp_path: Path):
    store = ConfigStore(tmp_path / "app_config.json")
    cfg = store.load()
    assert isinstance(cfg, AppConfig)

    cfg.system.timezone = "UTC"
    store.save(cfg)

    loaded = store.load()
    assert loaded.system.timezone == "UTC"


def test_api_config_endpoint():
    client = TestClient(app)
    resp = client.get("/api/v1/config")
    assert resp.status_code == 200
    body = resp.json()
    assert "domain" in body and "ai" in body and "system" in body and "auth" in body


def test_admin_settings_requires_login():
    client = TestClient(app)
    resp = client.get("/admin/settings", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert resp.headers["location"] in ("/admin/login", "/admin/change-password")


def test_build_chat_completions_url_avoids_duplicate_path():
    cfg = AIConfig(
        base_url="https://llm.428048.xyz/v1/chat/completions",
        chat_completions_path="/chat/completions",
        model="test-model",
    )
    assert _build_chat_completions_url(cfg) == "https://llm.428048.xyz/v1/chat/completions"


def test_trade_entry_filter():
    assert _is_trade_entry(
        title="分享一台 Mac mini M2",
        link="https://www.nodeseek.com/post-123",
        description="经验帖",
        categories=["trade"],
    )
    assert not _is_trade_entry(
        title="出一台 Mac mini M2",
        link="https://www.nodeseek.com/post-456",
        description="闲置转让",
        categories=["编程"],
    )


def test_ai_config_supports_extended_timeout_and_retries():
    cfg = AIConfig(model="test", timeout_seconds=3600, max_retries=3, retry_delay_seconds=5)
    assert cfg.timeout_seconds == 3600
    assert cfg.max_retries == 3
    assert cfg.retry_delay_seconds == 5


def test_runtime_config_can_be_overridden_by_env(monkeypatch):
    monkeypatch.setenv("NDS_LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("NDS_LLM_API_KEY", "secret-token")
    monkeypatch.setenv("NDS_LLM_CUSTOM_HEADERS_JSON", '{"Content-Type":"application/json","X-Test":"1"}')
    cfg = _load_runtime_config()
    assert str(cfg.ai.base_url).startswith("https://example.com/v1")
    assert cfg.ai.api_key.get_secret_value() == "secret-token"
    assert cfg.ai.custom_headers["X-Test"] == "1"


def test_should_retry_exception_for_524():
    request = httpx.Request("POST", "https://llm.428048.xyz/v1/chat/completions")
    response = httpx.Response(524, request=request, text="timeout")
    exc = httpx.HTTPStatusError("524 timeout", request=request, response=response)
    assert _should_retry_exception(exc)


def test_format_exception_for_524_contains_guidance():
    request = httpx.Request("POST", "https://llm.428048.xyz/v1/chat/completions")
    response = httpx.Response(524, request=request, text="timeout")
    exc = httpx.HTTPStatusError("524 timeout", request=request, response=response)
    message = _format_exception(exc)
    assert "HTTP 524" in message
    assert "上游响应超时" in message


def test_extract_text_from_html_prefers_article():
    html = """
    <html>
      <body>
        <article>
          <h1>标题</h1>
          <p>这是正文内容</p>
        </article>
        <footer>页脚内容</footer>
      </body>
    </html>
    """
    text = _extract_text_from_html(html)
    assert "这是正文内容" in text
    assert "页脚内容" not in text


def test_browser_fetch_returns_empty_when_playwright_unavailable(monkeypatch):
    import builtins
    import asyncio

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # type: ignore[no-untyped-def]
        if name.startswith("playwright"):
            raise ModuleNotFoundError("playwright not installed")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    text = asyncio.run(_fetch_post_content_with_browser("https://example.com", 5))
    assert text == ""
