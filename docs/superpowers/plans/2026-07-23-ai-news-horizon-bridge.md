# AI News × Horizon Bridge Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `/ai-news` and Brief an automatic AI HOT → Horizon Postgres failover so the research feed survives AI HOT permanent downtime, without embedding Horizon or running its pipeline on the request path.

**Architecture:** Keep AI HOT as the live primary client. Run Horizon in a same-host Docker sidecar that exports an inbox contract under `data/horizon_inbox/`. A CLI ingest path writes normalized items/daily/run metadata into existing `ai_news_*` tables plus new `ai_news_provider_runs`. A `NewsFacade` serves `preference=auto|aihot|horizon` on neutral `/api/news/*` routes and thin aliases of `/api/news/aihot/*`. Failover reads Postgres only.

**Tech Stack:** Python 3.11+ · FastAPI · pydantic-settings · httpx · Typer CLI · PostgreSQL · Next.js 15 · TanStack Query · pytest · Docker Compose

**Spec:** [docs/superpowers/specs/2026-07-23-ai-news-horizon-bridge-design.md](../specs/2026-07-23-ai-news-horizon-bridge-design.md)

## Global Constraints

- Research-only: no strategy/factor/backtest/paper/trading mutations from news paths.
- Request path never runs Horizon pipeline, MCP, or LLM calls.
- Failover authority is PostgreSQL only (no volume direct-read on GET).
- Default preference is `auto`; success responses always stamp `provider`, `preference`, `served_from`, `warnings`, `research_safety`.
- Top-level response field must remain `research_safety` (never `safety`).
- Tests never hit real `aihot.virxact.com`, real LLM, or a live Horizon container; use mocks + inbox fixtures + fake/test DB.
- Migrations apply only via `quant-system migrate --apply --allow <file> [--yes]`.
- Keep existing `/api/news/aihot/*` URLs working; path name is a compatibility alias, default semantics become facade `auto`.
- Do not vendor Horizon source into `quant_system` runtime.

## File Structure

| Path | Responsibility |
|---|---|
| `src/quant_system/news/models.py` | Keep `AiHotItem`/`AiHotDaily`/pages; add `ServedFrom` literals helpers if needed |
| `src/quant_system/news/facade.py` | **Create** — auto/aihot/horizon selection + response stamping |
| `src/quant_system/news/horizon_inbox.py` | **Create** — parse READY runs from inbox dir |
| `src/quant_system/news/horizon_ingest.py` | **Create** — transactional PG upsert from parsed run |
| `src/quant_system/news/horizon_repository.py` | **Create** — load fresh horizon items/daily/runs from PG |
| `src/quant_system/news/repository.py` | Keep aihot cache; do not hard-block other providers |
| `src/quant_system/news/daily_report_repository.py` | Generalize provider param or add horizon write/load helpers |
| `src/quant_system/api/schemas/news.py` | Add `preference`/`served_from`; extend status schema |
| `src/quant_system/api/routes/news.py` | Delegate to facade; add neutral routes; keep aihot aliases |
| `src/quant_system/config/settings.py` | Add `HorizonSettings` + `NewsSettings`; nest on `Settings` |
| `src/quant_system/cli.py` | Add `news` typer group + `horizon-ingest` |
| `scripts/sql/009_ai_news_provider_runs.sql` | **Create** — runs table + indexes |
| `deploy/horizon/*` | Dockerfile, entrypoint, export script, example config |
| `docker-compose.horizon.yml` | **Create** — horizon service + volumes |
| `data/horizon_inbox/.gitkeep` | Inbox root |
| `data/horizon_config/.gitignore` | Ignore secrets/config |
| `src/frontend/lib/api.ts` | Types + `getNews*` / keep `getAiHot*` as wrappers |
| `src/frontend/components/forms/AiNewsView.tsx` | Provider/failover status strip + copy |
| `src/frontend/app/brief/page.tsx` | Digest via auto facade; watermark meta |
| `docs/guides/ai-news.md` | Dual-source guide |
| `docs/execution/ai-news-horizon.md` | **Create** — ops runbook |
| `docs/INDEX.md` | Link spec/plan/guide/execution |
| `tests/test_news_facade.py` | **Create** |
| `tests/test_news_horizon_inbox.py` | **Create** |
| `tests/test_news_horizon_ingest.py` | **Create** |
| `tests/test_news_horizon_repository.py` | **Create** |
| `tests/test_api_news_facade.py` | **Create** — neutral + alias HTTP matrix |
| `tests/test_settings_news_horizon.py` | **Create** |
| `tests/test_api_news_aihot.py` | Update expectations for new stamp fields |
| `tests/test_frontend_ai_news_contract.py` | Update contract for new fields |
| `tests/fixtures/horizon_inbox/...` | READY run fixture |

---

### Task 1: Settings — News + Horizon config

**Files:**
- Modify: `src/quant_system/config/settings.py`
- Create: `tests/test_settings_news_horizon.py`
- Modify: `.env.example` (if present; add commented keys)

