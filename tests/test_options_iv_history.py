from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from quant_system.options.iv_history import (
    IV_MEASURE_ATM30_STRADDLE_V1,
    IvHistoryStore,
    compute_iv_rank,
    load_atm30_straddle_iv,
    option_contract_identity_matches,
    parse_option_contract_identity,
    resolve_atm30_straddle_iv,
    resolve_trusted_underlying_quote,
)
from quant_system.options.seller_score import is_us_market_session


def _market_sessions(*, start: date, count: int) -> list[str]:
    sessions: list[str] = []
    active = start
    while len(sessions) < count:
        if is_us_market_session(active):
            sessions.append(active.isoformat())
        active += timedelta(days=1)
    return sessions


def _append_formal(
    store: IvHistoryStore,
    ticker: str,
    *,
    current_iv: float,
    quote_session: str,
    run_date: str | None = None,
):
    return store.append(
        ticker,
        current_iv=current_iv,
        run_date=run_date or quote_session,
        quote_as_of=f"{quote_session} 15:59:00",
        provider="futu",
        fetched_at=f"{quote_session}T23:59:59Z",
    )


def _atm30_quote_row(
    option_type: str,
    *,
    strike: float,
    update_time: str | None,
) -> dict[str, object]:
    option_code = "C" if option_type == "CALL" else "P"
    encoded_strike = f"{int(strike * 1000):06d}"
    return {
        "symbol": f"US.AAPL260619{option_code}{encoded_strike}",
        "underlying": "US.AAPL",
        "option_type": option_type,
        "expiry": "2026-06-19",
        "strike": strike,
        "bid": 4.8,
        "ask": 5.0,
        "implied_volatility": 0.25,
        "update_time": update_time,
    }


def test_iv_history_appends_jsonl_records(tmp_path: Path) -> None:
    store = IvHistoryStore(tmp_path)

    path = _append_formal(
        store,
        "SPY",
        current_iv=0.24,
        quote_session="2026-05-01",
        run_date="2026-05-03",
    )

    assert path == tmp_path / "SPY.atm30_straddle_iv_v1.sessions.jsonl"
    assert '"ticker":"SPY"' in path.read_text(encoding="utf-8")
    assert store.read_values("SPY") == [0.24]


def test_compute_iv_rank_returns_none_until_minimum_history(tmp_path: Path) -> None:
    store = IvHistoryStore(tmp_path)
    for index, quote_session in enumerate(_market_sessions(start=date(2026, 1, 2), count=29)):
        _append_formal(
            store,
            "SPY",
            current_iv=0.10 + index * 0.01,
            quote_session=quote_session,
        )

    assert (
        compute_iv_rank(
            "SPY",
            0.20,
            history_dir=tmp_path,
            as_of_session="2099-12-31",
        )
        is None
    )


def test_compute_iv_rank_boundaries_and_midpoint(tmp_path: Path) -> None:
    store = IvHistoryStore(tmp_path)
    for index, quote_session in enumerate(_market_sessions(start=date(2026, 2, 2), count=30)):
        _append_formal(
            store,
            "SPY",
            current_iv=0.10 + index * 0.01,
            quote_session=quote_session,
        )

    assert compute_iv_rank("SPY", 0.10, history_dir=tmp_path, as_of_session="2099-12-31") == 0.0
    assert compute_iv_rank("SPY", 0.39, history_dir=tmp_path, as_of_session="2099-12-31") == 100.0
    assert compute_iv_rank("SPY", 0.245, history_dir=tmp_path, as_of_session="2099-12-31") == 50.0


def test_compute_iv_rank_excludes_sessions_after_as_of(tmp_path: Path) -> None:
    store = IvHistoryStore(tmp_path)
    sessions = _market_sessions(start=date(2026, 2, 2), count=31)
    for index, quote_session in enumerate(sessions[:30]):
        _append_formal(
            store,
            "SPY",
            current_iv=0.10 + index * 0.01,
            quote_session=quote_session,
        )
    _append_formal(
        store,
        "SPY",
        current_iv=0.90,
        quote_session=sessions[30],
    )

    assert (
        compute_iv_rank(
            "SPY",
            0.39,
            history_dir=tmp_path,
            as_of_session=sessions[29],
        )
        == 100.0
    )


