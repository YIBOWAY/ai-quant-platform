from __future__ import annotations

from pathlib import Path

from quant_system.options.iv_history import IvHistoryStore, compute_iv_rank


def test_iv_history_appends_jsonl_records(tmp_path: Path) -> None:
    store = IvHistoryStore(tmp_path)

    path = store.append("SPY", current_iv=0.24, run_date="2026-05-03")

    assert path == tmp_path / "SPY.jsonl"
    assert '"ticker":"SPY"' in path.read_text(encoding="utf-8")
    assert store.read_values("SPY") == [0.24]


def test_compute_iv_rank_returns_none_until_minimum_history(tmp_path: Path) -> None:
    store = IvHistoryStore(tmp_path)
    for index in range(29):
        store.append("SPY", current_iv=0.10 + index * 0.01, run_date=f"2026-01-{index + 1:02d}")

    assert compute_iv_rank("SPY", 0.20, history_dir=tmp_path) is None


def test_compute_iv_rank_boundaries_and_midpoint(tmp_path: Path) -> None:
    store = IvHistoryStore(tmp_path)
    for index in range(30):
        store.append("SPY", current_iv=0.10 + index * 0.01, run_date=f"2026-02-{index + 1:02d}")

    assert compute_iv_rank("SPY", 0.10, history_dir=tmp_path) == 0.0
    assert compute_iv_rank("SPY", 0.39, history_dir=tmp_path) == 100.0
    assert compute_iv_rank("SPY", 0.245, history_dir=tmp_path) == 50.0