**Interfaces:**
- Produces:
  - `class NewsSettings`: `source_preference: Literal["auto","aihot","horizon"] = "auto"`, `failover_enabled: bool = True`
  - `class HorizonSettings`: `enabled: bool = True`, `inbox_dir: str`, `max_age_seconds: int = 129600`, `provider_beta: bool = False`, `ingest_on_read: bool = False`
  - `Settings.news: NewsSettings`, `Settings.horizon: HorizonSettings`
- Env: `QS_NEWS_SOURCE_PREFERENCE`, `QS_NEWS_FAILOVER_ENABLED`, `QS_HORIZON_ENABLED`, `QS_HORIZON_INBOX_DIR`, `QS_HORIZON_MAX_AGE_SECONDS`, `QS_HORIZON_PROVIDER_BETA`, `QS_HORIZON_INGEST_ON_READ`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_settings_news_horizon.py
from quant_system.config.settings import Settings


def test_news_and_horizon_settings_defaults(monkeypatch, tmp_path):
    monkeypatch.delenv("QS_NEWS_SOURCE_PREFERENCE", raising=False)
    monkeypatch.delenv("QS_HORIZON_ENABLED", raising=False)
    monkeypatch.delenv("QS_HORIZON_INBOX_DIR", raising=False)
    settings = Settings()
    assert settings.news.source_preference == "auto"
    assert settings.news.failover_enabled is True
    assert settings.horizon.enabled is True
    assert settings.horizon.max_age_seconds == 129_600
    assert settings.horizon.provider_beta is False
    assert settings.horizon.ingest_on_read is False
    assert "horizon_inbox" in settings.horizon.inbox_dir.replace("\\", "/")


def test_horizon_settings_env_override(monkeypatch):
    monkeypatch.setenv("QS_NEWS_SOURCE_PREFERENCE", "horizon")
    monkeypatch.setenv("QS_NEWS_FAILOVER_ENABLED", "false")
    monkeypatch.setenv("QS_HORIZON_ENABLED", "false")
    monkeypatch.setenv("QS_HORIZON_MAX_AGE_SECONDS", "3600")
    monkeypatch.setenv("QS_HORIZON_INBOX_DIR", "/tmp/hz-inbox")
    settings = Settings()
    assert settings.news.source_preference == "horizon"
    assert settings.news.failover_enabled is False
    assert settings.horizon.enabled is False
    assert settings.horizon.max_age_seconds == 3600
    assert settings.horizon.inbox_dir == "/tmp/hz-inbox"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_settings_news_horizon.py -q`  
Expected: FAIL (`Settings` has no `news`/`horizon`)

- [ ] **Step 3: Implement settings**

Add after `AiHotSettings` in `settings.py` (mirror its `SettingsConfigDict` / `AliasChoices` style):

```python
class NewsSettings(BaseSettings):
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
```

On `Settings`:

```python
news: NewsSettings = Field(default_factory=NewsSettings)
horizon: HorizonSettings = Field(default_factory=HorizonSettings)
```

Ensure `Literal` and `Path` imports exist. Default `inbox_dir` must resolve to repo `data/horizon_inbox` (adjust parent hops if `settings.py` depth differs — verify with the test).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_settings_news_horizon.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/quant_system/config/settings.py tests/test_settings_news_horizon.py .env.example
git commit -m "feat(news): add NewsSettings and HorizonSettings"
```

---

### Task 2: API schema stamps (`preference`, `served_from`)

**Files:**
- Modify: `src/quant_system/api/schemas/news.py`
- Modify: `tests/test_api_news_aihot.py` (assert new fields on success path)
- Modify: `tests/test_frontend_ai_news_contract.py` if it freezes response keys

**Interfaces:**
- Produces on items/daily/dailies responses:
  - `preference: str`
  - `served_from: Literal["primary","failover","cache","forced"]`
- Status later extended in Task 6; this task only content endpoints + keep backward-compatible required fields.

- [ ] **Step 1: Write/adjust failing assertions**

In `test_aihot_items_route_returns_research_only_payload` after existing asserts:

```python
assert payload["preference"] == "auto"
assert payload["served_from"] == "primary"
assert "research_safety" in payload
assert "safety" not in payload or payload.get("safety")  # global middleware may inject footer safety; research_safety must still exist
```

Same `preference`/`served_from` on daily success test if present.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_api_news_aihot.py::test_aihot_items_route_returns_research_only_payload -q`  
Expected: FAIL missing keys

- [ ] **Step 3: Extend schemas and temporary route stamping**

In `schemas/news.py`, add fields to `AiHotItemsResponse`, `AiHotDailyResponse`, `AiHotDailiesResponse`:

```python
preference: str = "auto"
served_from: str = "primary"
```

In `routes/news.py` `_items_payload` / `_daily_payload` / `_dailies_payload`, add:

```python
"preference": "auto",
"served_from": "primary",
```

(Facade will own real values in Task 5; this unblocks contract.)

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_api_news_aihot.py -q`  
Expected: PASS (update any snapshot/contract tests in the same commit)

- [ ] **Step 5: Commit**

