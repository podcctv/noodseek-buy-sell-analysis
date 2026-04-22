from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from .schemas import AppConfig


class ConfigStore:
    """JSON 文件配置存储，支持线程安全读写。"""

    def __init__(self, path: Path):
        self.path = path
        self._lock = Lock()

    def load(self) -> AppConfig:
        with self._lock:
            if not self.path.exists():
                config = AppConfig()
                self._write(config)
                return config

            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return AppConfig.model_validate(data)

    def save(self, config: AppConfig) -> AppConfig:
        with self._lock:
            self._write(config)
            return config

    def _write(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2)
        self.path.write_text(payload, encoding="utf-8")


def mask_domain(domain: str) -> str:
    """对域名进行隐私保护展示，例如 a***.com。"""

    if "://" in domain:
        schema, rest = domain.split("://", 1)
        return f"{schema}://{_mask_host(rest)}"
    return _mask_host(domain)


def _mask_host(value: str) -> str:
    host = value.split("/", 1)[0]
    remain = value[len(host) :]

    chunks = host.split(".")
    if not chunks:
        return "***"

    first = chunks[0]
    if len(first) <= 2:
        masked_first = "*" * len(first)
    else:
        masked_first = first[0] + "*" * (len(first) - 2) + first[-1]

    return ".".join([masked_first, *chunks[1:]]) + remain