def test_atm30_v1_uses_nearest_30d_same_strike_call_put_mean() -> None:
    rows = []
    for expiry, strike, call_iv, put_iv in (
        ("2026-06-05", 100.0, 0.80, 0.70),
        ("2026-06-19", 100.0, 0.30, 0.20),
        ("2026-06-19", 101.0, 0.40, 0.35),
    ):
        rows.extend(
            [
                {
                    "option_type": "CALL",
                    "expiry": expiry,
                    "strike": strike,
                    "implied_volatility": call_iv,
                },
                {
                    "option_type": "PUT",
                    "expiry": expiry,
                    "strike": strike,
                    "implied_volatility": put_iv,
                },
            ]
        )

    observation = resolve_atm30_straddle_iv(
        pd.DataFrame(rows),
        spot_price=100.0,
        market_session=date(2026, 5, 20),
    )

    assert observation.measure == IV_MEASURE_ATM30_STRADDLE_V1
    assert observation.expiry == "2026-06-19"
    assert observation.strike == 100.0
    assert observation.current_iv == pytest.approx(0.25)


def test_trusted_underlying_uses_last_for_previous_options_session_overnight() -> None:
    quote = resolve_trusted_underlying_quote(
        {
            "symbol": "US.SPY",
            "last": 763.47,
            "prev_close": 765.72,
            "volume": 32_430_886,
            "update_time": "2026-08-25 00:20:19",
        },
        ticker="SPY",
        market_session=date(2026, 8, 24),
        observed_at="2026-08-25T04:21:00Z",
    )

    assert quote.spot_price == 763.47
    assert quote.quote_session == "2026-08-24"
    assert quote.quote_as_of == "2026-08-24T20:00:00Z"


def test_trusted_underlying_rejects_overnight_snapshot_without_valid_volume() -> None:
    with pytest.raises(ValueError, match="underlying_quote_future"):
        resolve_trusted_underlying_quote(
            {
                "symbol": "US.SPY",
                "last": 763.47,
                "prev_close": 765.72,
                "volume": 0,
                "update_time": "2026-08-25 00:20:19",
            },
            ticker="SPY",
            market_session=date(2026, 8, 24),
            observed_at="2026-08-25T04:21:00Z",
        )


@pytest.mark.parametrize(
    ("snapshot", "observed_at", "expected_error"),
    (
        (
            {
                "symbol": "US.SPY",
                "last": 763.47,
                "volume": 32_430_886,
                "update_time": "2026-08-25 10:00:00",
            },
            "2026-08-25T14:01:00Z",
            "underlying_quote_future",
        ),
        (
            {
                "symbol": "US.SPY",
                "last": 763.47,
                "volume": 32_430_886,
                "update_time": "2026-08-26 00:20:00",
            },
            "2026-08-26T04:21:00Z",
            "underlying_quote_future",
        ),
        (
            {
                "symbol": "US.SPY",
                "last": 763.47,
                "volume": 32_430_886,
                "update_time": "2026-08-25 00:20:00",
            },
            "2026-08-25T04:19:00Z",
            "underlying_quote_future",
        ),
        (
            {
                "symbol": "US.SPY",
                "last": float("nan"),
                "volume": 32_430_886,
                "update_time": "2026-08-25 00:20:00",
            },
            "2026-08-25T04:21:00Z",
            "underlying_price_missing",
        ),
    ),
)
def test_trusted_underlying_overnight_rebinding_fails_closed(
    snapshot: dict[str, object],
    observed_at: str,
    expected_error: str,
) -> None:
    with pytest.raises(ValueError, match=expected_error):
        resolve_trusted_underlying_quote(
            snapshot,
            ticker="SPY",
            market_session=date(2026, 8, 24),
            observed_at=observed_at,
        )