```bash
git add src/quant_system/api/schemas/news.py src/quant_system/api/routes/news.py tests/test_api_news_aihot.py tests/test_frontend_ai_news_contract.py
git commit -m "feat(news): stamp preference and served_from on news responses"
```

---

### Task 3: Horizon inbox parser

**Files:**
- Create: `src/quant_system/news/horizon_inbox.py`
- Create: `tests/test_news_horizon_inbox.py`
- Create: `tests/fixtures/horizon_inbox/runs/20260723T120000Z-ab12/{meta.json,items.json,summary-zh.md,READY}`

**Interfaces:**
- Produces:
  - `@dataclass frozen HorizonInboxRun`: `run_id`, `path`, `meta: dict`, `items: list[AiHotItem]`, `daily: AiHotDaily | None`, `content_digest: str`
  - `def iter_ready_runs(inbox_dir: str | Path) -> list[HorizonInboxRun]`
  - `def load_run(run_dir: Path) -> HorizonInboxRun`  
- Rules: skip without `READY`; require `meta.json` + `items.json`; build `AiHotItem` with `selected=True` when score present; daily from `daily.json` else weak markdown synthesis; `content_digest` = sha256 of canonical meta+items bytes.

- [ ] **Step 1: Create fixture + failing test**

Fixture `items.json`:

```json
[
  {
    "id": "hz-1",
    "title": "Horizon sample",
    "title_en": "Horizon sample",
    "url": "https://example.com/hz-1",
    "source": "HN",
    "published_at": "2026-07-23T11:00:00+00:00",
    "summary": "fixture summary",
    "category": "industry",
    "score": 8.5
  }
]
```

`meta.json`:

```json
{
  "run_id": "20260723T120000Z-ab12",
  "generated_at": "2026-07-23T12:00:00+00:00",
  "item_count": 1,
  "status": "ok"
}
```

Test:

```python
from pathlib import Path
from quant_system.news.horizon_inbox import iter_ready_runs

FIXTURE = Path(__file__).parent / "fixtures" / "horizon_inbox"

def test_iter_ready_runs_parses_fixture(tmp_path):
    # copy fixture tree to tmp_path or point at FIXTURE
    runs = iter_ready_runs(FIXTURE)
    assert len(runs) == 1
    run = runs[0]
    assert run.run_id == "20260723T120000Z-ab12"
    assert len(run.items) == 1
    assert run.items[0].id == "hz-1"
    assert run.items[0].url.startswith("https://")
    assert run.content_digest
    assert run.daily is not None  # from summary-zh.md weak synthesis or daily.json


def test_skips_runs_without_ready(tmp_path):
    run_dir = tmp_path / "runs" / "nope"
    run_dir.mkdir(parents=True)
    (run_dir / "meta.json").write_text("{}", encoding="utf-8")
    (run_dir / "items.json").write_text("[]", encoding="utf-8")
    assert iter_ready_runs(tmp_path) == []
```

- [ ] **Step 2: Run — expect FAIL**

Run: `python -m pytest tests/test_news_horizon_inbox.py -q`

- [ ] **Step 3: Implement `horizon_inbox.py`**

Minimal implementation sketch:

```python
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass
from pathlib import Path
from quant_system.news.models import AiHotDaily, AiHotItem, utc_now_iso

@dataclass(frozen=True)
class HorizonInboxRun:
    run_id: str
    path: Path
    meta: dict
    items: list[AiHotItem]
    daily: AiHotDaily | None
    content_digest: str

def iter_ready_runs(inbox_dir: str | Path) -> list[HorizonInboxRun]:
    root = Path(inbox_dir) / "runs"
    if not root.is_dir():
        return []
    found: list[HorizonInboxRun] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "READY").is_file():
            found.append(load_run(child))
    return found

def load_run(run_dir: Path) -> HorizonInboxRun:
    meta_raw = (run_dir / "meta.json").read_bytes()
    items_raw = (run_dir / "items.json").read_bytes()
    meta = json.loads(meta_raw.decode("utf-8"))
    raw_items = json.loads(items_raw.decode("utf-8"))
    if not isinstance(raw_items, list):
        raise ValueError("items.json must be a list")
    items = [_parse_item(obj) for obj in raw_items if isinstance(obj, dict)]
    daily = _load_daily(run_dir, meta, items)
    digest = hashlib.sha256(meta_raw + b"\n" + items_raw).hexdigest()
    run_id = str(meta.get("run_id") or run_dir.name)
    return HorizonInboxRun(
        run_id=run_id,
        path=run_dir,
        meta=meta if isinstance(meta, dict) else {},
        items=items,
        daily=daily,
        content_digest=digest,
    )

def _parse_item(obj: dict) -> AiHotItem:
    url = str(obj.get("url") or "")
    item_id = str(obj.get("id") or "") or hashlib.sha256(url.encode()).hexdigest()[:16]
    score = obj.get("score")
    score_f = float(score) if score is not None else None
    return AiHotItem(
        id=item_id,
        title=str(obj.get("title") or ""),
        title_en=obj.get("title_en"),
        url=url,
        source=str(obj.get("source") or "unknown"),
        published_at=obj.get("published_at"),
        summary=obj.get("summary"),
        category=obj.get("category"),
        score=score_f,
        selected=True if score_f is not None else obj.get("selected"),
        raw=dict(obj),
    )

def _load_daily(run_dir: Path, meta: dict, items: list[AiHotItem]) -> AiHotDaily | None:
    daily_path = run_dir / "daily.json"
    if daily_path.is_file():
        payload = json.loads(daily_path.read_text(encoding="utf-8"))
        # map fields → AiHotDaily
        ...
    zh = run_dir / "summary-zh.md"
    en = run_dir / "summary-en.md"
    if not zh.is_file() and not en.is_file():
        return None
    generated = str(meta.get("generated_at") or utc_now_iso())
    date = str(meta.get("daily_date") or generated[:10])
    sections = []
    if zh.is_file():
        sections.append({"label": "summary-zh", "markdown": zh.read_text(encoding="utf-8")})
    if en.is_file():
        sections.append({"label": "summary-en", "markdown": en.read_text(encoding="utf-8")})
    lead_title = items[0].title if items else date
    return AiHotDaily(
        date=date,
        generated_at=generated,
        window_start=meta.get("window_start"),
        window_end=meta.get("window_end"),
        lead={"title": lead_title},
        sections=sections,
        flashes=[],
        warnings=[],
        raw={"source": "horizon_inbox", "run_id": meta.get("run_id")},
    )
```

