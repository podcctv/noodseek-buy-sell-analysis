from pathlib import Path

from fastapi.testclient import TestClient

from app.config_store import ConfigStore, mask_domain
from app.main import app
from app.schemas import AppConfig


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
    assert "domain" in body and "ai" in body and "system" in body
