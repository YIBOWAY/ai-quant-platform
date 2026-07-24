-- Optional read-through cache for AI HOT public news items.
--
-- The live AI HOT public API remains the primary source. These tables only keep
-- read-only news metadata so the local UI can show recent cached items when the
-- upstream source is temporarily unavailable.
--
-- Safety: no trading instructions, broker credentials, account identifiers,
-- secrets, private keys, or live order data belong in these tables.

CREATE SCHEMA IF NOT EXISTS quant_system;

CREATE TABLE IF NOT EXISTS quant_system.ai_news_items (
    provider     TEXT NOT NULL DEFAULT 'aihot',
    item_id      TEXT NOT NULL,
    title        TEXT NOT NULL,
    title_en     TEXT,
    url          TEXT NOT NULL,
    source       TEXT NOT NULL,
    published_at TIMESTAMPTZ,
    summary      TEXT,
    category     TEXT,
    score        DOUBLE PRECISION,
    selected     BOOLEAN,
    raw          JSONB NOT NULL DEFAULT '{}'::jsonb,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, item_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_news_items_provider_selected_published
    ON quant_system.ai_news_items (provider, selected, published_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_news_items_provider_category_published
    ON quant_system.ai_news_items (provider, category, published_at DESC);

CREATE TABLE IF NOT EXISTS quant_system.ai_news_fetches (
    id           BIGSERIAL PRIMARY KEY,
    provider     TEXT NOT NULL DEFAULT 'aihot',
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    mode         TEXT,
    category     TEXT,
    search_query TEXT,
    since        TIMESTAMPTZ,
    cursor       TEXT,
    take_count   INTEGER,
    item_count   INTEGER NOT NULL,
    warnings     JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_ai_news_fetches_provider_fetched
    ON quant_system.ai_news_fetches (provider, fetched_at DESC);