Enforce max items (e.g. 500) and reject empty title/url.

- [ ] **Step 4: Run tests — PASS**

Run: `python -m pytest tests/test_news_horizon_inbox.py -q`

- [ ] **Step 5: Commit**

```bash
git add src/quant_system/news/horizon_inbox.py tests/test_news_horizon_inbox.py tests/fixtures/horizon_inbox
git commit -m "feat(news): parse Horizon inbox READY runs"
```

---

### Task 4: Migration `009_ai_news_provider_runs` + horizon repository

**Files:**
- Create: `scripts/sql/009_ai_news_provider_runs.sql`
- Create: `src/quant_system/news/horizon_repository.py`
- Create: `tests/test_news_horizon_repository.py`
- Modify: `src/quant_system/news/daily_report_repository.py` — accept `provider: str` parameter on cache/load **or** add `cache_news_daily_report(..., provider=)` / `load_cached_news_daily_report(..., provider=)` keeping aihot wrappers.

**Interfaces:**
- Produces:
  - `def load_latest_horizon_run(*, settings, now=None) -> dict | None`  
    (`run_id`, `generated_at`, `item_count`, `status`, `ingested_at`, …) only `status=ingested`, `item_count>0`, within `max_age_seconds`
  - `def load_horizon_items_page(*, settings, take, category=None, q=None, since=None) -> AiHotItemsPage | None`
  - `def load_horizon_daily(*, settings, date: str | None) -> AiHotDaily | None`
  - `def load_horizon_dailies(*, settings, take: int) -> AiHotDailiesPage | None`
  - `def record_provider_run(...)` / used by ingest
  - `def is_run_ingested(provider, run_id, content_digest, settings) -> bool`

- [ ] **Step 1: Write SQL**

```sql
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
```

- [ ] **Step 2: Repository tests with fake DB or monkeypatch**

Follow `tests/test_news_aihot_repository.py` style (fake connect / skip if pattern uses monkeypatch). Cover:
- fresh run returned
- stale run (generated_at too old) → None
- item_count=0 → not fresh
- items load filters `provider='horizon'`

- [ ] **Step 3: Implement `horizon_repository.py`**

Reuse `get_database`, `SCHEMA`, JSON helpers from existing repositories.  
When inserting items for horizon, mirror `cache_aihot_items` SQL but `provider='horizon'`. Prefer extracting shared `_upsert_items(provider, page, ...)` inside `repository.py` to avoid duplication — keep aihot function names as thin wrappers.

Generalize daily report:

```python
def cache_news_daily_report(daily: AiHotDaily, *, settings: Settings, provider: str) -> None: ...
def load_cached_news_daily_report(date: str, *, settings: Settings, provider: str) -> AiHotDaily | None: ...

def cache_aihot_daily_report(daily, *, settings):
    return cache_news_daily_report(daily, settings=settings, provider="aihot")
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_news_horizon_repository.py tests/test_news_aihot_repository.py tests/test_news_daily_report_repository.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/sql/009_ai_news_provider_runs.sql src/quant_system/news/horizon_repository.py src/quant_system/news/repository.py src/quant_system/news/daily_report_repository.py tests/test_news_horizon_repository.py
git commit -m "feat(news): horizon PG repository and provider_runs migration"
```

---

### Task 5: Horizon ingest CLI

**Files:**
- Create: `src/quant_system/news/horizon_ingest.py`
- Modify: `src/quant_system/cli.py` — `news_app` + command
- Create: `tests/test_news_horizon_ingest.py`
- Create: `data/horizon_inbox/.gitkeep`

**Interfaces:**
- Produces:
  - `def ingest_horizon_inbox(*, settings: Settings, run_id: str | None = None) -> dict`  
    returns `{ "ingested": [run_id...], "skipped": [...], "failed": [{run_id, error}] }`
  - CLI: `quant-system news horizon-ingest [--inbox DIR] [--run-id ID] [--once]`
