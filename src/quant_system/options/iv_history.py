from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd

from quant_system.options.iv_units import (
    IV_UNIT_RATIO,
    declare_unit,
    frame_unit,
    to_ratio,
)
from quant_system.options.seller_score import (
    latest_us_market_session,
    recommendation_quote_session,
    resolve_recommendation_quote,
)

_NEW_YORK = ZoneInfo("America/New_York")
_OPTIONS_MARKET_OPEN = time(9, 30)
_OPTIONS_REGULAR_CLOSE = time(16)
IV_MEASURE_ATM30_STRADDLE_V1 = "atm30_straddle_iv_v1"


@dataclass(frozen=True)
class Atm30StraddleIvObservation:
    measure: str
    current_iv: float
    expiry: str
    strike: float
    days_to_expiry: int
    quote_as_of: str | None = None
    quote_session: str | None = None


@dataclass(frozen=True)
class OptionContractIdentity:
    ticker: str
    expiry: str
    option_type: str
    strike: float


@dataclass(frozen=True)
class TrustedUnderlyingQuote:
    ticker: str
    spot_price: float
    quote_as_of: str
    quote_session: str


def resolve_options_market_session(*, now: datetime | None = None) -> date:
    local_now = now or datetime.now(_NEW_YORK)
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=_NEW_YORK)
    else:
        local_now = local_now.astimezone(_NEW_YORK)
    active_date = local_now.date()
    market_session = latest_us_market_session(active_date)
    if market_session == active_date and local_now.time() < _OPTIONS_MARKET_OPEN:
        market_session = latest_us_market_session(active_date - timedelta(days=1))
    return market_session


def parse_option_contract_identity(
    symbol: object,
    *,
    ticker: str,
) -> OptionContractIdentity | None:
    normalized_ticker = ticker.upper().strip().removeprefix("US.")
    normalized_symbol = str(symbol or "").upper().strip()
    # Futu option codes for dotted share-class tickers strip the dot
    # (US.BRKB260918C260000) while the chain underlying stays US.BRK.B;
    # accept both encodings for the same canonical ticker.
    squashed_ticker = normalized_ticker.replace(".", "")
    ticker_pattern = re.escape(normalized_ticker)
    if squashed_ticker and squashed_ticker != normalized_ticker:
        ticker_pattern = f"(?:{ticker_pattern}|{re.escape(squashed_ticker)})"
    match = re.fullmatch(
        rf"US\.{ticker_pattern}"
        r"(?P<expiry>\d{8}|\d{6})(?P<option_type>[CP])(?P<strike>\d+)",
        normalized_symbol,
    )
    if match is None:
        return None
    raw_expiry = match.group("expiry")
    try:
        expiry = datetime.strptime(
            raw_expiry,
            "%Y%m%d" if len(raw_expiry) == 8 else "%y%m%d",
        ).date()
    except ValueError:
        return None
    return OptionContractIdentity(
        ticker=normalized_ticker,
        expiry=expiry.isoformat(),
        option_type="CALL" if match.group("option_type") == "C" else "PUT",
        strike=int(match.group("strike")) / 1000.0,
    )


def option_contract_identity_matches(
    row: dict[str, object],
    *,
    ticker: str,
) -> bool:
    identity = parse_option_contract_identity(row.get("symbol"), ticker=ticker)
    if identity is None:
        return False
    try:
        strike = float(row.get("strike"))
    except (TypeError, ValueError):
        return False
    option_type = str(row.get("option_type") or "").upper().strip()
    return (
        math.isfinite(strike)
        and identity.expiry == str(row.get("expiry") or "")
        and identity.option_type == option_type
        and identity.strike == strike
    )