def test_atm30_loader_ignores_stale_quotes_outside_selected_pair() -> None:
    class MixedFreshnessProvider:
        def fetch_option_quotes_range(self, *_args, **_kwargs) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    _atm30_quote_row(
                        option_type,
                        strike=80.0,
                        update_time="2026-05-19 15:59:00",
                    )
                    for option_type in ("CALL", "PUT")
                ]
                + [
                    _atm30_quote_row(
                        option_type,
                        strike=100.0,
                        update_time="2026-05-20 15:59:00",
                    )
                    for option_type in ("CALL", "PUT")
                ]
            )

    observation = load_atm30_straddle_iv(
        MixedFreshnessProvider(),
        ticker="AAPL",
        spot_price=100.0,
        market_session=date(2026, 5, 20),
        observed_at="2026-05-20T20:00:00Z",
    )

    assert observation.strike == 100.0
    assert observation.quote_session == "2026-05-20"
    assert observation.quote_as_of == "2026-05-20T19:59:00Z"


@pytest.mark.parametrize(
    ("selected_quote_time", "expected_error"),
    (
        (None, "atm30_iv_quote_as_of_missing"),
        ("2026-05-19 15:59:00", "atm30_iv_quote_stale"),
        ("2026-05-21 15:59:00", "atm30_iv_quote_future"),
    ),
)
def test_atm30_loader_rejects_untrusted_selected_leg(
    selected_quote_time: str | None,
    expected_error: str,
) -> None:
    class SelectedLegProvider:
        def fetch_option_quotes_range(self, *_args, **_kwargs) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    _atm30_quote_row(
                        "CALL",
                        strike=100.0,
                        update_time=selected_quote_time,
                    ),
                    _atm30_quote_row(
                        "PUT",
                        strike=100.0,
                        update_time="2026-05-20 15:59:00",
                    ),
                ]
            )

    with pytest.raises(ValueError, match=expected_error):
        load_atm30_straddle_iv(
            SelectedLegProvider(),
            ticker="AAPL",
            spot_price=100.0,
            market_session=date(2026, 5, 20),
            observed_at="2026-05-20T20:00:00Z",
        )


def test_atm30_loader_rejects_contract_symbol_prefix_collision() -> None:
    class PrefixCollisionProvider:
        def fetch_option_quotes_range(self, ticker: str, **_kwargs) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "symbol": "US.AAPLX20260619C100000",
                        "underlying": "US.AAPL",
                        "option_type": "CALL",
                        "expiry": "2026-06-19",
                        "strike": 100.0,
                        "bid": 5.0,
                        "ask": 5.4,
                        "implied_volatility": 0.25,
                        "update_time": "2026-05-20 15:59:00",
                    },
                    {
                        "symbol": "US.AAPLX20260619P100000",
                        "underlying": "US.AAPL",
                        "option_type": "PUT",
                        "expiry": "2026-06-19",
                        "strike": 100.0,
                        "bid": 4.6,
                        "ask": 4.9,
                        "implied_volatility": 0.25,
                        "update_time": "2026-05-20 15:59:00",
                    },
                ]
            )

    with pytest.raises(ValueError, match="atm30_iv_symbol_mismatch"):
        load_atm30_straddle_iv(
            PrefixCollisionProvider(),
            ticker="AAPL",
            spot_price=100.0,
            market_session=date(2026, 5, 20),
            observed_at="2026-05-20T20:00:00Z",
        )


def test_option_contract_identity_requires_exact_strike() -> None:
    assert not option_contract_identity_matches(
        {
            "symbol": "US.SPY260918P00400000",
            "expiry": "2026-09-18",
            "option_type": "PUT",
            "strike": 400.0000000005,
        },
        ticker="SPY",
    )


