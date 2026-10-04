from __future__ import annotations

import json
import math
from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from quant_system.options.iv_history import (
    IV_MEASURE_ATM30_STRADDLE_V1,
    option_contract_identity_matches,
)
from quant_system.options.models import OptionsScreenerCandidate
from quant_system.options.radar import (
    CURATED_RECOMMENDATION_TICKERS,
    OptionsRadarCandidate,
    OptionsRadarReport,
    compute_global_score,
)
from quant_system.options.seller_score import (
    DEFAULT_EQUITY_RISK_PREMIUM,
    evaluate_seller_recommendation,
    historical_volatility_from_ratio,
    resolve_recommendation_quote,
    score_seller_contract,
)

RECOMMENDATION_CONTRACT_VERSION = "options_recommendations/v3"
RECOMMENDATION_LIMIT = 20


def _snapshot_eligible_candidates(report: OptionsRadarReport) -> list[OptionsRadarCandidate]:
    """Candidates that qualify for persistence in a recommendation snapshot."""
    if not (
        report.status == "available"
        and report.provider == "futu"
        and report.scanned_tickers > 0
    ):
        return []
    return [candidate for candidate in report.candidates if candidate.hard_gate_passed]


def persisted_recommendation_count(report: OptionsRadarReport) -> int:
    """Number of recommendation rows the snapshot writer would persist.

    This is the single source of truth for "how many candidates the user can
    see" so the task status, the API listing and the snapshot meta agree.
    """
    return min(len(_snapshot_eligible_candidates(report)), RECOMMENDATION_LIMIT)
CURATED_UNIVERSE_DIGEST = sha256(
    ("\n".join(CURATED_RECOMMENDATION_TICKERS) + "\n").encode("utf-8")
).hexdigest()
_SNAPSHOT_CANDIDATE_FIELDS = frozenset(
    {
        "breakeven",
        "candidate",
        "dividend_per_share",
        "earnings_in_window",
        "ex_dividend_date",
        "ex_dividend_in_window",
        "excess_annualized_ev",
        "expected_value",
        "extrinsic_value",
        "global_score",
        "gross_annualized_yield",
        "hard_gate_passed",
        "iv_rank",
        "iv_measure",
        "iv_history_samples",
        "iv_rank_status",
        "liquidity_factor",
        "manage_at_21_dte",
        "market_regime",
        "market_regime_penalty",
        "otm_pct",
        "pop",
        "quote_as_of",
        "recommendation_score",
        "recommendation_score_model",
        "run_date",
        "sector",
        "strategy",
        "take_profit_50_price",
        "ticker",
    }
)
_OPTION_CONTRACT_FIELDS = frozenset(
    {
        "annualized_yield",
        "ask",
        "avg_daily_volume",
        "bid",
        "days_to_expiry",
        "delta",
        "distance_pct",
        "earnings_date",
        "expiry",
        "gamma",
        "historical_volatility",
        "hv_iv_pass",
        "hv_iv_ratio",
        "implied_volatility",
        "iv_rank",
        "market_cap",
        "market_regime",
        "market_regime_penalty",
        "mid",
        "moneyness",
        "notes",
        "open_interest",
        "option_type",
        "premium_per_contract",
        "quote_as_of",
        "rating",
        "seller_score",
        "spread_pct",
        "strategy_type",
        "strike",
        "symbol",
        "theta",
        "trend_pass",
        "underlying",
        "underlying_price",
        "vega",
        "volume",
    }
)
_SELLER_SCORE_FIELDS = frozenset(
    {
        "yield_score",
        "liquidity_score",
        "delta_safety_score",
        "iv_edge_score",
        "iv_rank_score",
        "composite",
        "weights_used",
    }
)


