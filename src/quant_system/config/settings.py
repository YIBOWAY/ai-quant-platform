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
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from quant_system.config.runtime_paths import unconfigured_runtime_path

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

    default_data_provider: str = "futu"
    data_dir: Path = Path("data")
    parquet_dir: Path = Path("data/parquet")
    duckdb_path: Path = Path("data/quant_system.duckdb")
    reports_dir: Path = Path("reports")


class DatabaseSettings(BaseSettings):
    """Optional PostgreSQL mirrors for local research metadata.

    Disabled by default. When enabled and reachable, run list endpoints can use
    the run index, new runs are indexed best-effort, and AI News items can be
    cached for stale fallback. Otherwise the API transparently falls back to
    files/live upstreams. The URL is held as a secret so it is masked in the
    settings dump (it carries a password).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="QS_DATABASE_",
        extra="ignore",
    )

    enabled: bool = False
    url: SecretStr | None = None
    connect_timeout_seconds: int = Field(default=1, gt=0)
    # V1.1 fail-closed: startup never auto-applies migrations. New migrations are
    # applied only via the explicit `quant-system migrate --apply --allow <file>`
    # command under a separate authorization (never implicitly at boot).
    auto_migrate: bool = False

    @field_serializer("url", when_used="json")
    def serialize_database_url(self, value: SecretStr | None) -> str | None:
        return "**********" if value else None


class PaperAccountSettings(BaseSettings):
    """Persistent paper-account background processing settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="QS_PAPER_ACCOUNT_",
        extra="ignore",
    )

    auto_process_pending_orders_enabled: bool = True
    auto_process_interval_seconds: float = Field(default=30.0, gt=0)
    db_mode: Literal["file", "mirror", "canonical"] = "file"


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
        env_prefix="",
        extra="ignore",
        populate_by_name=True,
    )

    enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("QS_FUTU_ENABLED", "QS_ENABLED"),
    )
    host: str = Field(
        default="127.0.0.1",
        validation_alias=AliasChoices("QS_FUTU_HOST", "QS_HOST"),
    )
    port: int = Field(
        default=11111,
        validation_alias=AliasChoices("QS_FUTU_PORT", "QS_PORT"),
        ge=1,
        le=65535,
    )
    market: Literal["US"] = Field(
        default="US",
        validation_alias=AliasChoices("QS_FUTU_MARKET", "QS_MARKET"),
    )
    request_timeout_seconds: int = Field(
        default=15,
        validation_alias=AliasChoices(
            "QS_FUTU_REQUEST_TIMEOUT_SECONDS",
            "QS_REQUEST_TIMEOUT_SECONDS",
        ),
        gt=0,
    )
    default_kline_freq: str = Field(
        default="1d",
        validation_alias=AliasChoices(
            "QS_FUTU_DEFAULT_KLINE_FREQ",
            "QS_DEFAULT_KLINE_FREQ",
        ),
    )
    cache_dir: Path = Field(
        default=Path("data/futu"),
        validation_alias=AliasChoices("QS_FUTU_CACHE_DIR", "QS_CACHE_DIR"),
    )
    use_cache: bool = Field(
        default=True,
        validation_alias=AliasChoices("QS_FUTU_USE_CACHE", "QS_USE_CACHE"),
    )
    options_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "QS_FUTU_OPTIONS_ENABLED",
            "QS_OPTIONS_ENABLED",
        ),
    )