def test_option_contract_identity_accepts_dot_stripped_share_class_code() -> None:
    # Futu prints BRK.B option codes with the dot stripped while the chain
    # underlying keeps it: symbol US.BRKB260918C480000 under US.BRK.B.
    squashed = parse_option_contract_identity("US.BRKB260918C480000", ticker="BRK.B")
    assert squashed is not None
    assert squashed.ticker == "BRK.B"
    assert squashed.expiry == "2026-09-18"
    assert squashed.option_type == "CALL"
    assert squashed.strike == 480.0
    dotted = parse_option_contract_identity("US.BRK.B260918C480000", ticker="BRK.B")
    assert dotted is not None and dotted == squashed
    assert option_contract_identity_matches(
        {
            "symbol": "US.BRKB260918C480000",
            "expiry": "2026-09-18",
            "option_type": "CALL",
            "strike": 480.0,
        },
        ticker="BRK.B",
    )
    # A different dotted ticker still fails closed.
    assert parse_option_contract_identity("US.BRKB260918C480000", ticker="BRK.A") is None


def test_atm30_loader_accepts_brk_share_class_option_codes() -> None:
    class BrkProvider:
        def fetch_option_quotes_range(self, ticker: str, **_kwargs) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "symbol": "US.BRKB260619C480000",
                        "underlying": "US.BRK.B",
                        "option_type": "CALL",
                        "expiry": "2026-06-19",
                        "strike": 480.0,
                        "bid": 5.0,
                        "ask": 5.4,
                        "implied_volatility": 0.25,
                        "update_time": "2026-05-20 15:59:00",
                    },
                    {
                        "symbol": "US.BRKB260619P480000",
                        "underlying": "US.BRK.B",
                        "option_type": "PUT",
                        "expiry": "2026-06-19",
                        "strike": 480.0,
                        "bid": 4.6,
                        "ask": 4.9,
                        "implied_volatility": 0.25,
                        "update_time": "2026-05-20 15:59:00",
                    },
                ]
            )

    observation = load_atm30_straddle_iv(
        BrkProvider(),
        ticker="BRK.B",
        spot_price=480.0,
        market_session=date(2026, 5, 20),
        observed_at="2026-05-20T20:00:00Z",
    )

    assert observation.current_iv == 0.25
    assert observation.strike == 480.0


