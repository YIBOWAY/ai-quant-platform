-- scripts/sql/009_ai_news_provider_runs.sql
CREATE SCHEMA IF NOT EXISTS quant_system;

CREATE TABLE IF NOT EXISTS quant_system.ai_news_provider_runs (
    provider       TEXT NOT NULL,
    run_id         TEXT NOT NULL,
    generated_at   TIMESTAMPTZ NOT NULL,
    window_start   TIMESTAMPTZ,
    window_end     TIMESTAMPTZ,
    item_count     INTEGER NOT NULL DEFAULT 0,
    daily_date     DATE,
    inbox_path     TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    ingested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    status         TEXT NOT NULL,
    error          TEXT,
    raw_meta       JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (provider, run_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_news_provider_runs_provider_status_generated
    ON quant_system.ai_news_provider_runs (provider, status, generated_at DESC);