class RadarSnapshotStore:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)

    def write(self, report: OptionsRadarReport) -> tuple[Path, Path]:
        if (
            report.expected_universe_size <= 0
            or report.universe_size != report.expected_universe_size
        ):
            raise ValueError("expected_universe_size_required")
        if not _coverage_contract_valid(
            scanned_tickers=report.scanned_tickers,
            universe_size=report.universe_size,
            expected_universe_size=report.expected_universe_size,
            failed_tickers=report.failed_tickers,
        ):
            raise ValueError("snapshot_universe_coverage_invalid")
        self.root_dir.mkdir(parents=True, exist_ok=True)
        meta_path = self.root_dir / f"{report.run_date}_meta.json"
        eligible = sorted(
            _snapshot_eligible_candidates(report),
            key=lambda candidate: (
                -(
                    candidate.recommendation_score
                    if candidate.recommendation_score is not None
                    else float("-inf")
                )
            ),
        )
        serialized_eligible = [
            _candidate_to_json(report.run_date, candidate) for candidate in eligible
        ]
        identities = [_candidate_key(payload) for payload in serialized_eligible]
        if len(identities) != len(set(identities)):
            raise ValueError("snapshot candidate identity duplicated")
        serialized_candidates = serialized_eligible[:RECOMMENDATION_LIMIT]
        persisted_identities = identities[:RECOMMENDATION_LIMIT]
        payloads = {
            identity: payload
            for identity, payload in zip(
                persisted_identities,
                serialized_candidates,
                strict=True,
            )
        }
        rows = sorted(
            payloads.values(),
            key=lambda item: -float(item["recommendation_score"]),
        )
        data = "".join(json.dumps(payload, sort_keys=True) + "\n" for payload in rows).encode(
            "utf-8"
        )
        persisted_shortfall_count = max(RECOMMENDATION_LIMIT - len(rows), 0)
        persisted_shortfall_reasons = dict(report.shortfall_reasons)
        if persisted_shortfall_count:
            persisted_shortfall_reasons["eligible_contracts_below_limit"] = (
                persisted_shortfall_count
            )
        else:
            persisted_shortfall_reasons.pop("eligible_contracts_below_limit", None)
        try:
            as_of = resolve_recommendation_quote(
                run_date=report.run_date,
                quote_as_of=report.as_of,
                observed_at=report.finished_at,
            ).canonical_as_of
        except ValueError:
            as_of = None
        self._reject_as_of_regression(report.run_date, as_of)
        generation = uuid4().hex
        data_file = f"{report.run_date}.{generation}.jsonl"
        data_path = self.root_dir / data_file
        meta = json.dumps(
            {
                "contract_version": RECOMMENDATION_CONTRACT_VERSION,
                "snapshot_generation": generation,
                "data_file": data_file,
                "data_sha256": sha256(data).hexdigest(),
                "data_line_count": len(rows),
                "run_date": report.run_date,
                "started_at": report.started_at,
                "finished_at": report.finished_at,
                "universe_size": report.universe_size,
                "expected_universe_size": report.expected_universe_size,
                "universe_digest": (
                    CURATED_UNIVERSE_DIGEST
                    if report.expected_universe_size == len(CURATED_RECOMMENDATION_TICKERS)
                    else None
                ),
                "scanned_tickers": report.scanned_tickers,
                "failed_tickers": report.failed_tickers,
                "provider": report.provider,
                "as_of": as_of,
                "status": report.status,
                "risk_free_rate": report.risk_free_rate,
                "equity_risk_premium": report.equity_risk_premium,
                "shortfall_count": persisted_shortfall_count,
                "shortfall_reasons": persisted_shortfall_reasons,
                "candidate_count": len(rows),
                "iv_unit": "ratio",
            },
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        data_temporary = data_path.with_name(f".{data_path.name}.{generation}.tmp")
        meta_temporary = meta_path.with_name(f".{meta_path.name}.{generation}.tmp")
        try:
            data_temporary.write_bytes(data)
            meta_temporary.write_bytes(meta)
            data_temporary.replace(data_path)
            meta_temporary.replace(meta_path)
        finally:
            data_temporary.unlink(missing_ok=True)
            meta_temporary.unlink(missing_ok=True)
        return data_path, meta_path

    def _reject_as_of_regression(self, run_date: str, new_as_of: str | None) -> None:
        try:
            existing = self.read(run_date)
        except FileNotFoundError:
            return
        if existing.status not in {"available", "empty"} or existing.as_of is None:
            return
        existing_instant = _parse_timestamp(existing.as_of)
        new_instant = _parse_timestamp(new_as_of)
        if existing_instant is not None and (
            new_instant is None or new_instant < existing_instant
        ):
            raise ValueError("snapshot_as_of_regression")

    def read(self, run_date: str) -> OptionsRadarReport:
        meta_path = self.root_dir / f"{run_date}_meta.json"
        if not meta_path.exists():
            if any(self.root_dir.glob(f"{run_date}.*.jsonl")):
                return _unavailable_report(
                    run_date,
                    {},
                    reason="invalid_recommendation_snapshot",
                )
            raise FileNotFoundError(f"no radar snapshot for {run_date}")
        try:
            meta_before = meta_path.read_bytes()
            meta = _strict_json_document(meta_before)
        except (OSError, UnicodeDecodeError, TypeError, ValueError):
            return _unavailable_report(
                run_date,
                {},
                reason="invalid_recommendation_snapshot",
            )
        if not isinstance(meta, dict):
            return _unavailable_report(
                run_date,
                {},
                reason="invalid_recommendation_snapshot",
            )
        if meta.get("contract_version") != RECOMMENDATION_CONTRACT_VERSION:
            return _unavailable_report(
                run_date,
                meta,
                reason="legacy_snapshot_contract",
            )
        if not _meta_contract_valid(meta, expected_run_date=run_date):
            return _unavailable_report(
                run_date,
                meta,
                reason="invalid_recommendation_snapshot",
            )
        data_path = self.root_dir / str(meta["data_file"])
        if not data_path.exists():
            return _unavailable_report(
                run_date,
                meta,
                reason="invalid_recommendation_snapshot",
            )
        try:
            data = data_path.read_bytes()
            meta_after = meta_path.read_bytes()
            if meta_before != meta_after:
                raise ValueError("snapshot meta changed during read")
            if sha256(data).hexdigest() != meta["data_sha256"]:
                raise ValueError("snapshot data digest mismatch")
            lines = _strict_jsonl_lines(data)
            if len(lines) > RECOMMENDATION_LIMIT:
                raise ValueError("snapshot exceeds recommendation limit")
            if meta["data_line_count"] != len(lines):
                raise ValueError("snapshot data line count mismatch")
            candidates = []
            identities: set[tuple[str, str, str]] = set()
            for payload in lines:
                if payload.get("run_date") != run_date:
                    raise ValueError("snapshot row run_date mismatch")
                identity = _candidate_key(payload)
                if identity in identities:
                    raise ValueError("snapshot candidate identity duplicated")
                identities.add(identity)
                candidate = _candidate_from_json(payload)
                if not _candidate_contract_valid(
                    candidate,
                    run_date=run_date,
                    risk_free_rate=float(meta.get("risk_free_rate")),
                    equity_risk_premium=_meta_equity_risk_premium(meta),
                    observed_at=str(meta["finished_at"]),
                    allowed_tickers=(
                        frozenset(CURATED_RECOMMENDATION_TICKERS)
                        if meta["expected_universe_size"] == len(CURATED_RECOMMENDATION_TICKERS)
                        else None
                    ),
                ):
                    raise ValueError("snapshot candidate violates the recommendation contract")
                candidates.append(candidate)
        except (OSError, UnicodeDecodeError, KeyError, TypeError, ValueError):
            return _unavailable_report(
                run_date,
                meta,
                reason="invalid_recommendation_snapshot",
            )
        ranked = sorted(
            candidates,
            key=lambda candidate: -float(candidate.recommendation_score or 0.0),
        )
        candidate_tickers = {candidate.ticker.upper().strip() for candidate in candidates}
        failed_tickers = {
            str(item[0]).upper().strip() for item in meta.get("failed_tickers", [])
        }
        if (
            ranked != candidates
            or meta["candidate_count"] != len(candidates)
            or (meta.get("status") == "available") != bool(candidates)
            or not _meta_as_of_covers_candidates(meta.get("as_of"), candidates)
            or bool(candidate_tickers.intersection(failed_tickers))
        ):
            return _unavailable_report(
                run_date,
                meta,
                reason="invalid_recommendation_snapshot",
            )
        return OptionsRadarReport(
            run_date=run_date,
            started_at=str(meta.get("started_at", "")),
            finished_at=str(meta.get("finished_at", "")),
            universe_size=int(meta.get("universe_size", 0)),
            expected_universe_size=int(meta.get("expected_universe_size", 0)),
            scanned_tickers=int(meta.get("scanned_tickers", 0)),
            failed_tickers=[tuple(item) for item in meta.get("failed_tickers", [])],
            candidates=candidates,
            provider=meta.get("provider"),
            as_of=meta.get("as_of"),
            status=meta.get("status", "unavailable"),
            risk_free_rate=meta.get("risk_free_rate"),
            equity_risk_premium=meta.get("equity_risk_premium"),
            shortfall_count=int(meta.get("shortfall_count", max(20 - len(candidates), 0))),
            shortfall_reasons={
                str(key): int(value)
                for key, value in dict(meta.get("shortfall_reasons", {})).items()
            },
        )

    def list_dates(self) -> list[str]:
        dates = []
        for path in self.root_dir.glob("*_meta.json"):
            dates.append(path.name.removesuffix("_meta.json"))
        return sorted(dates, reverse=True)

    def latest_date(self) -> str | None:
        dates = self.list_dates()
        return dates[0] if dates else None


def _candidate_to_json(run_date: str, candidate: OptionsRadarCandidate) -> dict:
    payload = asdict(candidate)
    payload["run_date"] = run_date
    option = candidate.candidate.model_dump(mode="json")
    payload["candidate"] = {field: option.get(field) for field in _OPTION_CONTRACT_FIELDS}
    return payload


def _candidate_from_json(payload: dict) -> OptionsRadarCandidate:
    if not _candidate_payload_types_valid(payload):
        raise TypeError("snapshot candidate field types are invalid")
    sector = payload.get("sector")
    return OptionsRadarCandidate(
        ticker=str(payload["ticker"]),
        sector=sector,
        strategy=payload["strategy"],
        candidate=OptionsScreenerCandidate.model_validate(payload["candidate"]),
        iv_rank=payload.get("iv_rank"),
        iv_measure=str(payload["iv_measure"]),
        iv_history_samples=int(payload["iv_history_samples"]),
        iv_rank_status=payload["iv_rank_status"],
        earnings_in_window=bool(payload.get("earnings_in_window", False)),
        global_score=float(payload.get("global_score", 0.0)),
        market_regime=payload.get("market_regime"),
        market_regime_penalty=float(payload.get("market_regime_penalty", 0.0)),
        gross_annualized_yield=float(payload["gross_annualized_yield"]),
        pop=float(payload["pop"]),
        otm_pct=float(payload["otm_pct"]),
        ex_dividend_date=payload.get("ex_dividend_date"),
        ex_dividend_in_window=bool(payload.get("ex_dividend_in_window", False)),
        dividend_per_share=(
            float(payload["dividend_per_share"])
            if payload.get("dividend_per_share") is not None
            else None
        ),
        extrinsic_value=float(payload["extrinsic_value"]),
        breakeven=float(payload["breakeven"]),
        take_profit_50_price=float(payload["take_profit_50_price"]),
        manage_at_21_dte=str(payload["manage_at_21_dte"]),
        expected_value=float(payload["expected_value"]),
        excess_annualized_ev=float(payload["excess_annualized_ev"]),
        liquidity_factor=float(payload["liquidity_factor"]),
        recommendation_score=float(payload["recommendation_score"]),
        recommendation_score_model=str(payload["recommendation_score_model"]),
        hard_gate_passed=payload.get("hard_gate_passed") is True,
        quote_as_of=str(payload["quote_as_of"]),
    )


def _candidate_key(payload: dict) -> tuple[str, str, str]:
    contract_symbol = str(payload["candidate"]["symbol"]).upper().strip()
    return (
        str(payload["ticker"]).upper().strip(),
        contract_symbol,
        str(payload["strategy"]).lower().strip(),
    )


def _meta_equity_risk_premium(meta: dict) -> float:
    value = meta.get("equity_risk_premium")
    if value is None:
        return DEFAULT_EQUITY_RISK_PREMIUM
    return float(value)


def _candidate_contract_valid(
    candidate: OptionsRadarCandidate,
    *,
    run_date: str,
    risk_free_rate: float,
    equity_risk_premium: float,
    observed_at: str,
    allowed_tickers: frozenset[str] | None,
) -> bool:
    option = candidate.candidate
    expected_seller_score = score_seller_contract(
        annualized_yield=option.annualized_yield,
        spread_pct=option.spread_pct,
        open_interest=option.open_interest,
        volume=option.volume,
        delta=option.delta,
        hv_iv_ratio=option.hv_iv_ratio,
        iv_rank=candidate.iv_rank,
        market_regime_penalty=candidate.market_regime_penalty,
    )
    if not (
        candidate.hard_gate_passed
        and candidate.recommendation_score_model == "seller_ev_liquidity_v1"
        and (allowed_tickers is None or candidate.ticker.upper().strip() in allowed_tickers)
        and _canonical_underlying(option.underlying) == candidate.ticker.upper().strip()
        and option_contract_identity_matches(
            {
                "symbol": option.symbol,
                "expiry": option.expiry,
                "option_type": option.option_type,
                "strike": option.strike,
            },
            ticker=candidate.ticker,
        )
        and _option_quote_consistent(option)
        and bool(candidate.quote_as_of)
        and bool(option.quote_as_of)
        and candidate.quote_as_of == option.quote_as_of
        and candidate.strategy == option.strategy_type
        and option.option_type == ("PUT" if candidate.strategy == "sell_put" else "CALL")
        and candidate.earnings_in_window is False
        and candidate.iv_measure == IV_MEASURE_ATM30_STRADDLE_V1
        and candidate.iv_history_samples >= 0
        and (
            (
                candidate.iv_rank_status == "warming"
                and candidate.iv_history_samples < 30
                and candidate.iv_rank is None
                and option.iv_rank is None
            )
            or (
                candidate.iv_rank_status == "ready"
                and candidate.iv_history_samples >= 30
                and candidate.iv_rank is not None
                and option.iv_rank is not None
                and math.isfinite(candidate.iv_rank)
                and math.isfinite(option.iv_rank)
                and math.isclose(candidate.iv_rank, option.iv_rank, abs_tol=1e-9)
            )
        )
        and _seller_scores_equal(option.seller_score, expected_seller_score)
        and option.market_regime == candidate.market_regime
        and _same_float(
            option.market_regime_penalty,
            candidate.market_regime_penalty,
        )
        and math.isfinite(candidate.global_score)
        and 0 <= candidate.global_score <= 100
        and _same_float(
            candidate.global_score,
            compute_global_score(
                seller_composite=expected_seller_score.composite,
                earnings_in_window=False,
            ),
        )
    ):
        return False
    try:
        evaluation = evaluate_seller_recommendation(
            strategy_type=candidate.strategy,
            strike=option.strike,
            underlying_price=option.underlying_price,
            mid=option.mid,
            spread_pct=option.spread_pct,
            open_interest=option.open_interest,
            delta=option.delta,
            days_to_expiry=option.days_to_expiry,
            implied_volatility=option.implied_volatility,
            iv_rank=candidate.iv_rank,
            risk_free_rate=risk_free_rate,
            run_date=run_date,
            expiry=option.expiry,
            earnings_date=option.earnings_date,
            is_etf=(candidate.sector or "").upper() == "ETF",
            ex_dividend_date=candidate.ex_dividend_date,
            dividend_per_share=candidate.dividend_per_share,
            quote_as_of=candidate.quote_as_of,
            observed_at=observed_at,
            historical_volatility=historical_volatility_from_ratio(
                option.hv_iv_ratio,
                option.implied_volatility,
            ),
            equity_risk_premium=equity_risk_premium,
        )
    except (TypeError, ValueError, OverflowError):
        return False
    if not evaluation.hard_gate_passed:
        return False
    return (
        _same_float(candidate.extrinsic_value, evaluation.extrinsic_value)
        and _same_float(
            candidate.gross_annualized_yield,
            evaluation.gross_annualized_yield,
        )
        and _same_float(candidate.pop, evaluation.pop)
        and _same_float(candidate.otm_pct, evaluation.otm_pct)
        and candidate.ex_dividend_date == evaluation.ex_dividend_date
        and candidate.ex_dividend_in_window == evaluation.ex_dividend_in_window
        and _same_float(candidate.dividend_per_share, evaluation.dividend_per_share)
        and _same_float(candidate.breakeven, evaluation.breakeven)
        and _same_float(
            candidate.take_profit_50_price,
            evaluation.take_profit_50_price,
        )
        and candidate.manage_at_21_dte == evaluation.manage_at_21_dte
        and _same_float(candidate.expected_value, evaluation.expected_value)
        and _same_float(
            candidate.excess_annualized_ev,
            evaluation.excess_annualized_ev,
        )
        and _same_float(candidate.liquidity_factor, evaluation.liquidity_factor)
        and _same_float(
            candidate.recommendation_score,
            evaluation.recommendation_score,
        )
        and candidate.recommendation_score_model == evaluation.recommendation_score_model
        and candidate.quote_as_of == evaluation.quote_as_of
    )


def _same_float(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is right
    return (
        math.isfinite(left)
        and math.isfinite(right)
        and math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-12)
    )


def _seller_scores_equal(actual, expected) -> bool:
    """Permit arithmetic/JSON roundoff, never a different score or weight set."""
    if actual is None:
        return False
    left, right = actual.model_dump(), expected.model_dump()
    left_weights, right_weights = left.pop("weights_used"), right.pop("weights_used")
    if left_weights.keys() != right_weights.keys():
        return False
    return all(
        a is b
        if a is None or b is None
        else (
            math.isfinite(a)
            and math.isfinite(b)
            and math.isclose(a, b, rel_tol=1e-14, abs_tol=1e-12)
        )
        for a, b in [
            *((left[key], right[key]) for key in left),
            *((left_weights[key], right_weights[key]) for key in left_weights),
        ]
    )


def _canonical_underlying(value: str) -> str:
    normalized = value.upper().strip()
    return normalized.removeprefix("US.")


def _candidate_payload_types_valid(payload: dict) -> bool:
    option = payload.get("candidate")
    if (
        set(payload) != _SNAPSHOT_CANDIDATE_FIELDS
        or not isinstance(option, dict)
        or set(option) != _OPTION_CONTRACT_FIELDS
    ):
        return False
    if not all(
        _is_nonempty_string(payload.get(field))
        for field in (
            "ticker",
            "strategy",
            "manage_at_21_dte",
            "iv_measure",
            "iv_rank_status",
            "recommendation_score_model",
            "quote_as_of",
            "run_date",
        )
    ):
        return False
    if payload.get("sector") is not None and not isinstance(payload.get("sector"), str):
        return False
    if payload.get("market_regime") is not None and not isinstance(
        payload.get("market_regime"), str
    ):
        return False
    if payload.get("iv_rank_status") not in {"warming", "ready"}:
        return False
    if not _is_plain_int(payload.get("iv_history_samples"), minimum=0):
        return False
    if not all(
        isinstance(payload.get(field), bool)
        for field in (
            "earnings_in_window",
            "ex_dividend_in_window",
            "hard_gate_passed",
        )
    ):
        return False
    required_top_numbers = (
        "global_score",
        "market_regime_penalty",
        "gross_annualized_yield",
        "pop",
        "otm_pct",
        "extrinsic_value",
        "breakeven",
        "take_profit_50_price",
        "expected_value",
        "excess_annualized_ev",
        "liquidity_factor",
        "recommendation_score",
    )
    if not all(_is_plain_finite_number(payload.get(field)) for field in required_top_numbers):
        return False
    if payload.get("iv_rank") is not None and not _is_plain_finite_number(
        payload.get("iv_rank")
    ):
        return False
    if payload.get("dividend_per_share") is not None and not _is_plain_finite_number(
        payload.get("dividend_per_share")
    ):
        return False
    if payload.get("ex_dividend_date") is not None and not isinstance(
        payload.get("ex_dividend_date"), str
    ):
        return False
    if not all(
        _is_nonempty_string(option.get(field))
        for field in (
            "symbol",
            "underlying",
            "strategy_type",
            "option_type",
            "expiry",
            "rating",
            "quote_as_of",
        )
    ):
        return False
    for field in ("earnings_date", "market_regime"):
        if option.get(field) is not None and not isinstance(option.get(field), str):
            return False
    notes = option.get("notes")
    if not isinstance(notes, list) or not all(isinstance(note, str) for note in notes):
        return False
    required_option_numbers = (
        "strike",
        "underlying_price",
        "bid",
        "ask",
        "mid",
        "open_interest",
        "implied_volatility",
        "delta",
        "days_to_expiry",
        "annualized_yield",
        "spread_pct",
        "market_regime_penalty",
    )
    if not all(_is_plain_finite_number(option.get(field)) for field in required_option_numbers):
        return False
    if option.get("iv_rank") is not None and not _is_plain_finite_number(
        option.get("iv_rank")
    ):
        return False
    if not _is_plain_int(option.get("days_to_expiry"), minimum=0):
        return False
    for field in (
        "volume",
        "historical_volatility",
        "hv_iv_ratio",
        "gamma",
        "theta",
        "vega",
        "premium_per_contract",
        "moneyness",
        "distance_pct",
        "avg_daily_volume",
        "market_cap",
    ):
        if option.get(field) is not None and not _is_plain_finite_number(option.get(field)):
            return False
    for field in ("trend_pass", "hv_iv_pass"):
        if option.get(field) is not None and not isinstance(option.get(field), bool):
            return False
    return _seller_score_payload_types_valid(option.get("seller_score"))


def _seller_score_payload_types_valid(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != _SELLER_SCORE_FIELDS:
        return False
    for field in (
        "yield_score",
        "liquidity_score",
        "delta_safety_score",
        "iv_edge_score",
        "iv_rank_score",
    ):
        if value.get(field) is not None and not _is_plain_finite_number(value.get(field)):
            return False
    if not _is_plain_finite_number(value.get("composite")):
        return False
    weights = value.get("weights_used")
    return isinstance(weights, dict) and all(
        isinstance(key, str) and _is_plain_finite_number(weight) for key, weight in weights.items()
    )


def _is_plain_finite_number(value: object) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _option_quote_consistent(option: OptionsScreenerCandidate) -> bool:
    if any(value is None for value in (option.bid, option.ask, option.mid, option.spread_pct)):
        return False
    assert option.bid is not None
    assert option.ask is not None
    assert option.mid is not None
    assert option.spread_pct is not None
    if not all(
        math.isfinite(float(value))
        for value in (option.bid, option.ask, option.mid, option.spread_pct)
    ):
        return False
    if option.bid < 0 or option.ask < option.bid or option.mid <= 0:
        return False
    expected_mid = (option.bid + option.ask) / 2.0
    expected_spread = (option.ask - option.bid) / expected_mid
    return math.isclose(option.mid, expected_mid, rel_tol=1e-9, abs_tol=1e-12) and math.isclose(
        option.spread_pct,
        expected_spread,
        rel_tol=1e-9,
        abs_tol=1e-12,
    )


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _meta_as_of_covers_candidates(
    meta_as_of: object,
    candidates: list[OptionsRadarCandidate],
) -> bool:
    if not candidates:
        return True
    watermark = _parse_timestamp(meta_as_of)
    candidate_times = [_parse_timestamp(item.quote_as_of) for item in candidates]
    return (
        watermark is not None
        and all(value is not None for value in candidate_times)
        and all(watermark <= value for value in candidate_times if value is not None)
    )


def _meta_contract_valid(meta: dict, *, expected_run_date: str) -> bool:
    status = meta.get("status")
    provider = meta.get("provider")
    rate = meta.get("risk_free_rate")
    if not (
        meta.get("contract_version") == RECOMMENDATION_CONTRACT_VERSION
        and _is_snapshot_generation(meta.get("snapshot_generation"))
        and _valid_generation_data_file(
            meta.get("data_file"),
            run_date=expected_run_date,
            generation=meta.get("snapshot_generation"),
        )
        and _is_sha256(meta.get("data_sha256"))
        and _is_plain_int(meta.get("data_line_count"), minimum=0)
        and meta["data_line_count"] <= RECOMMENDATION_LIMIT
        and meta.get("run_date") == expected_run_date
        and _parse_timestamp(meta.get("started_at")) is not None
        and _parse_timestamp(meta.get("finished_at")) is not None
        and _is_plain_int(meta.get("universe_size"), minimum=0)
        and _is_plain_int(meta.get("expected_universe_size"), minimum=1)
        and meta["universe_size"] == meta["expected_universe_size"]
        and (
            meta.get("expected_universe_size") != len(CURATED_RECOMMENDATION_TICKERS)
            or meta.get("universe_digest") == CURATED_UNIVERSE_DIGEST
        )
        and _is_plain_int(meta.get("scanned_tickers"), minimum=0)
        and meta["scanned_tickers"] <= meta["universe_size"]
        and _coverage_contract_valid(
            scanned_tickers=meta["scanned_tickers"],
            universe_size=meta["universe_size"],
            expected_universe_size=meta["expected_universe_size"],
            failed_tickers=meta.get("failed_tickers"),
        )
        and (provider is None or isinstance(provider, str))
        and provider in (None, "sample", "futu")
        and isinstance(status, str)
        and status in ("available", "empty", "unavailable")
        and _is_plain_int(meta.get("shortfall_count"), minimum=0)
        and _valid_reason_counts(meta.get("shortfall_reasons"))
        and _is_plain_int(meta.get("candidate_count"), minimum=0)
        and meta["candidate_count"] <= RECOMMENDATION_LIMIT
    ):
        return False
    expected_shortfall = RECOMMENDATION_LIMIT - meta["candidate_count"]
    eligible_shortfall = meta["shortfall_reasons"].get("eligible_contracts_below_limit")
    if (
        meta["shortfall_count"] != expected_shortfall
        or (expected_shortfall > 0 and eligible_shortfall != expected_shortfall)
        or (expected_shortfall == 0 and eligible_shortfall is not None)
    ):
        return False
    if meta.get("as_of") is not None and _parse_timestamp(meta.get("as_of")) is None:
        return False
    if status in {"available", "empty"}:
        return (
            provider == "futu"
            and meta["scanned_tickers"] > 0
            and _parse_timestamp(meta.get("as_of")) is not None
            and isinstance(rate, int | float)
            and not isinstance(rate, bool)
            and math.isfinite(float(rate))
            and float(rate) >= 0
        )
    return meta["candidate_count"] == 0


def _unavailable_report(
    run_date: str,
    meta: dict,
    *,
    reason: str,
) -> OptionsRadarReport:
    provider = meta.get("provider")
    safe_provider = (
        provider if isinstance(provider, str) and provider in ("sample", "futu") else None
    )
    return OptionsRadarReport(
        run_date=run_date,
        started_at=_safe_string(meta.get("started_at")),
        finished_at=_safe_string(meta.get("finished_at")),
        universe_size=_safe_int(meta.get("universe_size")),
        expected_universe_size=_safe_int(meta.get("expected_universe_size")),
        scanned_tickers=_safe_int(meta.get("scanned_tickers")),
        failed_tickers=_safe_failed_tickers(meta.get("failed_tickers")),
        candidates=[],
        provider=safe_provider,
        as_of=None,
        status="unavailable",
        risk_free_rate=None,
        shortfall_count=RECOMMENDATION_LIMIT,
        shortfall_reasons={reason: 1},
    )


def _strict_json_document(raw: bytes) -> object:
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_reject_json_constant,
    )


def _strict_jsonl_lines(raw: bytes) -> list[dict]:
    text = raw.decode("utf-8")
    if not text:
        return []
    lines = text.splitlines()
    if any(not line.strip() for line in lines):
        raise ValueError("snapshot contains a blank JSONL row")
    payloads = [_strict_json_document(line.encode("utf-8")) for line in lines]
    if not all(isinstance(payload, dict) for payload in payloads):
        raise ValueError("snapshot JSONL rows must be objects")
    return payloads  # type: ignore[return-value]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key: {key}")
        payload[key] = value
    return payload


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"invalid JSON constant: {value}")


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_snapshot_generation(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 32
        and all(character in "0123456789abcdef" for character in value)
    )