def resolve_trusted_underlying_quote(
    snapshot: dict[str, object],
    *,
    ticker: str,
    market_session: date,
    observed_at: str,
) -> TrustedUnderlyingQuote:
    normalized_ticker = ticker.upper().strip().removeprefix("US.")
    observed_symbol = str(snapshot.get("symbol") or snapshot.get("code") or "").upper().strip()
    if observed_symbol.removeprefix("US.") != normalized_ticker:
        raise ValueError("underlying_symbol_mismatch")
    spot_price = None
    for key in ("last", "last_price", "close", "price"):
        parsed = _finite_positive(snapshot.get(key))
        if parsed is not None:
            spot_price = parsed
            break
    if spot_price is None:
        raise ValueError("underlying_price_missing")
    resolution = resolve_recommendation_quote(
        run_date=market_session.isoformat(),
        quote_as_of=str(snapshot.get("update_time") or "").strip(),
        observed_at=observed_at,
    )
    if resolution.reason is not None or resolution.canonical_as_of is None:
        # Futu can stamp the prior regular-session close with the next day's
        # overnight date. Rebind that explicit last/volume pair only while the
        # listed-options session is still the immediately preceding session.
        overnight_last = _finite_positive(snapshot.get("last"))
        if overnight_last is None:
            overnight_last = _finite_positive(snapshot.get("last_price"))
        overnight_volume = _finite_positive(snapshot.get("volume"))
        quote_session = resolution.quote_session
        try:
            observed_instant = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        except ValueError:
            observed_instant = None
        if observed_instant is not None and observed_instant.tzinfo is None:
            observed_instant = observed_instant.replace(tzinfo=UTC)
        observed_utc = observed_instant.astimezone(UTC) if observed_instant is not None else None
        if (
            resolution.reason != "quote_future"
            or overnight_last is None
            or overnight_volume is None
            or quote_session is None
            or latest_us_market_session(quote_session - timedelta(days=1)) != market_session
            or resolution.quote_at_utc is None
            or observed_utc is None
            or resolution.quote_at_utc > observed_utc
            or resolve_options_market_session(now=observed_instant) != market_session
        ):
            raise ValueError("underlying_" + (resolution.reason or "quote_session_invalid"))
        regular_close = datetime.combine(
            market_session,
            _OPTIONS_REGULAR_CLOSE,
            tzinfo=_NEW_YORK,
        )
        return TrustedUnderlyingQuote(
            ticker=normalized_ticker,
            spot_price=overnight_last,
            quote_as_of=regular_close.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            quote_session=market_session.isoformat(),
        )
    return TrustedUnderlyingQuote(
        ticker=normalized_ticker,
        spot_price=spot_price,
        quote_as_of=resolution.canonical_as_of,
        quote_session=resolution.expected_session.isoformat(),
    )


def resolve_atm30_straddle_iv(
    option_rows: pd.DataFrame,
    *,
    spot_price: float,
    market_session: date,
) -> Atm30StraddleIvObservation:
    required = {"option_type", "expiry", "strike", "implied_volatility"}
    missing = sorted(required.difference(option_rows.columns))
    if missing:
        raise ValueError("atm30_iv_missing_columns: " + ", ".join(missing))
    frame = option_rows.loc[:, sorted(required)].copy()
    frame["option_type"] = frame["option_type"].astype(str).str.upper()
    frame["strike"] = pd.to_numeric(frame["strike"], errors="coerce")
    frame_unit_name = frame_unit(option_rows)
    frame["implied_volatility"] = pd.to_numeric(frame["implied_volatility"], errors="coerce").map(
        lambda value: _normalize_iv(value, unit=frame_unit_name)
    )
    frame = frame.dropna(subset=["expiry", "strike", "implied_volatility"])
    calls = frame.loc[frame["option_type"] == "CALL"]
    puts = frame.loc[frame["option_type"] == "PUT"]
    pairs = calls.merge(puts, on=["expiry", "strike"], suffixes=("_call", "_put"))
    if pairs.empty:
        raise ValueError("atm30_iv_same_strike_pair_missing")
    pairs["days_to_expiry"] = pd.to_datetime(pairs["expiry"]).dt.date.map(
        lambda expiry: (expiry - market_session).days
    )
    pairs = pairs.loc[pairs["days_to_expiry"] >= 0].copy()
    if pairs.empty:
        raise ValueError("atm30_iv_nonexpired_pair_missing")
    pairs["tenor_distance"] = (pairs["days_to_expiry"] - 30).abs()
    pairs["strike_distance"] = (pairs["strike"] - spot_price).abs()
    row = pairs.sort_values(["tenor_distance", "strike_distance", "expiry", "strike"]).iloc[0]
    return Atm30StraddleIvObservation(
        measure=IV_MEASURE_ATM30_STRADDLE_V1,
        current_iv=float((row["implied_volatility_call"] + row["implied_volatility_put"]) / 2),
        expiry=str(row["expiry"]),
        strike=float(row["strike"]),
        days_to_expiry=int(row["days_to_expiry"]),
        quote_session=market_session.isoformat(),
    )