- Transaction: items + daily + provider_runs succeed together; on failure record `status=failed` only if safe, never half-write items without run row consistency (prefer all-or-nothing per run).

- [ ] **Step 1: Failing unit test with monkeypatched DB**

```python
def test_ingest_writes_provider_run_and_items(monkeypatch, tmp_path):
    # copy fixture inbox into tmp_path
    # monkeypatch get_database to capturing fake
    from quant_system.config.settings import Settings, HorizonSettings
    from quant_system.news.horizon_ingest import ingest_horizon_inbox
    settings = Settings()
    settings.horizon = HorizonSettings(inbox_dir=str(tmp_path), enabled=True)
    result = ingest_horizon_inbox(settings=settings)
    assert "20260723T120000Z-ab12" in result["ingested"]
    # second call skips
    result2 = ingest_horizon_inbox(settings=settings)
    assert "20260723T120000Z-ab12" in result2["skipped"]
```

- [ ] **Step 2: Implement ingest**

```python
PROVIDER = "horizon"

def ingest_horizon_inbox(*, settings, run_id=None):
    runs = iter_ready_runs(settings.horizon.inbox_dir)
    if run_id:
        runs = [r for r in runs if r.run_id == run_id]
    ingested, skipped, failed = [], [], []
    for run in runs:
        if is_run_ingested("horizon", run.run_id, run.content_digest, settings):
            skipped.append(run.run_id)
            continue
        try:
            persist_horizon_run(run, settings=settings)  # in horizon_repository
            ingested.append(run.run_id)
            marker = run.path / "INGESTED"
            marker.write_text(run.content_digest, encoding="utf-8")
        except Exception as exc:
            failed.append({"run_id": run.run_id, "error": str(exc)})
            log.exception("horizon ingest failed for %s", run.run_id)
    return {"ingested": ingested, "skipped": skipped, "failed": failed}
```

- [ ] **Step 3: CLI registration** near other apps in `cli.py`:

```python
news_app = typer.Typer(help="Read-only AI news maintenance commands.")

@news_app.command("horizon-ingest")
def news_horizon_ingest(
    inbox: Annotated[str | None, typer.Option("--inbox")] = None,
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
    once: Annotated[bool, typer.Option("--once")] = True,
) -> None:
    settings = load_settings()
    if inbox:
        settings.horizon.inbox_dir = inbox  # prefer model_copy if frozen
    from quant_system.news.horizon_ingest import ingest_horizon_inbox
    result = ingest_horizon_inbox(settings=settings, run_id=run_id)
    typer.echo(json.dumps(result, sort_keys=True))

# bottom:
app.add_typer(news_app, name="news")
```