class OptionsRadarSettings(BaseSettings):
    """Daily read-only seller-options radar settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",
        populate_by_name=True,
    )

    enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("QS_OPTIONS_RADAR_ENABLED"),
    )
    provider: Literal["futu", "sample"] = Field(
        default="futu",
        validation_alias=AliasChoices("QS_OPTIONS_RADAR_PROVIDER"),
    )
    universe_path: Path = Field(
        default=Path("data/options_universe/sp500_nasdaq100.csv"),
        validation_alias=AliasChoices("QS_OPTIONS_RADAR_UNIVERSE_PATH"),
    )
    universe_top_n: int = Field(
        default=100,
        validation_alias=AliasChoices("QS_OPTIONS_RADAR_UNIVERSE_TOP_N"),
        ge=1,
    )
    output_dir: Path = Field(
        default=Path("data/options_scans"),
        validation_alias=AliasChoices("QS_OPTIONS_RADAR_OUTPUT_DIR"),
    )
    futu_rate_limit_per_30s: int = Field(
        default=10,
        validation_alias=AliasChoices("QS_OPTIONS_RADAR_FUTU_RATE_LIMIT_PER_30S"),
        ge=1,
    )
    futu_request_pause_seconds: float = Field(
        default=3.1,
        validation_alias=AliasChoices("QS_OPTIONS_RADAR_FUTU_REQUEST_PAUSE_SECONDS"),
        gt=0,
    )
    snapshot_batch_size: int = Field(
        default=200,
        validation_alias=AliasChoices("QS_OPTIONS_RADAR_SNAPSHOT_BATCH_SIZE"),
        ge=1,
        le=400,
    )
    max_dte_for_radar: int = Field(
        default=60,
        validation_alias=AliasChoices("QS_OPTIONS_RADAR_MAX_DTE_FOR_RADAR"),
        ge=0,
    )
    min_dte_for_radar: int = Field(
        default=7,
        validation_alias=AliasChoices("QS_OPTIONS_RADAR_MIN_DTE_FOR_RADAR"),
        ge=0,
    )
    max_delta_for_radar: float = Field(
        default=0.8,
        validation_alias=AliasChoices("QS_OPTIONS_RADAR_MAX_DELTA_FOR_RADAR"),
        ge=0,
        le=1,
    )
    iv_history_lookback_days: int = Field(
        default=252,
        validation_alias=AliasChoices("QS_OPTIONS_RADAR_IV_HISTORY_LOOKBACK_DAYS"),
        ge=30,
    )
    earnings_calendar_path: Path = Field(
        default=Path("data/options_universe/earnings_calendar.csv"),
        validation_alias=AliasChoices("QS_OPTIONS_RADAR_EARNINGS_CALENDAR_PATH"),
    )
    vix_history_path: Path = Field(
        default=Path("data/options_universe/vix_history.csv"),
        validation_alias=AliasChoices("QS_OPTIONS_RADAR_VIX_HISTORY_PATH"),
    )
    startup_catchup_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("QS_OPTIONS_RADAR_STARTUP_CATCHUP_ENABLED"),
    )

    @model_validator(mode="after")
    def validate_dte_window(self) -> OptionsRadarSettings:
        if self.min_dte_for_radar > self.max_dte_for_radar:
            raise ValueError("min_dte_for_radar must be <= max_dte_for_radar")
        return self


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

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_empty_provider(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return "stub"
        return value

    @field_validator("api_key", "base_url", "model", mode="before")
    @classmethod
    def normalize_empty_optional_value(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_serializer("api_key", when_used="json")
    def serialize_llm_secret(self, value: SecretStr | None) -> str | None:
        return "**********" if value else None


DEFAULT_AIHOT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class AiHotSettings(BaseSettings):
    """Read-only AI HOT public news feed settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",
        populate_by_name=True,
    )

    enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("QS_AIHOT_ENABLED"),
    )
    base_url: str = Field(
        default="https://aihot.virxact.com",
        validation_alias=AliasChoices("QS_AIHOT_BASE_URL"),
        min_length=1,
    )
    timeout_seconds: int = Field(
        default=8,
        validation_alias=AliasChoices("QS_AIHOT_TIMEOUT_SECONDS"),
        gt=0,
    )
    cache_ttl_seconds: int = Field(
        default=120,
        validation_alias=AliasChoices("QS_AIHOT_CACHE_TTL_SECONDS"),
        ge=0,
    )
    user_agent: str = Field(
        default=DEFAULT_AIHOT_USER_AGENT,
        validation_alias=AliasChoices("QS_AIHOT_USER_AGENT"),
        min_length=1,
    )


class NewsSettings(BaseSettings):
    """AI News source preference and failover policy."""

    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="", extra="ignore", populate_by_name=True
    )
    source_preference: Literal["auto", "aihot", "horizon"] = Field(
        default="auto",
        validation_alias=AliasChoices("QS_NEWS_SOURCE_PREFERENCE"),
    )
    failover_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("QS_NEWS_FAILOVER_ENABLED"),
    )