def load_atm30_straddle_iv(
    provider,
    *,
    ticker: str,
    spot_price: float,
    market_session: date,
    observed_at: str | None = None,
) -> Atm30StraddleIvObservation:
    frame = provider.fetch_option_quotes_range(
        ticker,
        start_expiration=(pd.Timestamp(market_session) + pd.Timedelta(days=20)).date().isoformat(),
        end_expiration=(pd.Timestamp(market_session) + pd.Timedelta(days=45)).date().isoformat(),
        option_type="ALL",
    )
    received_at = observed_at or _utc_now()
    required = {
        "symbol",
        "underlying",
        "option_type",
        "expiry",
        "strike",
        "bid",
        "ask",
        "implied_volatility",
        "update_time",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError("atm30_iv_missing_columns: " + ", ".join(missing))
    normalized_ticker = ticker.upper().strip().removeprefix("US.")
    for row in frame.to_dict(orient="records"):
        underlying = str(row.get("underlying") or "").upper().strip()
        if underlying.removeprefix(
            "US."
        ) != normalized_ticker or not option_contract_identity_matches(
            row, ticker=normalized_ticker
        ):
            raise ValueError("atm30_iv_symbol_mismatch")
    normalized = frame.copy()
    normalized["strike"] = pd.to_numeric(normalized["strike"], errors="coerce")
    normalized["bid"] = pd.to_numeric(normalized["bid"], errors="coerce")
    normalized["ask"] = pd.to_numeric(normalized["ask"], errors="coerce")
    normalized["implied_volatility"] = pd.to_numeric(
        normalized["implied_volatility"], errors="coerce"
    ).map(lambda value: _normalize_iv(value, unit=frame_unit(frame)))
    normalized = normalized.loc[
        normalized["strike"].notna()
        & (normalized["strike"] > 0)
        & normalized["bid"].notna()
        & (normalized["bid"] > 0)
        & normalized["ask"].notna()
        & (normalized["ask"] >= normalized["bid"])
        & normalized["implied_volatility"].notna()
        & (normalized["implied_volatility"] > 0)
    ].copy()
    if normalized.empty:
        raise ValueError("atm30_iv_quote_invalid")
    normalized = declare_unit(normalized, IV_UNIT_RATIO)
    observation = resolve_atm30_straddle_iv(
        normalized,
        spot_price=spot_price,
        market_session=market_session,
    )
    selected = normalized.loc[
        (normalized["expiry"].astype(str) == observation.expiry)
        & (pd.to_numeric(normalized["strike"], errors="coerce") == observation.strike)
        & normalized["option_type"].astype(str).str.upper().isin({"CALL", "PUT"})
    ]
    if len(selected) != 2:
        raise ValueError("atm30_iv_selected_pair_invalid")
    canonical_times: list[str] = []
    for row in selected.to_dict(orient="records"):
        resolution = resolve_recommendation_quote(
            run_date=market_session.isoformat(),
            quote_as_of=str(row.get("update_time") or ""),
            observed_at=received_at,
        )
        if resolution.reason is not None or resolution.canonical_as_of is None:
            raise ValueError("atm30_iv_" + (resolution.reason or "quote_session_invalid"))
        canonical_times.append(resolution.canonical_as_of)
    quote_as_of = max(canonical_times, key=_quote_instant)
    return replace(observation, quote_as_of=quote_as_of)


def _finite_positive(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed <= 0:
        return None
    return parsed


def _normalize_iv(value: object, *, unit: str | None = None) -> float | None:
    # Provider frames declare their unit; an undeclared value is the canonical
    # decimal ratio. A magnitude heuristic cannot tell 45% IV from 45 percent.
    return to_ratio(value, unit=unit) if unit is not None else to_ratio(value)


class IvHistoryStore:
    def __init__(self, history_dir: str | Path) -> None:
        self.history_dir = Path(history_dir)

    def append(
        self,
        ticker: str,
        *,
        current_iv: float,
        run_date: str,
        quote_as_of: str,
        provider: str,
        fetched_at: str | None = None,
        measure: str = IV_MEASURE_ATM30_STRADDLE_V1,
    ) -> Path:
        if isinstance(current_iv, bool) or not math.isfinite(current_iv) or current_iv <= 0:
            raise ValueError("current_iv must be finite and positive")
        if provider != "futu":
            raise ValueError("iv_history_provider_must_be_futu")
        if measure != IV_MEASURE_ATM30_STRADDLE_V1:
            raise ValueError("iv_history_measure_invalid")
        active_fetched_at = fetched_at or _utc_now()
        quote_reason, quote_session = recommendation_quote_session(
            run_date=run_date,
            quote_as_of=quote_as_of,
            observed_at=active_fetched_at,
        )
        if quote_reason is not None or quote_session is None:
            raise ValueError(quote_reason or "quote_session_invalid")
        normalized = ticker.upper().strip()
        path = self._formal_path(normalized, measure=measure)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ticker": normalized,
            "run_date": run_date,
            "quote_session": quote_session.isoformat(),
            "quote_as_of": quote_as_of,
            "provider": provider,
            "measure": measure,
            "current_iv": current_iv,
            "iv_unit": IV_UNIT_RATIO,
            "fetched_at": active_fetched_at,
        }
        existing_text = ""
        replacement_index: int | None = None
        existing_lines: list[str] = []
        if path.exists():
            existing_text = path.read_text(encoding="utf-8")
            existing_lines = existing_text.splitlines()
            for index, line in enumerate(existing_lines):
                if not line.strip():
                    continue
                try:
                    item = _strict_json_document(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                observation = _formal_observation(
                    item,
                    expected_ticker=normalized,
                    expected_measure=measure,
                )
                if observation is not None and observation[0] == quote_session.isoformat():
                    incoming_instant = _quote_instant(quote_as_of)
                    if observation[2] > incoming_instant:
                        return path
                    if observation[2] == incoming_instant:
                        if not math.isclose(
                            observation[1],
                            current_iv,
                            rel_tol=1e-12,
                            abs_tol=1e-12,
                        ):
                            raise ValueError("iv_history_observation_conflict")
                        return path
                    replacement_index = index
                    break
        serialized = json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        )
        if replacement_index is not None:
            existing_lines[replacement_index] = serialized
            body = "\n".join(existing_lines) + "\n"
        else:
            prefix = existing_text
            if prefix and not prefix.endswith("\n"):
                prefix += "\n"
            body = prefix + serialized + "\n"
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(body, encoding="utf-8")
        temporary.replace(path)
        return path

    def read_values(
        self,
        ticker: str,
        *,
        lookback_days: int | None = None,
        measure: str = IV_MEASURE_ATM30_STRADDLE_V1,
        as_of_session: date | str | None = None,
    ) -> list[float]:
        normalized = ticker.upper().strip()
        if measure != IV_MEASURE_ATM30_STRADDLE_V1:
            return []
        path = self._formal_path(normalized, measure=measure)
        if not path.exists():
            return []
        observations_by_session: dict[str, tuple[float, datetime]] = {}
        conflicted_sessions: set[str] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = _strict_json_document(line)
            except (json.JSONDecodeError, ValueError):
                continue
            observation = _formal_observation(
                payload,
                expected_ticker=normalized,
                expected_measure=measure,
            )
            if observation is not None:
                session, value, quote_time = observation
                if session in conflicted_sessions:
                    continue
                existing = observations_by_session.get(session)
                if existing is None or quote_time > existing[1]:
                    observations_by_session[session] = (value, quote_time)
                elif quote_time == existing[1] and not math.isclose(
                    value,
                    existing[0],
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                ):
                    observations_by_session.pop(session, None)
                    conflicted_sessions.add(session)
        cutoff = (
            as_of_session
            if isinstance(as_of_session, date)
            else date.fromisoformat(as_of_session)
            if as_of_session is not None
            else None
        )
        values = [
            observations_by_session[session][0]
            for session in sorted(observations_by_session)
            if cutoff is None or date.fromisoformat(session) <= cutoff
        ]
        if lookback_days is not None:
            return values[-lookback_days:]
        return values

    def _formal_path(self, normalized_ticker: str, *, measure: str) -> Path:
        return self.history_dir / f"{normalized_ticker}.{measure}.sessions.jsonl"


def compute_iv_rank(
    ticker: str,
    current_iv: float | None,
    *,
    lookback_days: int = 252,
    history_dir: str | Path = Path("data/options_scans/iv_history"),
    min_samples: int = 30,
    measure: str = IV_MEASURE_ATM30_STRADDLE_V1,
    as_of_session: date | str,
) -> float | None:
    if current_iv is None:
        return None
    history = IvHistoryStore(history_dir).read_values(
        ticker,
        lookback_days=lookback_days,
        measure=measure,
        as_of_session=as_of_session,
    )
    if len(history) < min_samples:
        return None
    low = min(history)
    high = max(history)
    if high <= low:
        return 50.0
    rank = ((current_iv - low) / (high - low)) * 100
    return round(min(max(rank, 0.0), 100.0), 2)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _formal_observation(
    payload: object,
    *,
    expected_ticker: str,
    expected_measure: str,
) -> tuple[str, float, datetime] | None:
    if not isinstance(payload, dict) or payload.get("provider") != "futu":
        return None
    if str(payload.get("ticker", "")).upper().strip() != expected_ticker:
        return None
    if payload.get("measure") != expected_measure:
        return None
    run_date = payload.get("run_date")
    quote_as_of = payload.get("quote_as_of")
    quote_session = payload.get("quote_session")
    fetched_at = payload.get("fetched_at")
    value = payload.get("current_iv")
    if not all(
        isinstance(item, str) and item.strip()
        for item in (run_date, quote_as_of, quote_session, fetched_at)
    ):
        return None
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        return None
    try:
        reason, derived_session = recommendation_quote_session(
            run_date=run_date,
            quote_as_of=quote_as_of,
            observed_at=fetched_at,
        )
    except ValueError:
        return None
    if (
        reason is not None
        or derived_session is None
        or derived_session.isoformat() != quote_session
    ):
        return None
    return quote_session, float(value), _quote_instant(quote_as_of)


def _quote_instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    localized = parsed.replace(tzinfo=_NEW_YORK) if parsed.tzinfo is None else parsed
    return localized.astimezone(UTC)


def _strict_json_document(raw: str) -> object:
    return json.loads(raw, object_pairs_hook=_unique_object)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key: {key}")
        payload[key] = value
    return payload
