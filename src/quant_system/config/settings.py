from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import (
    AliasChoices,
    Field,
    SecretStr,
    ValidationError,
    field_serializer,
    model_validator,
)
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


class FutuSettings(BaseSettings):
    """Read-only Futu / OpenD connectivity settings for market data."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="QS_",
        extra="ignore",
    )

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = Field(default=11111, ge=1, le=65535)
    market: Literal["US"] = "US"
    request_timeout_seconds: int = Field(default=15, gt=0)
    default_kline_freq: str = "1d"
    cache_dir: Path = Path("data/futu")
    use_cache: bool = True
    options_enabled: bool = True


class LLMSettings(BaseSettings):
    """Optional LLM routing for the Phase 7 research assistant."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",
        populate_by_name=True,
    )

    provider: Literal["stub", "openai", "xai"] = Field(
        default="stub",
        validation_alias=AliasChoices("QS_LLM_PROVIDER", "LLM_PROVIDER"),
    )
    api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("QS_LLM_API_KEY", "LLM_API_KEY"),
    )
    base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("QS_LLM_BASE_URL", "LLM_BASE_URL"),
    )
    model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("QS_LLM_MODEL", "LLM_MODEL"),
    )
    timeout: int = Field(
        default=60,
        validation_alias=AliasChoices("QS_LLM_TIMEOUT", "LLM_TIMEOUT"),
        gt=0,
    )

    @field_serializer("api_key", when_used="json")
    def serialize_llm_secret(self, value: SecretStr | None) -> str | None:
        return "**********" if value else None


class PredictionMarketSettings(BaseSettings):
    """Read-only prediction market research settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="QS_",
        extra="ignore",
    )

    provider: Literal["sample", "polymarket"] = Field(
        default="sample",
        validation_alias=AliasChoices("QS_PREDICTION_MARKET_PROVIDER", "QS_PROVIDER"),
    )
    polymarket_gamma_base_url: str = Field(
        default="https://gamma-api.polymarket.com",
        validation_alias=AliasChoices("QS_POLYMARKET_GAMMA_BASE_URL"),
    )
    polymarket_clob_base_url: str = Field(
        default="https://clob.polymarket.com",
        validation_alias=AliasChoices("QS_POLYMARKET_CLOB_BASE_URL"),
    )
    polymarket_data_api_base_url: str = Field(
        default="https://data-api.polymarket.com",
        validation_alias=AliasChoices("QS_POLYMARKET_DATA_API_BASE_URL"),
    )
    polymarket_request_timeout_seconds: int = Field(
        default=10,
        validation_alias=AliasChoices("QS_POLYMARKET_REQUEST_TIMEOUT_SECONDS"),
        gt=0,
    )
    polymarket_max_retries: int = Field(
        default=2,
        validation_alias=AliasChoices("QS_POLYMARKET_MAX_RETRIES"),
        ge=0,
        le=5,
    )
    polymarket_rate_limit_per_second: float = Field(
        default=2.0,
        validation_alias=AliasChoices("QS_POLYMARKET_RATE_LIMIT_PER_SECOND"),
        gt=0,
    )
    polymarket_cache_dir: Path = Field(
        default=Path("data/prediction_market"),
        validation_alias=AliasChoices("QS_POLYMARKET_CACHE_DIR"),
    )
    history_dir: Path = Field(
        default=Path("data/prediction_market/history"),
        validation_alias=AliasChoices("QS_PREDICTION_MARKET_HISTORY_DIR"),
    )
    polymarket_cache_ttl_seconds: int = Field(
        default=300,
        validation_alias=AliasChoices("QS_POLYMARKET_CACHE_TTL_SECONDS"),
        ge=0,
    )
    polymarket_cache_stale_if_error_seconds: int = Field(
        default=86_400,
        validation_alias=AliasChoices("QS_POLYMARKET_CACHE_STALE_IF_ERROR_SECONDS"),
        ge=0,
    )
    polymarket_user_agent: str = Field(
        default="ai-quant-platform/phase11",
        validation_alias=AliasChoices("QS_POLYMARKET_USER_AGENT"),
        min_length=1,
    )
    collector_default_interval_seconds: float = Field(
        default=30.0,
        validation_alias=AliasChoices(
            "QS_PREDICTION_MARKET_COLLECTOR_DEFAULT_INTERVAL_SECONDS"
        ),
        gt=0,
    )
    backtest_default_fee_bps: float = Field(
        default=0.0,
        validation_alias=AliasChoices("QS_PREDICTION_MARKET_BACKTEST_DEFAULT_FEE_BPS"),
        ge=0,
    )
    polymarket_read_only: bool = Field(
        default=True,
        validation_alias=AliasChoices("QS_POLYMARKET_READ_ONLY"),
    )

    @model_validator(mode="after")
    def require_read_only(self) -> PredictionMarketSettings:
        if not self.polymarket_read_only:
            raise ValueError("polymarket_read_only must remain true in Phase 11")
        return self


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
    api_cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
            "http://localhost:3000",
            "http://localhost:3001",
        ]
    )
    safety: SafetySettings = Field(default_factory=SafetySettings)
    data: DataSettings = Field(default_factory=DataSettings)
    api_keys: ApiKeySettings = Field(default_factory=ApiKeySettings)
    futu: FutuSettings = Field(default_factory=FutuSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    prediction_market: PredictionMarketSettings = Field(
        default_factory=PredictionMarketSettings
    )


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
