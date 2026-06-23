-- Run index for the local AI quant platform.
--
-- Files under data/api_runs/<kind>/<run_id>/metadata.json remain the source of
-- truth for run artifacts. This table is a fast, queryable index over those
-- runs so the API can list history without scanning the filesystem. It is
-- entirely optional: with QS_DATABASE_ENABLED=false (or the container stopped)
-- every endpoint falls back to reading the files directly.
--
-- Safety: store research run metadata only. No secrets, broker credentials,
-- wallet data, private keys, or live order instructions.

CREATE SCHEMA IF NOT EXISTS quant_system;

CREATE TABLE IF NOT EXISTS quant_system.runs (
    kind          TEXT NOT NULL,        -- 'backtest' | 'factor' | 'paper' | 'replication'
    run_id        TEXT NOT NULL,
    source        TEXT,                 -- 'sample' | 'futu' | 'tiingo' | ...
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),  -- run time (from run_id, 1s resolution)
    indexed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),  -- insert time, sub-second tiebreaker
    artifact_path TEXT,                 -- data/api_runs/<kind>/<run_id>
    metadata      JSONB NOT NULL,       -- full metadata.json payload
    PRIMARY KEY (kind, run_id)
);

-- Upgrade path for tables created before indexed_at existed.
ALTER TABLE quant_system.runs
    ADD COLUMN IF NOT EXISTS indexed_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_runs_kind_created
    ON quant_system.runs (kind, created_at DESC, indexed_at DESC);
