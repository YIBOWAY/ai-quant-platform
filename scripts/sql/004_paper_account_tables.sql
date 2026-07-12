-- Optional PostgreSQL storage for the persistent paper account.
--
-- Creating these tables does not change the active source of truth. Runtime
-- configuration selects file-authoritative ``mirror`` or DB-authoritative
-- ``canonical`` only after explicit backfill, reconciliation, and human review.

CREATE SCHEMA IF NOT EXISTS quant_system;

CREATE TABLE IF NOT EXISTS quant_system.paper_accounts (
    account_id     TEXT PRIMARY KEY,
    owner_user_id  UUID NOT NULL REFERENCES quant_system.app_users(id),
    base_currency  TEXT NOT NULL,
    initial_cash   DOUBLE PRECISION NOT NULL,
    cash           DOUBLE PRECISION NOT NULL,
    realized_pnl   DOUBLE PRECISION NOT NULL,
    kill_switch    BOOLEAN NOT NULL,
    version        INTEGER NOT NULL DEFAULT 1,
    raw            JSONB NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS quant_system.paper_account_ledger (
    account_id          TEXT NOT NULL REFERENCES quant_system.paper_accounts(account_id) ON DELETE CASCADE,
    entry_id            TEXT NOT NULL,
    seq                 INTEGER NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL,
    kind                TEXT NOT NULL,
    source              TEXT NOT NULL,
    symbol              TEXT,
    side                TEXT,
    quantity            DOUBLE PRECISION,
    price               DOUBLE PRECISION,
    gross_value         DOUBLE PRECISION,
    commission          DOUBLE PRECISION NOT NULL DEFAULT 0,
    price_kind          TEXT,
    realized_pnl_delta  DOUBLE PRECISION NOT NULL DEFAULT 0,
    cash_after          DOUBLE PRECISION NOT NULL,
    note                TEXT NOT NULL DEFAULT '',
    raw                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, entry_id),
    UNIQUE (account_id, seq)
);

CREATE TABLE IF NOT EXISTS quant_system.paper_pending_orders (
    account_id  TEXT NOT NULL REFERENCES quant_system.paper_accounts(account_id) ON DELETE CASCADE,
    order_id    TEXT NOT NULL,
    payload     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, order_id)
);

CREATE TABLE IF NOT EXISTS quant_system.paper_positions_current (
    account_id       TEXT NOT NULL REFERENCES quant_system.paper_accounts(account_id) ON DELETE CASCADE,
    symbol           TEXT NOT NULL,
    quantity         DOUBLE PRECISION NOT NULL,
    avg_cost         DOUBLE PRECISION NOT NULL,
    source_quantity  JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, symbol)
);

CREATE TABLE IF NOT EXISTS quant_system.paper_position_snapshots (
    snapshot_id  UUID PRIMARY KEY,
    account_id   TEXT NOT NULL REFERENCES quant_system.paper_accounts(account_id) ON DELETE CASCADE,
    snapshot_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    equity       DOUBLE PRECISION NOT NULL,
    cash         DOUBLE PRECISION NOT NULL,
    source       TEXT NOT NULL DEFAULT 'account_json',
    metadata     JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS quant_system.paper_position_snapshot_rows (
    snapshot_id       UUID NOT NULL REFERENCES quant_system.paper_position_snapshots(snapshot_id) ON DELETE CASCADE,
    symbol            TEXT NOT NULL,
    quantity          DOUBLE PRECISION NOT NULL,
    avg_cost          DOUBLE PRECISION NOT NULL,
    last_price        DOUBLE PRECISION NOT NULL,
    market_value      DOUBLE PRECISION NOT NULL,
    unrealized_pnl    DOUBLE PRECISION NOT NULL,
    source_breakdown  JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (snapshot_id, symbol)
);

-- UNIQUE (account_id, seq) already owns an equivalent B-tree. Remove the
-- historical duplicate if an earlier version of this migration created it.
DROP INDEX IF EXISTS quant_system.idx_paper_ledger_account_seq;

CREATE INDEX IF NOT EXISTS idx_paper_snapshots_account_time
    ON quant_system.paper_position_snapshots (account_id, snapshot_at DESC);
