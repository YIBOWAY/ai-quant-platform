from __future__ import annotations

import pytest

from quant_system.universes.pit import PitUniverseStore, UniverseSnapshot


def _settings(tmp_path):
    from quant_system.config.settings import DataSettings, Settings

    return Settings(
        data=DataSettings(
            data_dir=tmp_path / "data",
            parquet_dir=tmp_path / "p",
            duckdb_path=tmp_path / "d.duckdb",
            reports_dir=tmp_path / "r",
        )
    )


def test_store_resolves_latest_snapshot_on_or_before_date(tmp_path) -> None:
    store = PitUniverseStore(tmp_path / "universes")
    store.append(
        UniverseSnapshot(
            universe_id="nasdaq100",
            as_of="2024-01-01",
            symbols=["AAPL", "MSFT"],
            note="2024 membership",
        )
    )
    store.append(
        UniverseSnapshot(
            universe_id="nasdaq100",
            as_of="2025-01-01",
            symbols=["AAPL", "MSFT", "NVDA"],
            note="2025 membership",
        )
    )

    assert store.universe_at("nasdaq100", "2024-06-30").symbols == ["AAPL", "MSFT"]
    resolved = store.universe_at("nasdaq100", "2025-06-30")
    assert resolved.symbols == ["AAPL", "MSFT", "NVDA"]
    assert resolved.as_of == "2025-01-01"
    assert store.universe_at("nasdaq100", "2023-12-31") is None


def test_snapshot_digest_is_order_insensitive(tmp_path) -> None:
    a = UniverseSnapshot(
        universe_id="u", as_of="2025-01-01", symbols=["SPY", "QQQ"]
    )
    b = UniverseSnapshot(
        universe_id="u", as_of="2025-01-01", symbols=["QQQ", "SPY"]
    )
    assert a.digest() == b.digest()


def test_seed_store_ships_core_snapshots() -> None:
    from quant_system.universes.pit import seed_store_path

    store = PitUniverseStore(seed_store_path())
    liquid20 = store.universe_at("liquid20", "2026-08-16")
    assert liquid20 is not None and len(liquid20.symbols) == 20
    ndx = store.universe_at("nasdaq100-core", "2026-08-16")
    assert ndx is not None and 90 <= len(ndx.symbols) <= 110
    assert "static" in (ndx.note or "")
    assert ndx.membership_mode == "static_snapshot"


def test_backtest_records_universe_snapshot_digest(tmp_path) -> None:
    from quant_system.backtest.pipeline import run_backtest

    result = run_backtest(
        symbols=["SPY", "QQQ"],
        start="2024-01-02",
        end="2024-02-02",
        provider="sample",
        lookback=3,
        top_n=1,
        output_dir=tmp_path / "runs",
        settings=_settings(tmp_path),
    )
    assert result.universe_snapshot_digest
    assert len(result.universe_snapshot_digest) == 64


def test_backtest_preserves_resolved_pit_snapshot_identity(
    tmp_path, monkeypatch
) -> None:
    from quant_system.backtest.pipeline import run_backtest
    from quant_system.research.trials import TrialsLedger
    from quant_system.universes import pit

    snapshot = UniverseSnapshot(
        universe_id="pit-test",
        as_of="2024-01-15",
        symbols=["SPY", "QQQ"],
        note="dated fixture membership",
    )
    store = PitUniverseStore(tmp_path / "pit")
    store.append(snapshot)
    monkeypatch.setattr(pit, "seed_store_path", lambda: store.root)
    result = run_backtest(
        symbols=[],
        universe_id="pit-test",
        start="2024-01-02",
        end="2024-02-02",
        provider="sample",
        lookback=3,
        top_n=1,
        output_dir=tmp_path / "runs",
        settings=_settings(tmp_path),
        run_id="backtest-pit-identity",
    )

    assert result.universe_snapshot == snapshot
    assert result.universe_snapshot.membership_mode == "dated_snapshot"
    assert result.universe_snapshot_digest == snapshot.digest()
    assert result.universe_snapshot_digest != snapshot.model_copy(
        update={"as_of": "2024-02-02"}
    ).digest()
    trial = TrialsLedger(tmp_path / "data" / "trials").list()[0]
    assert trial.metadata["universe_snapshot"] == snapshot.model_dump(mode="json")
    assert trial.metadata["universe_snapshot"]["membership_mode"] == "dated_snapshot"
    assert trial.metadata["universe_snapshot_digest"] == snapshot.digest()


def test_custom_symbols_are_identified_as_adhoc_when_they_override_a_universe(
    tmp_path,
) -> None:
    from quant_system.backtest.pipeline import run_backtest

    result = run_backtest(
        symbols=["SPY", "QQQ"],
        universe_id="liquid20",
        start="2024-01-02",
        end="2024-02-02",
        provider="sample",
        lookback=3,
        top_n=1,
        output_dir=tmp_path / "runs",
        settings=_settings(tmp_path),
    )

    assert result.universe_id == "liquid20"
    assert result.universe_snapshot.universe_id == "adhoc"
    assert result.universe_snapshot.symbols == ["SPY", "QQQ"]
    assert result.universe_snapshot.membership_mode == "adhoc"


def test_unknown_universe_fails_closed_before_writing_a_trial(tmp_path) -> None:
    from quant_system.backtest.pipeline import run_backtest

    with pytest.raises(KeyError, match="unknown universe id"):
        run_backtest(
            symbols=[],
            universe_id="no-such-universe",
            start="2024-01-02",
            end="2024-02-02",
            provider="sample",
            lookback=3,
            top_n=1,
            output_dir=tmp_path / "runs",
            settings=_settings(tmp_path),
        )

    assert not (tmp_path / "data" / "trials" / "trials.jsonl").exists()


def test_resolve_symbols_prefers_dated_pit_seed_over_static_registry() -> None:
    from quant_system.backtest.pipeline import _resolve_universe
    from quant_system.universes.pit import PitUniverseStore, seed_store_path

    seed_symbols = sorted(
        PitUniverseStore(seed_store_path()).universe_at("liquid20", "2026-08-14").symbols
    )
    snapshot = _resolve_universe(
        symbols=[], universe_id="liquid20", as_of="2026-08-14"
    )
    assert snapshot.symbols == [symbol.upper() for symbol in seed_symbols]
    assert snapshot.membership_mode == "static_snapshot"
    # Legacy static ids keep resolving exactly as before.
    legacy = _resolve_universe(
        symbols=[], universe_id="etf", as_of="2026-08-14"
    )
    assert "SPY" in legacy.symbols and "IWM" in legacy.symbols
    assert legacy.membership_mode == "static_snapshot"
