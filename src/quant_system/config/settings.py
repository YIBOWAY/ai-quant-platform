from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_serializer, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LIVE_TRADING_CONFIRMATION_PHRASE = "I_UNDERSTAND_THIS_ENABLES_LIVE_TRADING"


class SafetySettings(BaseSettings):
    """Default safety controls shared by research, backtest, and paper modes."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="QS_",
        extra="ignore",
    )

    dry_run: bool = True
    paper_trading: bool = True
    live_trading_enabled: bool = False
    no_live_trade_without_manual_approval: bool = True
    kill_switch: bool = True

    max_position_size: float = Field(default=0.05, ge=0, le=1)
    max_daily_loss: float = Field(default=0.02, ge=0, le=1)
    max_drawdown: float = Field(default=0.10, ge=0, le=1)
    max_order_value: float = Field(default=10_000, ge=0)
    max_turnover: float = Field(default=1.0, ge=0)

    allowed_symbols: list[str] = Field(default_factory=list)
    blocked_symbols: list[str] = Field(default_factory=list)
    manual_live_trading_confirmation: str = ""

    @model_validator(mode="after")
    def require_live_confirmation(self) -> SafetySettings:
        if (
            self.live_trading_enabled
            and self.manual_live_trading_confirmation != LIVE_TRADING_CONFIRMATION_PHRASE
        ):
            raise ValueError(
                "manual_live_trading_confirmation must exactly match "
                f"{LIVE_TRADING_CONFIRMATION_PHRASE!r} when live_trading_enabled is true"
            )
        return self


class DataSettings(BaseSettings):
    """Local data-layer paths and provider defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="QS_",
        extra="ignore",
    )

    default_data_provider: str = "sample"
    data_dir: Path = Path("data")
    parquet_dir: Path = Path("data/parquet")
    duckdb_path: Path = Path("data/quant_system.duckdb")
    reports_dir: Path = Path("reports")


class ApiKeySettings(BaseSettings):
    """API credentials loaded from local environment only."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="QS_",
        extra="ignore",
    )

    finnhub_api_key: SecretStr | None = None
    alpha_vantage_api_key: SecretStr | None = None
    tiingo_api_token: SecretStr | None = None
    twelvedata_api_key: SecretStr | None = None
    polygon_api_key: SecretStr | None = None
    newsapi_key: SecretStr | None = None
    twitter_api_key: SecretStr | None = None
    twitter_api_key_secret: SecretStr | None = None
    twitter_bearer_token: SecretStr | None = None

    @field_serializer(
        "finnhub_api_key",
        "alpha_vantage_api_key",
        "tiingo_api_token",
        "twelvedata_api_key",
        "polygon_api_key",
        "newsapi_key",
        "twitter_api_key",
        "twitter_api_key_secret",
        "twitter_bearer_token",
        when_used="json",
    )
    def serialize_secret(self, value: SecretStr | None) -> str | None:
        return "**********" if value else None


class Settings(BaseSettings):
    """Application-level settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="QS_",
        extra="ignore",
    )

    app_name: str = "AI Quant Research Platform"
    environment: Literal["local", "test", "paper", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    safety: SafetySettings = Field(default_factory=SafetySettings)
    data: DataSettings = Field(default_factory=DataSettings)
    api_keys: ApiKeySettings = Field(default_factory=ApiKeySettings)


# Note on env loading:
# ``Settings`` and nested settings use the ``QS_`` prefix. Top-level
# ``QS_*`` env vars (e.g. ``QS_LOG_LEVEL``) bind to ``Settings`` directly while
# sub-models are constructed via ``default_factory`` and read their own env keys
# from the same file. ``Settings`` ignores unknown keys via ``extra="ignore"``,
# so the layers do not collide. Keep this in mind when adding new fields:
# pick a layer first, then reflect the prefix in
# ``.env.example``.
@lru_cache(maxsize=1)
def load_settings() -> Settings:
    """Load settings once so CLI and future services share the same config view."""
    try:
        return Settings()
    except ValidationError:
        raise


def reload_settings() -> Settings:
    """Clear the cached settings and reload from environment.

    Intended for tests or interactive sessions that mutate environment
    variables and need a fresh ``Settings`` instance.
    """
    load_settings.cache_clear()
    return load_settings()
