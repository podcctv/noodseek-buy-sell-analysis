from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl, SecretStr, TypeAdapter


def _to_http_url(value: str) -> HttpUrl:
    return TypeAdapter(HttpUrl).validate_python(value)


class DomainConfig(BaseModel):
    """域名相关配置，默认启用隐私保护。"""

    rss_domain: HttpUrl = Field(default_factory=lambda: _to_http_url("https://rss.nodeseek.com/"))
    callback_domain: HttpUrl | None = None
    privacy_protection_enabled: bool = True


class AIConfig(BaseModel):
    """AI 配置项，支持 OpenAI 兼容接口。"""

    provider: str = "openai_compatible"
    base_url: HttpUrl = Field(default_factory=lambda: _to_http_url("https://llm.428048.xyz/v1"))
    api_key: SecretStr = Field(default=SecretStr(""))
    model: str = "gpt-4o-mini"
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class SystemConfig(BaseModel):
    """系统运行配置。"""

    confidence_threshold: float = Field(default=0.7, ge=0, le=1)
    rss_poll_interval_seconds: int = Field(default=300, ge=30, le=86400)
    timezone: str = "Asia/Shanghai"


class AppConfig(BaseModel):
    domain: DomainConfig = Field(default_factory=DomainConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    system: SystemConfig = Field(default_factory=SystemConfig)
