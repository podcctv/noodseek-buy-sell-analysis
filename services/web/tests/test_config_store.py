from pathlib import Path

from fastapi.testclient import TestClient

from app.config_store import ConfigStore, mask_domain
from app.main import _build_chat_completions_url, _is_trade_entry, app
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