Add CLI smoke test with `CliRunner` if the repo pattern exists; else unit-test ingest only.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_news_horizon_ingest.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/quant_system/news/horizon_ingest.py src/quant_system/cli.py tests/test_news_horizon_ingest.py data/horizon_inbox/.gitkeep
git commit -m "feat(news): horizon-ingest CLI and persist path"
```

---

### Task 6: NewsFacade + route wiring (auto failover)

**Files:**
- Create: `src/quant_system/news/facade.py`
- Create: `tests/test_news_facade.py`
- Create: `tests/test_api_news_facade.py`
- Modify: `src/quant_system/api/routes/news.py`
- Modify: `src/quant_system/api/schemas/news.py` (status shape)
- Modify: `tests/test_api_news_aihot.py` (disabled/failover behaviors)

**Interfaces:**
- Produces:
  - `class NewsFacade`:
    - `items(self, *, preference, mode, category, q, since, cursor, take) -> dict`
    - `daily(self, *, preference, date) -> dict`
    - `dailies(self, *, preference, take) -> dict`
    - `status(self) -> dict`
  - Routes:
    - `GET /api/news/items|daily|dailies|status`
    - `GET /api/news/aihot/*` → same facade, default preference from settings (`auto`)
  - Auto order: aihot live → horizon PG fresh → aihot cache → error `news_unavailable`

- [ ] **Step 1: Facade unit tests (no HTTP)**

```python
def test_auto_primary_aihot():
    facade = NewsFacade(aihot_client=FakeOk(), settings=settings_with_failover, horizon_loader=FakeHorizonEmpty())
    payload = facade.items(preference="auto", mode="selected", take=10)
    assert payload["provider"] == "aihot"
    assert payload["served_from"] == "primary"

def test_auto_failover_horizon():
    facade = NewsFacade(aihot_client=FakeTimeout(), settings=..., horizon_loader=FakeHorizonFresh())
    payload = facade.items(preference="auto", mode="selected", take=10)
    assert payload["provider"] == "horizon"
    assert payload["served_from"] == "failover"
    assert any("failover" in w for w in payload["warnings"])

def test_auto_cache_when_horizon_missing():
    ...

def test_auto_unavailable():
    with pytest.raises(NewsFacadeError) as ei:
        facade.items(...)
    assert ei.value.code == "news_unavailable"

def test_forced_horizon_stale():
    ...
```

- [ ] **Step 2: Implement facade**

```python
class NewsFacadeError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 503):
        self.code = code
        self.message = message
        self.status_code = status_code

class NewsFacade:
    def items(...):
        pref = preference or self.settings.news.source_preference
        if pref == "aihot":
            return self._aihot_items(..., forced=True)
        if pref == "horizon":
            return self._horizon_items(..., forced=True)
        # auto
        if not self.settings.news.failover_enabled or not self.settings.horizon.enabled:
            return self._aihot_items_with_cache_only(...)
        try:
            page = self._aihot_live_items(...)
            self._cache_aihot(page)
            return self._stamp_items(page, provider="aihot", preference="auto", served_from="primary")
        except AiHotProviderError as exc:
            self._remember(exc)
            hz = self._horizon_items_page(...)
            if hz is not None:
                return self._stamp_items(
                    hz, provider="horizon", preference="auto", served_from="failover",
                    extra_warnings=[exc.message, "served_from=horizon_failover", f"horizon_run_id=..."],
                )
            cached = self._aihot_cache(...)
            if cached is not None:
                return self._stamp_items(cached, provider="aihot", preference="auto", served_from="cache",
                                         extra_warnings=[exc.message, "aihot_cache_fallback"])
            raise NewsFacadeError("news_unavailable", f"aihot={exc.message}; horizon=unavailable", 503)
```

Mirror for daily. Dailies: aihot live or horizon index from daily_reports where provider=horizon.

Status payload per spec §6.5 — **must not** call aihot client.

- [ ] **Step 3: Wire routes**

Replace body of `aihot_items` / `daily` / `dailies` / `status` with facade calls.  
Add neutral routes that call the same handlers with optional `preference` query:

```python
preference: Literal["auto", "aihot", "horizon"] | None = None
```

When `None`, use `settings.news.source_preference`.

Map `NewsFacadeError` → HTTPException detail `{code, message}`.  
Keep `_ensure_enabled` **out** of auto path when aihot disabled (auto should still try horizon). Only forced aihot uses aihot_disabled.

Important behavior change vs today:
- `QS_AIHOT_ENABLED=false` + auto + fresh horizon ⇒ **200 failover**, not 503 aihot_disabled.
- Update `test_api_news_aihot.py` tests that expected 503 on disabled for items — split into forced vs auto cases.

- [ ] **Step 4: HTTP matrix tests**

```python
# tests/test_api_news_facade.py
# 1 primary, 2 failover, 3 cache, 4 unavailable, 5 aihot disabled auto failover,
# 6 forced aihot disabled still 503, status no client calls
```

Run:

```bash
python -m pytest tests/test_news_facade.py tests/test_api_news_facade.py tests/test_api_news_aihot.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/quant_system/news/facade.py src/quant_system/api/routes/news.py src/quant_system/api/schemas/news.py tests/test_news_facade.py tests/test_api_news_facade.py tests/test_api_news_aihot.py
git commit -m "feat(news): NewsFacade auto failover and neutral routes"
```

---

### Task 7: Frontend API + AI News UI stamps

**Files:**
- Modify: `src/frontend/lib/api.ts`
- Modify: `src/frontend/components/forms/AiNewsView.tsx`
- Modify: `tests/test_frontend_ai_news_contract.py`
- Optional: frontend vitest if present for AiNewsView

**Interfaces:**
- Extend `AiHotItemsResponse` / daily / dailies / status types:
  - `preference?: string`
  - `served_from?: "primary" | "failover" | "cache" | "forced"`
  - status: nested `providers` optional for forward compat — if backend ships nested status, type it; UI may read either legacy flat aihot fields or nested
- Add:
  - `getNewsItems(query)` → `/api/news/items`
  - `getNewsDaily`, `getNewsDailies`, `getNewsStatus`
- Keep `getAiHot*` calling **neutral** paths (or old aliases); both OK if facade-backed. Prefer neutral.

- [ ] **Step 1: Update contract test expectations** for new fields optional/required as implemented.

- [ ] **Step 2: Implement api.ts types + functions**

```typescript
export type NewsServedFrom = "primary" | "failover" | "cache" | "forced";

// on AiHotItemsResponse:
preference?: string;
served_from?: NewsServedFrom;

export function getNewsItems(query: AiHotItemsQuery & { preference?: "auto"|"aihot"|"horizon" } = {}) {
  const params = new URLSearchParams();
  // same as getAiHotItems + preference
  return apiGet<AiHotItemsResponse>(`/api/news/items?${params}`, fallback);
}

export function getAiHotItems(query: AiHotItemsQuery = {}) {
  return getNewsItems(query); // alias
}
```

Status fallback should not invent a live probe.

- [ ] **Step 3: AiNewsView**

- Show `provider` from items/daily response (not only status).
- If `served_from === "failover"`, StatusPill or banner: failover active.
- Copy update (zh/en): main source AI HOT beta; standby self-hosted Horizon; verify originals; research-only.
- Keep filters/tabs.

- [ ] **Step 4: Run**

```bash
python -m pytest tests/test_frontend_ai_news_contract.py -q
npm --prefix src/frontend run type-check
```

- [ ] **Step 5: Commit**

```bash
git add src/frontend/lib/api.ts src/frontend/components/forms/AiNewsView.tsx tests/test_frontend_ai_news_contract.py
git commit -m "feat(news): frontend dual-source stamps and neutral API client"
```

---

### Task 8: Brief digest uses auto facade metadata

**Files:**
- Modify: `src/frontend/app/brief/page.tsx`
- Modify: brief payload/zod if needed (`src/frontend/lib/briefArchive.ts`) — only optional meta
- Tests: any brief contract test that freezes `ai_news` watermark

**Interfaces:**
- `getAiHotItems({ take: 6 })` already aliases auto — ensure no hardcoded expect `provider: "aihot"` only.
- When building watermark / source row for ai_news, include:
  - `provider: digest.provider`
  - `served_from: digest.served_from`
  - short warnings join
- On `digest.apiError` or empty items: `ai_news: []`, do not throw; keep other brief sections.

- [ ] **Step 1: Locate digest mapping** (`digestItems`, `ai_news:` around lines ~804–950) and write/adjust a focused test if one exists; else add a small pure helper test:

```typescript
// e.g. mapDigestToBriefAiNews(digest) unit test in frontend vitest
```

Or Python contract if brief mapping stays in TS only — then manual assert via type-check + existing brief tests.

- [ ] **Step 2: Implement mapping**

```typescript
const digest = await getNewsItems({ take: 6, preference: "auto" });
// ...
ai_news: digestItems.map((item) => ({
  title: item.title,
  url: item.url,
  source: item.source,
  // existing fields...
})),
// watermark / sources entry:
{
  name: "ai_news",
  provider: digest.provider,
  served_from: digest.served_from,
  detail: digest.apiError ?? `${digest.provider}/${digest.served_from ?? "primary"}`,
}
```

Ensure zod schemas treat unknown watermark keys as passthrough or optional.

- [ ] **Step 3: Run brief-related tests + type-check**

```bash
python -m pytest tests/test_api_brief_persistence.py -q  # if unrelated failures, don't "fix" by weakening
npm --prefix src/frontend run type-check
```

- [ ] **Step 4: Commit**

```bash
git add src/frontend/app/brief/page.tsx src/frontend/lib/briefArchive.ts src/frontend/lib/api.ts
git commit -m "feat(brief): ai_news digest follows news auto failover"
```

---

### Task 9: Docker Horizon sidecar + export contract

**Files:**
- Create: `deploy/horizon/Dockerfile`
- Create: `deploy/horizon/entrypoint.sh`
- Create: `deploy/horizon/export_run.py`
- Create: `deploy/horizon/config.example.json`
- Create: `docker-compose.horizon.yml`
- Create: `data/horizon_config/.gitignore` (`*` + `!.gitignore` + `!config.example.json` if linked)
- Create: `docs/execution/ai-news-horizon.md`

**Interfaces:**
- Container writes only under `/inbox/runs/<run_id>/` then `READY`.
- Does not connect to Postgres.
- Pins Horizon upstream git SHA in Dockerfile `ARG HORIZON_REF=...`.
- Env: LLM keys via `env_file: data/horizon_config/.env`.
- Interval default 6h.

- [ ] **Step 1: Write export unit test (host-side)** for `export_run.py` pure function if importable — or document manual verification only. Prefer:

```python
# tests/test_horizon_export_run.py
# given a fake upstream output dir, export_run produces READY + items.json schema
```

If export script is bash-only, keep logic in `export_run.py`.

- [ ] **Step 2: Implement Dockerfile + entrypoint**

```dockerfile
FROM python:3.12-slim
ARG HORIZON_REF=main
# pin to a commit SHA when known
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/horizon
RUN git clone https://github.com/Thysrael/Horizon.git . && git checkout ${HORIZON_REF}
RUN pip install --no-cache-dir uv && uv sync
COPY export_run.py /opt/bin/export_run.py
COPY entrypoint.sh /opt/bin/entrypoint.sh
RUN chmod +x /opt/bin/entrypoint.sh
ENV HORIZON_INBOX=/inbox
ENV HORIZON_RUN_INTERVAL_SECONDS=21600
ENTRYPOINT ["/opt/bin/entrypoint.sh"]
```

`entrypoint.sh`:

```bash
#!/bin/sh
set -eu
INTERVAL="${HORIZON_RUN_INTERVAL_SECONDS:-21600}"
while true; do
  # run upstream CLI; on failure log and sleep
  uv run horizon || true
  python /opt/bin/export_run.py --horizon-data /opt/horizon/data --inbox "${HORIZON_INBOX}"
  sleep "$INTERVAL"
done
```

`export_run.py` must implement inbox contract from Task 3. If upstream output shape is uncertain, parse best-effort and still emit valid empty/non-empty items with meta; never write READY on exception.

`docker-compose.horizon.yml`:

```yaml
services:
  horizon:
    build:
      context: ./deploy/horizon
      args:
        HORIZON_REF: "<pin commit>"
    env_file:
      - ./data/horizon_config/.env
    volumes:
      - ./data/horizon_inbox:/inbox
      - ./data/horizon_config:/config:ro
    restart: unless-stopped
```

- [ ] **Step 3: Execution runbook** `docs/execution/ai-news-horizon.md` covering: key setup, `compose up`, first ingest, migrate 009, failover drill (`QS_AIHOT_ENABLED=false`), cron example for ingest every 10 minutes.

- [ ] **Step 4: Offline tests still pass without Docker**

```bash
python -m pytest tests/test_news_horizon_inbox.py tests/test_news_facade.py tests/test_api_news_facade.py -q
```

- [ ] **Step 5: Commit**

```bash
git add deploy/horizon docker-compose.horizon.yml data/horizon_config docs/execution/ai-news-horizon.md tests/test_horizon_export_run.py
git commit -m "feat(news): Horizon Docker sidecar and export inbox contract"
```

---

### Task 10: Docs index + guide + design cross-links

**Files:**
- Modify: `docs/guides/ai-news.md`
- Modify: `docs/INDEX.md`
- Modify: `docs/design/ai_news_integration_plan.md` (decision log pointer)
- Modify: `docs/superpowers/specs/2026-07-23-ai-news-horizon-bridge-design.md` status → implemented-in-progress / link plan

- [ ] **Step 1: Update guide** — dual source, auto failover order, config table, migrate command:

```bash
quant-system migrate --apply --allow 009_ai_news_provider_runs.sql --yes
quant-system news horizon-ingest --once
```

- [ ] **Step 2: INDEX links** under design/guides/execution.

- [ ] **Step 3: Commit**

```bash
git add docs/guides/ai-news.md docs/INDEX.md docs/design/ai_news_integration_plan.md docs/superpowers/specs/2026-07-23-ai-news-horizon-bridge-design.md
git commit -m "docs(news): Horizon bridge guide and index links"
```

---

### Task 11: Full verification gate

- [ ] **Step 1: Backend suite (news-focused + safety)**

```bash
python -m pytest \
  tests/test_settings_news_horizon.py \
  tests/test_news_horizon_inbox.py \
  tests/test_news_horizon_repository.py \
  tests/test_news_horizon_ingest.py \
  tests/test_news_facade.py \
  tests/test_api_news_facade.py \
  tests/test_api_news_aihot.py \
  tests/test_news_aihot_repository.py \
  tests/test_news_daily_report_repository.py \
  tests/test_frontend_ai_news_contract.py \
  tests/test_api_safety.py \
  -q
```

Expected: all PASS

- [ ] **Step 2: Frontend**

```bash
npm --prefix src/frontend run type-check
npm --prefix src/frontend run lint
```

- [ ] **Step 3: Ruff**

```bash
ruff check src/quant_system/news src/quant_system/api/routes/news.py src/quant_system/api/schemas/news.py tests/test_news_*.py tests/test_api_news_*.py
```

- [ ] **Step 4: Manual drill (operator, optional in agent run)**

1. Apply migration 009.  
2. Copy tests fixture into `data/horizon_inbox` and run `quant-system news horizon-ingest --once`.  
3. `QS_AIHOT_ENABLED=false quant-system serve` (or env) → curl items auto → `provider=horizon`, `served_from=failover`.  
4. Re-enable aihot → primary.

- [ ] **Step 5: Final commit if doc/test fixups needed**

```bash
git add -A
git status
# commit only if there are fixups
```

---

## Spec Coverage Checklist

| Spec section | Task(s) |
|---|---|
| §1 bus factor / decisions | Tasks 1–11 (global) |
| §2 success criteria auto failover/cutback | 6, 8, 11 |
| §3 architecture modules | 3–6, 9 |
| §4 inbox contract | 3, 5, 9 |
| §5 PG runs + reuse ai_news_* | 4, 5 |
| §6 Facade/API/status/errors/config | 1, 2, 6 |
| §7 Brief | 8 |
| §8 Frontend | 7 |
| §9 Docker/ops | 9, 10 |
| §10 degradation matrix | 6 tests |
| §11 risks | constraints + tests |
| §12 test plan | 11 |
| §13 slices S0–S7 | Tasks 1–10 map S0→2, S1→6, S2→4, S3→3+5, S4→8, S5→7, S6→9, S7→10 |
| Phase B reserved only | no merge task (intentional) |

## Placeholder / consistency notes (self-review)

- No TBD steps; export script must emit Task 3 contract field names (`id/title/url/source/...`).
- Provider string is always `"aihot"` | `"horizon"`.
- `served_from` enum fixed: `primary|failover|cache|forced`.
- Migration file name **`009_ai_news_provider_runs.sql`** (after `008_l2a_conversation_turn_claim.sql`).
- CLI group name **`news`**, command **`horizon-ingest`**.
- Default inbox: repo `data/horizon_inbox`.
- `AiHot*` type names may remain for compatibility; facade still returns those shapes with extra stamps.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-23-ai-news-horizon-bridge.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — execute tasks in this session with executing-plans checkpoints  

Which approach?
