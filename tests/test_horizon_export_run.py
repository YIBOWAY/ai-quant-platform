"""Host-side unit tests for deploy/horizon/export_run.py (no Docker, no network)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from quant_system.news.horizon_inbox import iter_ready_runs, load_run

ROOT = Path(__file__).resolve().parents[1]
EXPORT_SCRIPT = ROOT / "deploy" / "horizon" / "export_run.py"


def _load_export_module():
    spec = importlib.util.spec_from_file_location("horizon_export_run", EXPORT_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


export_run_mod = _load_export_module()


def _write_content_item(
    *,
    item_id: str = "hackernews:story:1",
    title: str = "Horizon upstream sample",
    url: str = "https://example.com/hz-upstream-1",
    source_type: str = "hackernews",
    ai_score: float = 8.5,
    ai_summary: str = "upstream summary",
    ai_tags: list[str] | None = None,
    content: str | None = None,
    published_at: str = "2026-07-23T11:00:00+00:00",
) -> dict:
    return {
        "id": item_id,
        "source_type": source_type,
        "title": title,
        "url": url,
        "content": content,
        "published_at": published_at,
        "ai_score": ai_score,
        "ai_summary": ai_summary,
        "ai_tags": ai_tags if ai_tags is not None else ["ai-tools"],
        "metadata": {},
    }


def _seed_mcp_run(horizon_data: Path, *, stage: str = "enriched") -> Path:
    run_dir = horizon_data / "mcp-runs" / "run-20260723T120000Z-deadbeef"
    run_dir.mkdir(parents=True)
    items = [
        _write_content_item(),
        _write_content_item(
            item_id="rss:simon:2",
            title="Second item",
            url="https://example.com/hz-2",
            source_type="rss",
            ai_score=7.0,
            ai_tags=["industry"],
        ),
    ]
    (run_dir / f"{stage}_items.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "summary-zh.md").write_text("# 中文摘要\n\n测试\n", encoding="utf-8")
    (run_dir / "summary-en.md").write_text("# English summary\n\nTest\n", encoding="utf-8")
    (run_dir / "meta.json").write_text(
        json.dumps({"run_id": run_dir.name, "created_at": "2026-07-23T12:00:00+00:00"}),
        encoding="utf-8",
    )
    return run_dir


def test_export_run_writes_ready_parseable_by_inbox(tmp_path: Path) -> None:
    horizon_data = tmp_path / "horizon-data"
    inbox = tmp_path / "inbox"
    _seed_mcp_run(horizon_data)

    fixed = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)
    run_dir = export_run_mod.export_run(
        horizon_data,
        inbox,
        now=fixed,
        run_id="20260723T120000Z-ab12",
    )

    assert run_dir.name == "20260723T120000Z-ab12"
    assert (run_dir / "READY").is_file()
    assert (run_dir / "meta.json").is_file()
    assert (run_dir / "items.json").is_file()
    assert (run_dir / "summary-zh.md").is_file()
    assert (run_dir / "summary-en.md").is_file()

    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["run_id"] == "20260723T120000Z-ab12"
    assert meta["item_count"] == 2
    assert meta["status"] == "ok"
    assert "generated_at" in meta

    items = json.loads((run_dir / "items.json").read_text(encoding="utf-8"))
    assert len(items) == 2
    assert items[0]["id"] == "hackernews:story:1"
    assert items[0]["title"] == "Horizon upstream sample"
    assert items[0]["title_en"] == "Horizon upstream sample"
    assert items[0]["url"] == "https://example.com/hz-upstream-1"
    assert items[0]["source"] == "hackernews"
    assert items[0]["summary"] == "upstream summary"
    assert items[0]["category"] == "ai-tools"
    assert items[0]["score"] == 8.5
    assert items[0]["published_at"]

    # Must be accepted by the Task-3 inbox parser.
    loaded = load_run(run_dir)
    assert loaded.run_id == "20260723T120000Z-ab12"
    assert len(loaded.items) == 2
    assert loaded.items[0].score == 8.5
    assert loaded.items[0].selected is True
    assert loaded.daily is not None
    assert any(s["label"] == "summary-zh" for s in loaded.daily.sections)

    runs = iter_ready_runs(inbox)
    assert len(runs) == 1
    assert runs[0].run_id == loaded.run_id


def test_prefers_enriched_over_scored(tmp_path: Path) -> None:
    horizon_data = tmp_path / "horizon-data"
    run_dir = horizon_data / "mcp-runs" / "run-mix"
    run_dir.mkdir(parents=True)
    scored = [_write_content_item(item_id="scored-only", title="Scored", url="https://e.com/s")]
    enriched = [
        _write_content_item(item_id="enriched-only", title="Enriched", url="https://e.com/e")
    ]
    (run_dir / "scored_items.json").write_text(json.dumps(scored), encoding="utf-8")
    (run_dir / "enriched_items.json").write_text(json.dumps(enriched), encoding="utf-8")

    payload = export_run_mod.build_inbox_payload(horizon_data)
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == "enriched-only"


def test_falls_back_to_daily_summaries_dir(tmp_path: Path) -> None:
    horizon_data = tmp_path / "horizon-data"
    summaries = horizon_data / "summaries"
    summaries.mkdir(parents=True)
    (summaries / "horizon-2026-07-23-zh.md").write_text("中文日报", encoding="utf-8")
    (summaries / "horizon-2026-07-23-en.md").write_text("English daily", encoding="utf-8")
    # No mcp-runs — empty items but summaries still export.
    inbox = tmp_path / "inbox"
    run_dir = export_run_mod.export_run(
        horizon_data, inbox, run_id="20260723T130000Z-empty"
    )
    assert (run_dir / "READY").is_file()
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["item_count"] == 0
    assert (run_dir / "summary-zh.md").read_text(encoding="utf-8") == "中文日报"
    loaded = load_run(run_dir)
    assert loaded.items == []
    assert loaded.daily is not None


def test_empty_items_still_emits_ready(tmp_path: Path) -> None:
    horizon_data = tmp_path / "horizon-data"
    horizon_data.mkdir()
    inbox = tmp_path / "inbox"
    run_dir = export_run_mod.export_run(horizon_data, inbox, run_id="20260723T140000Z-zero")
    assert (run_dir / "READY").is_file()
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["item_count"] == 0
    assert json.loads((run_dir / "items.json").read_text(encoding="utf-8")) == []


def test_map_content_item_uses_content_when_no_ai_summary() -> None:
    mapped = export_run_mod.map_content_item(
        _write_content_item(ai_summary=None, content="body text from scraper")
    )
    assert mapped is not None
    assert mapped["summary"] == "body text from scraper"
    assert mapped["category"] == "ai-tools"


def test_map_content_item_defaults_category_industry() -> None:
    mapped = export_run_mod.map_content_item(_write_content_item(ai_tags=[]))
    assert mapped is not None
    assert mapped["category"] == "industry"


def test_map_skips_items_without_title_or_url() -> None:
    assert export_run_mod.map_content_item({"title": "", "url": "https://x"}) is None
    assert export_run_mod.map_content_item({"title": "t", "url": ""}) is None


def test_no_ready_on_exception(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    # Missing horizon-data directory → FileNotFoundError, no READY.
    with pytest.raises(FileNotFoundError):
        export_run_mod.export_run(tmp_path / "missing", inbox, run_id="nope")
    assert list(inbox.glob("runs/*/READY")) == []


def test_cli_success_and_failure(tmp_path: Path) -> None:
    horizon_data = tmp_path / "horizon-data"
    inbox = tmp_path / "inbox"
    _seed_mcp_run(horizon_data)

    ok = subprocess.run(
        [
            sys.executable,
            str(EXPORT_SCRIPT),
            "--horizon-data",
            str(horizon_data),
            "--inbox",
            str(inbox),
            "--run-id",
            "20260723T150000Z-cli",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert ok.returncode == 0, ok.stderr
    assert (inbox / "runs" / "20260723T150000Z-cli" / "READY").is_file()

    bad = subprocess.run(
        [
            sys.executable,
            str(EXPORT_SCRIPT),
            "--horizon-data",
            str(tmp_path / "nope"),
            "--inbox",
            str(inbox),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert bad.returncode != 0