class HorizonSettings(BaseSettings):
    """Local Horizon inbox feed settings for AI News bridge."""

    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="", extra="ignore", populate_by_name=True
    )
    enabled: bool = Field(default=True, validation_alias=AliasChoices("QS_HORIZON_ENABLED"))
    inbox_dir: str = Field(
        default=str(Path(__file__).resolve().parents[3] / "data" / "horizon_inbox"),
        validation_alias=AliasChoices("QS_HORIZON_INBOX_DIR"),
        min_length=1,
    )
    max_age_seconds: int = Field(
        default=129_600,
        validation_alias=AliasChoices("QS_HORIZON_MAX_AGE_SECONDS"),
        gt=0,
    )
    provider_beta: bool = Field(
        default=False,
        validation_alias=AliasChoices("QS_HORIZON_PROVIDER_BETA"),
    )
    ingest_on_read: bool = Field(
        default=False,
        validation_alias=AliasChoices("QS_HORIZON_INGEST_ON_READ"),
    )


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


class BacktestJobSettings(BaseSettings):
    """Lightweight in-process async backtest job settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="QS_BACKTEST_JOBS_",
        extra="ignore",
    )

    enabled: bool = False
    max_workers: int = Field(default=1, ge=1, le=8)
    shutdown_timeout_seconds: float = Field(default=5.0, ge=0.0, le=300.0)


class HermesArtifactSettings(BaseSettings):
    """Read-only access to the HQA materialized artifact feed."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="QS_HERMES_ARTIFACT_",
        extra="ignore",
    )

    feed_path: Path = unconfigured_runtime_path("hermes-artifact-feed")
    freshness_budget_seconds: int = Field(default=10_800, gt=0)
    max_future_clock_skew_seconds: int = Field(default=300, ge=0, le=86_400)
    max_manifest_bytes: int = Field(default=4 * 1024 * 1024, gt=0)


class HermesGatewaySettings(BaseSettings):
    """Fail-closed, server-side access to the local Hermes API Server.

    This credential authorizes the full upstream API, so browser code must
    never receive it. Session reads stay GET-only; supervised dispatch uses a
    separate durable port. The legacy ephemeral HTTP adapter is test-only.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="QS_HERMES_GATEWAY_",
        extra="ignore",
    )

    enabled: bool = False
    base_url: str = "http://127.0.0.1:8642"
    api_key_file: Path | None = None
    # Git checkout that owns the running Hermes API Server. Release admission
    # hashes its clean commit identity and must match the operator stamp.
    runtime_root: Path = (
        Path.home()
        / ".hermes"
        / "hermes-agent"
        / ".claude"
        / "worktrees"
        / "v2-integration"
    )
    timeout_seconds: float = Field(default=2.0, gt=0, le=30, allow_inf_nan=False)
    # Real /v1/runs can take tens of seconds; keep read timeout short separately.
    dispatch_timeout_seconds: float = Field(default=120.0, gt=0, le=600, allow_inf_nan=False)
    # Explicit hermetic-test escape hatch only; production defaults fail closed.
    allow_ephemeral_runs: bool = False
    max_response_bytes: int = Field(default=4 * 1024 * 1024, ge=4096, le=16 * 1024 * 1024)
    max_messages: int = Field(default=200, ge=1, le=1000)


class LocalMutationSettings(BaseSettings):
    """Local single-user mutation / composer gate (default OFF).

    Opening this does **not** enable live trading. Trading stays behind
    ``SafetySettings`` (kill_switch / paper / dry_run). This flag only unlocks
    the authenticated local BFF mutation path for research composer / workspace
    act on loopback.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="QS_LOCAL_MUTATION_",
        extra="ignore",
    )

    enabled: bool = False
    # When true and schemas+dispatch are ready, surface chat_write_ready locally.
    composer_open: bool = False


class LocalTrustSettings(BaseSettings):
    """Solo-owner localhost identity-ritual bypass (default OFF).

    Bypasses ONLY local identity binding: candidate admission records,
    preflight evidence, three-repo runtime digests, clean-checkout requirement,
    and connector admission ceremony. Live trading must remain OFF. Research
    and paper toggles stay independent and are enforced at their own execution
    boundaries; public write/release fields are never touched.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="QS_LOCAL_TRUST_",
        extra="ignore",
    )

    mode: bool = False


class FactorAutomationSettings(BaseSettings):
    """Deny-only switches for the local paper factor automation path.

    ``mode`` may authorize machine review for paper-only candidates.  The
    independent ``auto_land`` switch is additionally required before any
    prepared promotion may be committed or landed.  Neither setting grants a
    live-trading capability.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="QS_FACTOR_AUTOMATION_",
        extra="ignore",
    )

    mode: bool = False
    auto_land: bool = False


