from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, ValidationError, model_validator
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


class Settings(BaseSettings):
    """Application-level settings for Phase 0."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="QS_",
        extra="ignore",
    )

    app_name: str = "AI Quant Research Platform"
    environment: Literal["local", "test", "paper", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    safety: SafetySettings = Field(default_factory=SafetySettings)


# Note on env loading:
# Both ``Settings`` and ``SafetySettings`` use the ``QS_`` prefix. Top-level
# ``QS_*`` env vars (e.g. ``QS_LOG_LEVEL``) bind to ``Settings`` directly while
# the ``safety`` sub-model is constructed via ``default_factory`` and reads the
# same env keys (e.g. ``QS_DRY_RUN``). ``Settings`` ignores unknown keys via
# ``extra="ignore"``, so the two layers do not collide. Keep this in mind when
# adding new fields: pick a layer first, then reflect the prefix in
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