def _valid_generation_data_file(
    value: object,
    *,
    run_date: str,
    generation: object,
) -> bool:
    if not isinstance(value, str) or not _is_snapshot_generation(generation):
        return False
    return Path(value).name == value and value == f"{run_date}.{generation}.jsonl"


def _is_plain_int(value: object, *, minimum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _valid_failed_tickers(
    value: object,
    *,
    allowed_tickers: frozenset[str] | None = None,
) -> bool:
    if not isinstance(value, list) or not all(
        isinstance(item, list | tuple)
        and len(item) == 2
        and all(isinstance(field, str) and bool(field.strip()) for field in item)
        for item in value
    ):
        return False
    normalized = [str(item[0]).upper().strip() for item in value]
    return len(normalized) == len(set(normalized)) and (
        allowed_tickers is None or all(ticker in allowed_tickers for ticker in normalized)
    )


def _coverage_contract_valid(
    *,
    scanned_tickers: object,
    universe_size: object,
    expected_universe_size: object,
    failed_tickers: object,
) -> bool:
    if not (
        _is_plain_int(scanned_tickers, minimum=0)
        and _is_plain_int(universe_size, minimum=0)
        and _is_plain_int(expected_universe_size, minimum=1)
    ):
        return False
    allowed_tickers = (
        frozenset(CURATED_RECOMMENDATION_TICKERS)
        if expected_universe_size == len(CURATED_RECOMMENDATION_TICKERS)
        else None
    )
    return (
        _valid_failed_tickers(failed_tickers, allowed_tickers=allowed_tickers)
        and scanned_tickers + len(failed_tickers) == universe_size
    )


def _valid_reason_counts(value: object) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str) and _is_plain_int(count, minimum=0) for key, count in value.items()
    )


def _safe_string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _safe_int(value: object) -> int:
    return value if _is_plain_int(value, minimum=0) else 0


def _safe_failed_tickers(value: object) -> list[tuple[str, str]]:
    if not _valid_failed_tickers(value):
        return []
    return [(str(item[0]), str(item[1])) for item in value]  # type: ignore[index]