class AgentV02ReleaseSettings(BaseSettings):
    """Local operator inputs for the durable Agent v0.2 release gate."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="QS_AGENT_V02_RELEASE_",
        extra="ignore",
    )

    workspace_id: str = Field(
        default="ws-local-main",
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    platform_runtime_root: Path = unconfigured_runtime_path(
        "platform-runtime-root"
    )
    evidence_file: Path = unconfigured_runtime_path("release-evidence-file")
    capability_max_age_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        allow_inf_nan=False,
    )
    connector_heartbeat_max_age_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        allow_inf_nan=False,
    )


class CandidateAdmissionSettings(BaseSettings):
    """Deny-only operator inputs for the private Agent v0.2 candidate phase.

    ``enabled`` can only veto admission.  It never grants command dispatch by
    itself; durable PostgreSQL admission, exact evidence, clean runtimes, and
    the command-side candidate binding are independent requirements.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="QS_AGENT_V02_CANDIDATE_",
        extra="ignore",
    )

    enabled: bool = False
    # A release candidate must survive the complete operator flow: real
    # multi-turn chat, one supervised restart, provider evidence, browser
    # decisions, and the paper-reproduction review.  Two hours is still a
    # deliberately short-lived admission, but avoids turning that honest flow
    # into a 30-minute race.
    ttl_seconds: int = Field(default=900, ge=1, le=7200)
    preflight_evidence_file: Path = unconfigured_runtime_path(
        "candidate-preflight-evidence-file"
    )
    final_evidence_file: Path = unconfigured_runtime_path(
        "candidate-final-evidence-file"
    )


class IntentPayloadSettings(BaseSettings):
    """Subprocess Port to HQA ``intent_payload_cli`` (L2a-Send).

    Platform must not import ``hqa``. BFF uses ``put``; the supervised worker
    uses ``bind_resolve``. Both external runtime paths require explicit
    operator bindings; an installed package never infers them from its own
    module location.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="QS_INTENT_PAYLOAD_",
        extra="ignore",
    )

    # Both values must be explicitly configured for any subprocess authority.
    python_executable: Path | None = None
    hqa_root: Path = unconfigured_runtime_path("hqa-runtime-root")
    timeout_seconds: float = Field(default=15.0, gt=0, le=300, allow_inf_nan=False)


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
        # First loopback origin becomes LocalSessionPolicy.accepted_origin
        # (owner cookie/CSRF gate). Prefer the real FE default port 3001 so
        # Next same-origin rewrites on :3001 are not workspace_forbidden.
        default_factory=lambda: [
            "http://127.0.0.1:3001",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://localhost:3000",
        ]
    )
    safety: SafetySettings = Field(default_factory=SafetySettings)
    data: DataSettings = Field(default_factory=DataSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    paper_account: PaperAccountSettings = Field(default_factory=PaperAccountSettings)
    api_keys: ApiKeySettings = Field(default_factory=ApiKeySettings)
    futu: FutuSettings = Field(default_factory=FutuSettings)
    options_radar: OptionsRadarSettings = Field(default_factory=OptionsRadarSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    aihot: AiHotSettings = Field(default_factory=AiHotSettings)
    news: NewsSettings = Field(default_factory=NewsSettings)
    horizon: HorizonSettings = Field(default_factory=HorizonSettings)
    prediction_market: PredictionMarketSettings = Field(
        default_factory=PredictionMarketSettings
    )
    backtest_jobs: BacktestJobSettings = Field(default_factory=BacktestJobSettings)
    hermes_artifacts: HermesArtifactSettings = Field(default_factory=HermesArtifactSettings)
    hermes_gateway: HermesGatewaySettings = Field(default_factory=HermesGatewaySettings)
    local_mutation: LocalMutationSettings = Field(default_factory=LocalMutationSettings)
    local_trust: LocalTrustSettings = Field(default_factory=LocalTrustSettings)
    factor_automation: FactorAutomationSettings = Field(
        default_factory=FactorAutomationSettings
    )
    agent_v02_release: AgentV02ReleaseSettings = Field(
        default_factory=AgentV02ReleaseSettings
    )
    candidate_admission: CandidateAdmissionSettings = Field(
        default_factory=CandidateAdmissionSettings
    )
    intent_payload: IntentPayloadSettings = Field(default_factory=IntentPayloadSettings)


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