def test_iv_history_keeps_one_value_per_ticker_and_quote_session(tmp_path: Path) -> None:
    store = IvHistoryStore(tmp_path)

    _append_formal(store, "SPY", current_iv=0.20, quote_session="2026-08-20")
    _append_formal(store, "SPY", current_iv=0.20, quote_session="2026-08-20")
    _append_formal(store, "SPY", current_iv=0.25, quote_session="2026-08-21")

    assert store.read_values("SPY") == [0.20, 0.25]
    assert (
        len(
            (tmp_path / "SPY.atm30_straddle_iv_v1.sessions.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        == 2
    )


def test_iv_rank_ignores_legacy_rows_without_provenance_without_rewrite(
    tmp_path: Path,
) -> None:
    rows = []
    for index in range(15):
        for duplicate in range(2):
            rows.append(
                json.dumps(
                    {
                        "ticker": "SPY",
                        "run_date": f"2026-08-{index + 1:02d}",
                        "current_iv": 0.20 + index * 0.01 + duplicate * 0.001,
                        "fetched_at": "2026-08-20T20:00:00Z",
                    }
                )
            )
    path = tmp_path / "SPY.jsonl"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    before = path.read_bytes()

    assert IvHistoryStore(tmp_path).read_values("SPY") == []
    assert compute_iv_rank("SPY", 0.30, history_dir=tmp_path, as_of_session="2099-12-31") is None
    assert path.read_bytes() == before


def test_iv_rank_excludes_unversioned_formal_history_without_rewrite(
    tmp_path: Path,
) -> None:
    rows = []
    for index, quote_session in enumerate(_market_sessions(start=date(2026, 1, 2), count=30)):
        rows.append(
            json.dumps(
                {
                    "ticker": "SPY",
                    "run_date": quote_session,
                    "quote_session": quote_session,
                    "quote_as_of": f"{quote_session} 15:59:00",
                    "provider": "futu",
                    "current_iv": 0.10 + index * 0.01,
                    "fetched_at": f"{quote_session}T23:59:59Z",
                }
            )
        )
    legacy_path = tmp_path / "SPY.sessions.jsonl"
    legacy_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    before = legacy_path.read_bytes()

    assert IvHistoryStore(tmp_path).read_values("SPY") == []
    assert compute_iv_rank("SPY", 0.20, history_dir=tmp_path, as_of_session="2099-12-31") is None
    assert legacy_path.read_bytes() == before


def test_formal_append_leaves_legacy_history_file_byte_identical(
    tmp_path: Path,
) -> None:
    legacy_path = tmp_path / "SPY.jsonl"
    legacy_path.write_text(
        json.dumps(
            {
                "ticker": "SPY",
                "run_date": "2026-08-20",
                "current_iv": 0.20,
                "fetched_at": "2026-08-20T20:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before = legacy_path.read_bytes()

    formal_path = _append_formal(
        IvHistoryStore(tmp_path),
        "SPY",
        current_iv=0.24,
        quote_session="2026-08-21",
    )

    assert legacy_path.read_bytes() == before
    assert formal_path == tmp_path / "SPY.atm30_straddle_iv_v1.sessions.jsonl"
    assert IvHistoryStore(tmp_path).read_values("SPY") == [0.24]


def test_iv_history_uses_quote_session_and_saturday_replay_is_zero_write(
    tmp_path: Path,
) -> None:
    store = IvHistoryStore(tmp_path)
    quote_as_of = "2026-08-21 15:59:00"

    path = store.append(
        "SPY",
        current_iv=0.24,
        run_date="2026-08-21",
        quote_as_of=quote_as_of,
        provider="futu",
        fetched_at="2026-08-21T23:59:59Z",
    )
    first_bytes = path.read_bytes()
    store.append(
        "SPY",
        current_iv=0.24,
        run_date="2026-08-22",
        quote_as_of=quote_as_of,
        provider="futu",
        fetched_at="2026-08-22T23:59:59Z",
    )

    assert path.read_bytes() == first_bytes
    assert store.read_values("SPY") == [0.24]
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["provider"] == "futu"
    assert payload["quote_session"] == "2026-08-21"


def test_conflicting_same_quote_instant_fails_closed_without_rewrite(
    tmp_path: Path,
) -> None:
    store = IvHistoryStore(tmp_path)
    path = store.append(
        "SPY",
        current_iv=0.20,
        run_date="2026-08-21",
        quote_as_of="2026-08-21 15:59:00",
        provider="futu",
        fetched_at="2026-08-21T23:00:00Z",
    )
    before = path.read_bytes()

    with pytest.raises(ValueError, match="iv_history_observation_conflict"):
        store.append(
            "SPY",
            current_iv=0.25,
            run_date="2026-08-22",
            quote_as_of="2026-08-21 15:59:00",
            provider="futu",
            fetched_at="2026-08-22T23:00:00Z",
        )

    assert path.read_bytes() == before


def test_later_quote_replaces_same_session_observation_without_adding_a_day(
    tmp_path: Path,
) -> None:
    store = IvHistoryStore(tmp_path)
    store.append(
        "SPY",
        current_iv=0.20,
        run_date="2026-08-21",
        quote_as_of="2026-08-21 11:00:00",
        provider="futu",
        fetched_at="2026-08-21T20:00:00Z",
    )

    path = store.append(
        "SPY",
        current_iv=0.25,
        run_date="2026-08-22",
        quote_as_of="2026-08-21 16:00:00",
        provider="futu",
        fetched_at="2026-08-22T20:00:00Z",
    )

    assert store.read_values("SPY") == [0.25]
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_repeated_quote_session_across_run_dates_never_builds_iv_rank(
    tmp_path: Path,
) -> None:
    rows = []
    for index in range(30):
        run_date = ("2026-08-21", "2026-08-22", "2026-08-23")[index % 3]
        rows.append(
            json.dumps(
                {
                    "ticker": "SPY",
                    "run_date": run_date,
                    "quote_session": "2026-08-21",
                    "quote_as_of": "2026-08-21 15:59:00",
                    "provider": "futu",
                    "measure": IV_MEASURE_ATM30_STRADDLE_V1,
                    "current_iv": 0.20 + index * 0.001,
                    "fetched_at": "2026-08-23T20:00:00Z",
                }
            )
        )
    (tmp_path / "SPY.atm30_straddle_iv_v1.sessions.jsonl").write_text(
        "\n".join(rows) + "\n",
        encoding="utf-8",
    )

    assert IvHistoryStore(tmp_path).read_values("SPY") == []
    assert compute_iv_rank("SPY", 0.30, history_dir=tmp_path, as_of_session="2099-12-31") is None


def test_iv_history_lookback_is_sorted_by_quote_session_not_file_order(
    tmp_path: Path,
) -> None:
    store = IvHistoryStore(tmp_path)
    for quote_session, current_iv in (
        ("2026-08-21", 0.21),
        ("2026-08-19", 0.19),
        ("2026-08-20", 0.20),
    ):
        _append_formal(
            store,
            "SPY",
            current_iv=current_iv,
            quote_session=quote_session,
        )

    assert store.read_values("SPY", lookback_days=2) == [0.20, 0.21]


def test_iv_history_boolean_value_cannot_complete_minimum_sample_count(
    tmp_path: Path,
) -> None:
    store = IvHistoryStore(tmp_path)
    for index, quote_session in enumerate(_market_sessions(start=date(2026, 1, 2), count=29)):
        _append_formal(
            store,
            "SPY",
            current_iv=0.10 + index * 0.01,
            quote_session=quote_session,
        )
    path = tmp_path / "SPY.atm30_straddle_iv_v1.sessions.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "ticker": "SPY",
                    "run_date": "2026-03-02",
                    "quote_session": "2026-03-02",
                    "quote_as_of": "2026-03-02 15:59:00",
                    "provider": "futu",
                    "measure": IV_MEASURE_ATM30_STRADDLE_V1,
                    "current_iv": True,
                    "fetched_at": "2026-03-02T23:59:59Z",
                }
            )
            + "\n"
        )

    assert len(store.read_values("SPY")) == 29
    assert compute_iv_rank("SPY", 0.30, history_dir=tmp_path, as_of_session="2099-12-31") is None


def test_iv_history_duplicate_json_key_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "SPY.atm30_straddle_iv_v1.sessions.jsonl"
    path.write_text(
        '{"ticker":"SPY","run_date":"2026-08-21",'
        '"quote_session":"2026-08-21",'
        '"quote_as_of":"2026-08-21 15:59:00",'
        '"provider":"sample","provider":"futu",'
        '"measure":"atm30_straddle_iv_v1",'
        '"current_iv":0.24,"fetched_at":"2026-08-21T23:59:59Z"}\n',
        encoding="utf-8",
    )

    assert IvHistoryStore(tmp_path).read_values("SPY") == []


def test_iv_history_append_rejects_boolean_iv_without_writing(tmp_path: Path) -> None:
    store = IvHistoryStore(tmp_path)

    with pytest.raises(ValueError, match="current_iv must be finite and positive"):
        store.append(
            "SPY",
            current_iv=True,  # type: ignore[arg-type]
            run_date="2026-08-21",
            quote_as_of="2026-08-21 15:59:00",
            provider="futu",
            fetched_at="2026-08-21T23:59:59Z",
        )

    assert list(tmp_path.iterdir()) == []
