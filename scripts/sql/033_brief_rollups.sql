-- Durable AI weekly/monthly rollup archive for the local single-user brief.
--
-- Rollup issues mirror the daily brief archive shape: one issue per
-- (owner, kind, period, locale) with append-only versioned snapshots.
-- Applying this migration is an explicit operator action.

CREATE TABLE IF NOT EXISTS quant_system.brief_rollup_issues (
    rollup_id           UUID PRIMARY KEY,
    public_id           TEXT NOT NULL UNIQUE,
    owner_user_id       UUID NOT NULL REFERENCES quant_system.app_users(id),
    kind                TEXT NOT NULL CHECK (kind IN ('weekly','monthly')),
    period_key          TEXT NOT NULL,
    period_start        DATE NOT NULL,
    period_end          DATE NOT NULL,
    locale              TEXT NOT NULL DEFAULT 'zh',
    status              TEXT NOT NULL DEFAULT 'published',
    latest_snapshot_id  UUID,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner_user_id, kind, period_key, locale)
);

CREATE TABLE IF NOT EXISTS quant_system.brief_rollup_snapshots (
    snapshot_id       UUID PRIMARY KEY,
    rollup_id         UUID NOT NULL REFERENCES quant_system.brief_rollup_issues(rollup_id) ON DELETE CASCADE,
    version           INTEGER NOT NULL,
    payload           JSONB NOT NULL,
    source_watermark  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (rollup_id, version)
);

-- Runtime/read-only roles mirror the 010 default-privilege set for brief
-- tables (the runtime role writes snapshots; the read-only role reads).
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE quant_system.brief_rollup_issues TO quant_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE quant_system.brief_rollup_snapshots TO quant_runtime;
GRANT SELECT ON TABLE quant_system.brief_rollup_issues TO quant_readonly;
GRANT SELECT ON TABLE quant_system.brief_rollup_snapshots TO quant_readonly;
