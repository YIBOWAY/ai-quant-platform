-- Durable business facts for the local single-user app shell.
--
-- Root user is seeded now so future multi-user support can attach owner_user_id
-- without rewriting brief, AI report, or paper account tables.

CREATE SCHEMA IF NOT EXISTS quant_system;

CREATE TABLE IF NOT EXISTS quant_system.app_users (
    id          UUID PRIMARY KEY,
    username    TEXT NOT NULL UNIQUE,
    role        TEXT NOT NULL DEFAULT 'root',
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM quant_system.app_users
        WHERE username = 'root'
          AND id <> '00000000-0000-0000-0000-000000000001'::uuid
    ) THEN
        RAISE EXCEPTION
            'quant_system.app_users root username exists with a different id; expected %',
            '00000000-0000-0000-0000-000000000001';
    END IF;
END $$;

INSERT INTO quant_system.app_users (id, username, role, is_active)
VALUES ('00000000-0000-0000-0000-000000000001', 'root', 'root', TRUE)
ON CONFLICT (id) DO UPDATE
SET username = EXCLUDED.username,
    role = EXCLUDED.role,
    is_active = TRUE,
    updated_at = now();

CREATE TABLE IF NOT EXISTS quant_system.brief_issues (
    issue_id            UUID PRIMARY KEY,
    public_id           TEXT NOT NULL UNIQUE,
    owner_user_id       UUID NOT NULL REFERENCES quant_system.app_users(id),
    issue_date          DATE NOT NULL,
    market_session_date DATE,
    locale              TEXT NOT NULL DEFAULT 'zh',
    status              TEXT NOT NULL DEFAULT 'published',
    latest_snapshot_id  UUID,
    share_token_hash    TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner_user_id, issue_date, locale)
);

CREATE TABLE IF NOT EXISTS quant_system.brief_snapshots (
    snapshot_id       UUID PRIMARY KEY,
    issue_id          UUID NOT NULL REFERENCES quant_system.brief_issues(issue_id) ON DELETE CASCADE,
    version           INTEGER NOT NULL,
    payload           JSONB NOT NULL,
    rendered_text     TEXT,
    source_watermark  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (issue_id, version),
    CONSTRAINT uq_brief_snapshots_issue_snapshot UNIQUE (issue_id, snapshot_id)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_brief_snapshots_issue_snapshot'
          AND conrelid = 'quant_system.brief_snapshots'::regclass
    ) THEN
        ALTER TABLE quant_system.brief_snapshots
            ADD CONSTRAINT uq_brief_snapshots_issue_snapshot
            UNIQUE (issue_id, snapshot_id);
    END IF;
END $$;

ALTER TABLE quant_system.brief_issues
    DROP CONSTRAINT IF EXISTS fk_brief_latest_snapshot;

ALTER TABLE quant_system.brief_issues
    ADD CONSTRAINT fk_brief_latest_snapshot
    FOREIGN KEY (issue_id, latest_snapshot_id)
    REFERENCES quant_system.brief_snapshots(issue_id, snapshot_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE IF NOT EXISTS quant_system.brief_snapshot_sources (
    id            BIGSERIAL PRIMARY KEY,
    snapshot_id   UUID NOT NULL REFERENCES quant_system.brief_snapshots(snapshot_id) ON DELETE CASCADE,
    source_type   TEXT NOT NULL,
    source_id     TEXT,
    source_uri    TEXT,
    payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quant_system.ai_news_daily_reports (
    owner_user_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'::uuid REFERENCES quant_system.app_users(id),
    provider      TEXT NOT NULL DEFAULT 'aihot',
    report_date   DATE NOT NULL,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    generated_at  TIMESTAMPTZ,
    lead          JSONB NOT NULL DEFAULT '{}'::jsonb,
    sections      JSONB NOT NULL DEFAULT '[]'::jsonb,
    flashes       JSONB NOT NULL DEFAULT '[]'::jsonb,
    warnings      JSONB NOT NULL DEFAULT '[]'::jsonb,
    raw           JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_user_id, provider, report_date)
);

ALTER TABLE quant_system.ai_news_daily_reports
    ADD COLUMN IF NOT EXISTS owner_user_id UUID NOT NULL
        DEFAULT '00000000-0000-0000-0000-000000000001'::uuid
        REFERENCES quant_system.app_users(id);

DO $$
DECLARE
    existing_pk_name TEXT;
    existing_pk_columns TEXT[];
BEGIN
    SELECT c.conname, array_agg(a.attname ORDER BY cols.ord)
    INTO existing_pk_name, existing_pk_columns
    FROM pg_constraint c
    JOIN unnest(c.conkey) WITH ORDINALITY AS cols(attnum, ord)
      ON true
    JOIN pg_attribute a
      ON a.attrelid = c.conrelid
     AND a.attnum = cols.attnum
    WHERE c.conrelid = 'quant_system.ai_news_daily_reports'::regclass
      AND c.contype = 'p'
    GROUP BY c.conname;

    IF existing_pk_name IS NOT NULL
       AND existing_pk_columns <> ARRAY['owner_user_id', 'provider', 'report_date'] THEN
        EXECUTE format(
            'ALTER TABLE quant_system.ai_news_daily_reports DROP CONSTRAINT %I',
            existing_pk_name
        );
        existing_pk_name := NULL;
    END IF;

    IF existing_pk_name IS NULL THEN
        ALTER TABLE quant_system.ai_news_daily_reports
            ADD CONSTRAINT ai_news_daily_reports_pkey
            PRIMARY KEY (owner_user_id, provider, report_date);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_brief_issues_owner_date
    ON quant_system.brief_issues (owner_user_id, issue_date DESC, locale);

CREATE INDEX IF NOT EXISTS idx_brief_snapshots_issue_version
    ON quant_system.brief_snapshots (issue_id, version DESC);

CREATE INDEX IF NOT EXISTS idx_brief_sources_snapshot_type
    ON quant_system.brief_snapshot_sources (snapshot_id, source_type);

CREATE INDEX IF NOT EXISTS idx_ai_news_daily_reports_owner_provider_date
    ON quant_system.ai_news_daily_reports (owner_user_id, provider, report_date DESC);
