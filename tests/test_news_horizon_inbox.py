from __future__ import annotations

from pathlib import Path

from quant_system.news.horizon_inbox import iter_ready_runs, load_run

FIXTURE = Path(__file__).parent / "fixtures" / "horizon_inbox"


def test_iter_ready_runs_parses_fixture():
    runs = iter_ready_runs(FIXTURE)
    assert len(runs) == 1
    run = runs[0]
    assert run.run_id == "20260723T120000Z-ab12"
    assert len(run.items) == 1
    assert run.items[0].id == "hz-1"
    assert run.items[0].url.startswith("https://")
    assert run.items[0].title == "Horizon sample"
    assert run.items[0].score == 8.5
    assert run.items[0].selected is True
    assert run.content_digest
    assert len(run.content_digest) == 64
    assert run.daily is not None
    assert run.daily.date == "2026-07-23"
    assert run.daily.sections
    assert run.daily.sections[0]["label"] == "summary-zh"
    assert run.meta["status"] == "ok"


def test_skips_runs_without_ready(tmp_path):
    run_dir = tmp_path / "runs" / "nope"
    run_dir.mkdir(parents=True)
    (run_dir / "meta.json").write_text("{}", encoding="utf-8")
    (run_dir / "items.json").write_text("[]", encoding="utf-8")
    assert iter_ready_runs(tmp_path) == []


def test_load_run_content_digest_is_stable():
    run_dir = FIXTURE / "runs" / "20260723T120000Z-ab12"
    a = load_run(run_dir)
    b = load_run(run_dir)
    assert a.content_digest == b.content_digest
    assert a.content_digest == (
        __import__("hashlib")
        .sha256(
            (run_dir / "meta.json").read_bytes()
            + b"\n"
            + (run_dir / "items.json").read_bytes()
        )
        .hexdigest()
    )


def test_rejects_item_with_empty_title_or_url(tmp_path):
    run_dir = tmp_path / "runs" / "bad-item"
    run_dir.mkdir(parents=True)
    (run_dir / "READY").write_text("", encoding="utf-8")
    (run_dir / "meta.json").write_text(
        '{"run_id": "bad-item", "generated_at": "2026-07-23T12:00:00+00:00"}',
        encoding="utf-8",
    )
    (run_dir / "items.json").write_text(
        '[{"id": "x", "title": "", "url": "https://example.com/x", "source": "HN"}]',
        encoding="utf-8",
    )
    import pytest

    with pytest.raises(ValueError, match="title"):
        load_run(run_dir)
