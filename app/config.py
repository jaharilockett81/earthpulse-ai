"""Runtime configuration, read once from environment variables.

Secrets (QLOO_API_KEY, ANTHROPIC_API_KEY) are only ever read here and passed to
server-side clients. They are never returned by any API route or written to logs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # Qloo — the hackathon key only works on the hackathon host.
    qloo_api_key: str = field(default_factory=lambda: os.getenv("QLOO_API_KEY", "").strip(), repr=False)
    qloo_base_url: str = field(default_factory=lambda: os.getenv("QLOO_BASE_URL", "https://hackathon.api.qloo.com").rstrip("/"))
    qloo_timeout_s: float = field(default_factory=lambda: _float("QLOO_TIMEOUT_S", 12.0))
    qloo_max_rps: float = field(default_factory=lambda: _float("QLOO_MAX_RPS", 4.0))  # key limit is 5/s
    qloo_cache_ttl_s: float = field(default_factory=lambda: _float("QLOO_CACHE_TTL_S", 24 * 3600))

    # Optional LLM (natural-language prompt parsing + explanation polish). App works without it.
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "").strip(), repr=False)
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "claude-haiku-5-5"))
    llm_timeout_s: float = field(default_factory=lambda: _float("LLM_TIMEOUT_S", 15.0))

    # Geocoding for an optional "starting from" point (Open-Meteo, no key).
    geocode_url: str = field(default_factory=lambda: os.getenv("GEOCODE_URL", "https://geocoding-api.open-meteo.com/v1/search"))

    # Abuse protection for the public demo.
    runs_per_hour_per_ip: int = field(default_factory=lambda: int(_float("RUNS_PER_HOUR_PER_IP", 20)))
    search_per_10min_per_ip: int = field(default_factory=lambda: int(_float("SEARCH_PER_10MIN_PER_IP", 120)))

    # Local UI development only: serve clearly-labelled synthetic data when no key is set.
    # Refused when ENVIRONMENT=production.
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development").lower())
    dev_fixtures: bool = field(default_factory=lambda: _bool("EARTHPULSE_DEV_FIXTURES"))

    @property
    def qloo_configured(self) -> bool:
        return bool(self.qloo_api_key)

    @property
    def llm_configured(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def fixtures_active(self) -> bool:
        return self.dev_fixtures and self.environment != "production" and not self.qloo_configured


def get_settings() -> Settings:
    return Settings()
