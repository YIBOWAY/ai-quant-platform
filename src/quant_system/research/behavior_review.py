"""V2 bounded daily-factor review with an explicit executable DSL reference.

PASS requires temporal probes AND scores/ranks/target-weight agreement with a
declared whitelist expression on every valid probe input. Without that reference
the review is advisory-only/not_evaluated. Cross-sectional custom models,
fundamental semantics, unknown warm-up/universe policies and external data truth
are not supported approval domains. Runtime consumes physically clipped as-of
inputs. This never proves arbitrary Python correct or authorizes promotion.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from quant_system.research.exploration_sandbox import DockerSandbox, digest, records

VERSION = "daily-factor-behavior/v2"
KEYS = ["symbol", "timestamp"]
FIELDS = ["open", "high", "low", "close", "volume"]
REQUIRED = {*KEYS, *FIELDS, "eligible", "available_at"}


def prepare_input(ohlcv: pd.DataFrame) -> pd.DataFrame:
    if not REQUIRED.issubset(ohlcv):
        raise ValueError("missing_daily_factor_columns")
    frame = ohlcv.copy()
    for name in ("timestamp", "available_at"):
        frame[name] = pd.to_datetime(frame[name], utc=True)
        if frame[name].isna().any():
            raise ValueError("missing_visibility_timestamp")
    if frame.empty or frame.duplicated(KEYS).any():
        raise ValueError("empty_or_duplicate_panel")
    if not frame.eligible.map(lambda value: isinstance(value, (bool, np.bool_))).all():
        raise ValueError("membership_must_be_boolean")
    if not frame.symbol.map(lambda value: isinstance(value, str) and bool(value)).all():
        raise ValueError("invalid_symbol")
    for field in FIELDS:
        frame[field] = pd.to_numeric(frame[field], errors="raise")
        values = frame[field].dropna()
        if not np.isfinite(values).all() or (values < 0).any():
            raise ValueError("invalid_market_value")
    return frame.sort_values(KEYS, ignore_index=True)


def checked_scores(result: dict, frame: pd.DataFrame) -> pd.DataFrame:
    if result.get("status") != "ok":
        raise ValueError(result.get("reason", "execution_unavailable"))
    scores = pd.DataFrame(result["scores"])
    if list(scores.columns) != [*KEYS, "score"]:
        raise ValueError("invalid_score_columns")
    scores["timestamp"] = pd.to_datetime(scores.timestamp, utc=True)
    if scores.duplicated(KEYS).any():
        raise ValueError("duplicate_scores")
    scores = scores.sort_values(KEYS, ignore_index=True)
    if not scores[KEYS].equals(frame[KEYS]):
        raise ValueError("score_grid_mismatch")
    if scores.score.map(lambda v: isinstance(v, (str, bool))).any():
        raise ValueError("score_must_be_numeric")
    scores["score"] = pd.to_numeric(scores.score, errors="raise")
    if not np.isfinite(scores.score.dropna()).all():
        raise ValueError("nonfinite_scores")
    unavailable = ~frame.eligible | frame.close.isna() | (frame.available_at > frame.timestamp)
    if scores.score[unavailable].notna().any():
        raise ValueError("unavailable_or_nonmember_scored")
    return scores


def _same(left: pd.DataFrame, right: pd.DataFrame, cutoff=None) -> bool:
    if cutoff is not None:
        left, right = (f[f.timestamp <= cutoff] for f in (left, right))
    joined = left.merge(right, on=KEYS, how="outer", suffixes=("_a", "_b"), indicator=True)
    return bool(
        (joined["_merge"] == "both").all()
        and np.allclose(joined.score_a, joined.score_b, equal_nan=True, atol=1e-12, rtol=1e-10)
    )


def review_factor(
    source: str,
    ohlcv: pd.DataFrame,
    context: dict | None = None,
    *,
    runner: DockerSandbox | None = None,
    expected_expression: str | None = None,
) -> dict:
    """Execute unchanged source on frozen, mutated and truncated inputs.

    Optional context['observations'] is a list of symbol/available_at/value
    records. Its future records are poisoned and removed in paired tests. Their
    external provenance, revision semantics and truth are NOT verified here.
    A supplied expected_expression freezes the intended OHLCV formula, null
    propagation and membership contract. Missing/unexpressible references cannot
    produce pass, even if every temporal/advisory probe passes.
    """
    runner = runner or DockerSandbox()
    context = context or {}
    identity = {
        "version": VERSION,
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "input_digest": digest({"ohlcv": records(ohlcv), "context": context}),
        "expected_expression": expected_expression,
    }
    report = {
        **identity,
        "scope": "bounded_daily_ohlcv_behavior",
        "promotion_authorized": False,
        "switch_authorized": False,
        "probes": [],
        "not_evaluated": [
            "external_source_truth_and_security_identity",
            "arbitrary_model_training",
            "delayed_bar_revision_reuse",
            "factor_owned_cost_accounting",
            "unseen_programs_and_inputs",
            "independent_calibration",
        ],
        "status": "not_evaluated",
    }
    if set(context) - {"observations"}:
        report["reason"] = "unsupported_context_fields"
        return report
    if set(ohlcv) - REQUIRED:
        report["reason"] = "unsupported_input_fields"
        return report
    if "observations" in context:
        observations = context["observations"]
        if not isinstance(observations, list) or any(
            not isinstance(row, dict) or set(row) != {"symbol", "available_at", "value"}
            for row in observations
        ):
            report["reason"] = "unsupported_observation_schema"
            return report
    try:
        frame = prepare_input(ohlcv)
    except (ValueError, TypeError) as exc:
        report["reason"] = str(exc)
        return report
    dates = sorted(frame.timestamp.unique())
    if len(dates) < 8 or frame.symbol.nunique() < 2:
        report["reason"] = "insufficient_probe_panel"
        return report
    # All prefixes on small calibration windows, four explicit anchors on long
    # windows. Passing sampled long-window probes is not a universal proof.
    anchors = {dates[0], dates[len(dates) // 3], dates[2 * len(dates) // 3], dates[-2]}
    cutoffs = dates[:-1] if len(dates) <= 32 else sorted(anchors)
    report["prefix_policy"] = "all_small_window_prefixes" if len(dates) <= 32 else "four_anchors"
    jobs = {"baseline": (frame, context), "repeat": (frame, context)}
    for n, cutoff in enumerate(cutoffs):
        if cutoff in anchors:
            future = frame.copy()
            future.loc[future.timestamp > cutoff, FIELDS] *= 17.0 + n
            future.loc[future.timestamp > cutoff, "eligible"] = False
            future.loc[future.timestamp > cutoff, "available_at"] = dates[-1] + pd.Timedelta(
                days=30
            )
            jobs[f"future_{n}"] = (future, context)
        jobs[f"prefix_{n}"] = (frame[frame.timestamp <= cutoff].reset_index(drop=True), context)
    delayed = frame.copy()
    hidden = (delayed.symbol == delayed.symbol.iloc[0]) & (delayed.timestamp == cutoffs[0])
    delayed.loc[hidden, "available_at"] = dates[-1] + pd.Timedelta(days=30)
    masked = delayed.copy()
    masked.loc[hidden, FIELDS] = np.nan
    poisoned = delayed.copy()
    poisoned.loc[hidden, FIELDS] *= 97
    jobs["visibility_masked"], jobs["visibility_poisoned"] = (masked, context), (poisoned, context)
    membership = frame.copy()
    membership.loc[
        (membership.timestamp >= cutoffs[0]) & (membership.symbol == frame.symbol.iloc[0]),
        "eligible",
    ] = False
    jobs["membership"] = (membership, context)
    missing = frame.copy()
    missing.loc[hidden, "close"] = np.nan
    jobs["missing_market"] = (missing, context)
    jobs["malformed"] = (frame.drop(columns="close"), context)
    observations = context.get("observations")
    observation_ready = isinstance(observations, list) and bool(observations)
    if observation_ready:
        try:
            cutoff = cutoffs[0]
            visible = [row for row in observations if pd.Timestamp(row["available_at"]) <= cutoff]
            future_records = [
                row for row in observations if pd.Timestamp(row["available_at"]) > cutoff
            ]
            if not future_records:
                observation_ready = False
            else:
                changed = [
                    {**row, "value": float(row["value"]) * 173 + 71} for row in future_records
                ]
                prefix = jobs["prefix_0"][0]
                jobs["observations_visible"] = (prefix, {**context, "observations": visible})
                jobs["observations_poisoned"] = (
                    prefix,
                    {**context, "observations": visible + changed},
                )
        except (ValueError, TypeError, KeyError):
            observation_ready = False
    if not observation_ready:
        report["not_evaluated"].append("published_observations_visibility")
        if "observations" in context:
            report["probes"].append(
                {
                    "probe": "published_observations_visibility",
                    "status": "not_evaluated",
                    "reason": "no_valid_future_observations_for_probe",
                }
            )

    def execute(item):
        name, (bars, ctx) = item
        return name, runner.run(source, bars, ctx)

    with ThreadPoolExecutor(max_workers=4) as pool:
        executions = dict(pool.map(execute, jobs.items()))
    report["executions"] = {
        name: {key: value for key, value in run.items() if key != "scores"}
        for name, run in executions.items()
    }
    parsed, invalid = {}, {}
    for name, result in executions.items():
        if name == "malformed":
            continue
        try:
            if result.get("status") == "ok" and (
                result.get("source_sha256") != identity["source_sha256"]
                or result.get("input_digest")
                != digest({"ohlcv": records(jobs[name][0]), "context": jobs[name][1]})
                or not result.get("isolation")
            ):
                invalid[name] = ("not_evaluated", "execution_identity_not_attested")
                continue
            parsed[name] = checked_scores(result, jobs[name][0])
        except (ValueError, TypeError, KeyError) as exc:
            invalid[name] = (
                "not_evaluated" if result.get("status") == "not_evaluated" else "fail",
                str(exc),
            )

    def compare(probe, left, right=None, cutoff=None):
        bad = [invalid[name] for name in (left, right) if name in invalid]
        if bad:
            state = "fail" if any(item[0] == "fail" for item in bad) else "not_evaluated"
            reason = ";".join(item[1] for item in bad)
        else:
            state = (
                "pass" if right is None or _same(parsed[left], parsed[right], cutoff) else "fail"
            )
            reason = (
                "contract_checked"
                if right is None
                else "invariant_preserved"
                if state == "pass"
                else "scores_changed"
            )
        report["probes"].append(
            {
                "probe": probe,
                "status": state,
                "reason": reason,
                "executions": [name for name in (left, right) if name],
                "cutoff": str(cutoff) if cutoff is not None else None,
            }
        )

    compare("output_contract", "baseline")
    compare("determinism", "baseline", "repeat")
    for n, cutoff in enumerate(cutoffs):
        if cutoff in anchors:
            compare("future_perturbation", "baseline", f"future_{n}", cutoff)
        compare("prefix_truncation", "baseline", f"prefix_{n}", cutoff)
    compare("available_at_visibility", "visibility_masked", "visibility_poisoned")
    compare("membership_change", "membership")
    compare("missing_market_data", "missing_market")
    malformed = executions["malformed"]
    malformed_state = (
        "pass"
        if malformed.get("reason") == "factor_exception"
        else "not_evaluated"
        if malformed.get("status") == "not_evaluated"
        else "fail"
    )
    report["probes"].append(
        {
            "probe": "fault_propagation",
            "status": malformed_state,
            "reason": malformed.get("reason", "swallowed_malformed_input"),
            "executions": ["malformed"],
        }
    )
    if observation_ready:
        compare(
            "published_observations_visibility", "observations_visible", "observations_poisoned"
        )
    states = {item["status"] for item in report["probes"]}
    report["status"] = (
        "fail" if "fail" in states else "not_evaluated" if "not_evaluated" in states else "pass"
    )
    if "baseline" in parsed:
        report["scores"] = records(parsed["baseline"])
        scored = parsed["baseline"].dropna(subset=["score"])
        if scored.timestamp.nunique() < 3 or scored.symbol.nunique() < 2:
            report["probes"].append(
                {
                    "probe": "evidence_sufficiency",
                    "status": "not_evaluated",
                    "reason": "insufficient_nonnull_scores",
                }
            )
            if report["status"] != "fail":
                report["status"] = "not_evaluated"
    if expected_expression is None:
        report["reference"] = {"status": "not_evaluated", "reason": "expected_expression_required"}
    else:
        comparisons = {
            name: verify_translation(expected_expression, jobs[name][0], scores)
            for name, scores in parsed.items()
        }
        reference_states = {item["status"] for item in comparisons.values()}
        reference_state = (
            "fail"
            if "fail" in reference_states
            else "not_evaluated"
            if "not_evaluated" in reference_states or not comparisons
            else "pass"
        )
        report["reference"] = {
            "status": reference_state,
            "comparisons": comparisons,
            "contract_digest": digest(
                {
                    "expected_expression": expected_expression,
                    "comparator_version": VERSION,
                    "top_k": 2,
                }
            ),
        }
    if report["reference"]["status"] == "fail":
        report["status"] = "fail"
    elif report["reference"]["status"] != "pass" and report["status"] == "pass":
        report["status"] = "not_evaluated"
    # Mirror the settled status so a not_evaluated review never carries a
    # pass-shaped advisory field.
    report["advisory_status"] = report["status"]
    report["review_digest"] = digest(report)
    return report


def verify_cost_trace(trades: list[dict] | None) -> dict:
    """Independent cash-cost reference for signed share trades, both buys/sells.

    This verifies the supplied trace, not whether all real fills were supplied.
    The compute-only factor contract does not own execution costs.
    """
    if not trades:
        return {"status": "not_evaluated", "reason": "trade_trace_missing"}
    checked = []
    try:
        for row in trades:
            quantity, price = float(row["quantity"]), float(row["price"])
            commission, slippage = float(row["commission"]), float(row["slippage"])
            if not all(np.isfinite([quantity, price, commission, slippage])) or price <= 0:
                raise ValueError("invalid_trade")
            notional = abs(quantity) * price
            expected = (notional / 10000, notional * 5 / 10000)
            checked.append(np.allclose((commission, slippage), expected, atol=1e-10, rtol=1e-10))
    except (ValueError, TypeError, KeyError):
        return {"status": "not_evaluated", "reason": "invalid_trade_trace"}
    return {
        "status": "pass" if all(checked) else "fail",
        "trade_count": len(checked),
        "commission_bps": 1.0,
        "slippage_bps": 5.0,
        "trace_digest": digest(trades),
        "scope": "supplied_trade_cost_arithmetic_only",
    }


def run_factor_asof(
    source: str, ohlcv: pd.DataFrame, context: dict, *, as_of, runner: DockerSandbox | None = None
) -> dict:
    """Run on a physically clipped input, returning only the decision timestamp.

    This is the downstream execution contract. The container cannot read future
    rows from the host because ONLY the clipped payload is copied to its mount.
    It cannot establish whether the caller's prices/member identities are true.
    """
    if set(ohlcv) != REQUIRED or set(context) - {"observations"}:
        return {"status": "not_evaluated", "reason": "unsupported_asof_input"}
    try:
        cutoff = pd.Timestamp(as_of)
        if cutoff.tzinfo is None:
            raise ValueError("asof_requires_timezone")
        cutoff = cutoff.tz_convert("UTC")
        frame = prepare_input(ohlcv)
        visible = frame[(frame.timestamp <= cutoff) & (frame.available_at <= cutoff)]
        visible = visible.reset_index(drop=True)
        if not (visible.timestamp == cutoff).any():
            return {"status": "not_evaluated", "reason": "no_visible_asof_market_rows"}
        clipped_context = {}
        if "observations" in context:
            observations = context["observations"]
            if not isinstance(observations, list) or any(
                not isinstance(row, dict) or set(row) != {"symbol", "available_at", "value"}
                for row in observations
            ):
                raise ValueError("unsupported_observation_schema")
            clipped_context["observations"] = [
                row for row in observations if pd.Timestamp(row["available_at"]) <= cutoff
            ]
    except (ValueError, TypeError, KeyError) as exc:
        return {"status": "not_evaluated", "reason": str(exc)}
    result = (runner or DockerSandbox()).run(source, visible, clipped_context)
    if result["status"] != "ok":
        return result
    try:
        scores = checked_scores(result, visible)
    except (ValueError, TypeError, KeyError) as exc:
        return {"status": "error", "reason": str(exc)}
    return {
        **result,
        "scores": records(scores[scores.timestamp == cutoff]),
        "as_of": cutoff.isoformat(),
        "visible_input_rows": len(visible),
        "scope": "physically_clipped_asof_input",
        "promotion_authorized": False,
    }


def _ranking_and_holdings(scores: pd.DataFrame, top_k: int):
    ranked = (
        scores.dropna(subset=["score"])
        .sort_values(["timestamp", "score", "symbol"], ascending=[True, False, True])
        .copy()
    )
    ranked["rank"] = ranked.groupby("timestamp").cumcount() + 1
    held = ranked[ranked["rank"] <= top_k].copy()
    held["weight"] = 1 / held.groupby("timestamp")["symbol"].transform("count")
    return records(ranked[[*KEYS, "rank"]]), records(held[[*KEYS, "weight"]])


def verify_translation(
    expression: str, ohlcv: pd.DataFrame, scores: pd.DataFrame, *, top_k: int = 2
) -> dict:
    """Check a proposed DSL translation; never generate or run arbitrary host code."""
    from quant_system.d34.qlib_expr import compile_qlib_expr

    if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 100:
        raise ValueError("invalid_top_k")
    try:
        compiled = compile_qlib_expr(expression)
        frame = prepare_input(ohlcv)
        # Late bars are deliberately outside the v1 supported factor interface.
        frame.loc[frame.available_at > frame.timestamp, FIELDS] = np.nan
        values = eval(compiled.pandas_body, {"__builtins__": {}, "np": np, "frame": frame})  # noqa: S307
        if not isinstance(values, pd.Series):
            return {"status": "not_evaluated", "reason": "scalar_dsl_not_supported"}
        translated = frame[KEYS].assign(score=values.where(frame.eligible & frame.close.notna()))
        expected = checked_scores({"status": "ok", "scores": records(translated)}, frame)
        actual = checked_scores({"status": "ok", "scores": records(scores)}, frame)
    except (ValueError, TypeError, KeyError) as exc:
        return {"status": "not_evaluated", "reason": str(exc)}
    ranks_a, weights_a = _ranking_and_holdings(actual, top_k)
    ranks_b, weights_b = _ranking_and_holdings(expected, top_k)
    checks = {
        "scores_equal": _same(actual, expected),
        "rankings_equal": ranks_a == ranks_b,
        "holdings_equal": weights_a == weights_b,
    }
    compiler = Path(__file__).resolve().parents[1] / "d34/qlib_expr.py"
    return {
        "status": "pass" if all(checks.values()) else "fail",
        **checks,
        "expression": compiled.qlib,
        "lookback": compiled.lookback,
        "compiler_sha256": hashlib.sha256(compiler.read_bytes()).hexdigest(),
        "input_digest": digest(records(frame)),
        "code_scores_digest": digest(records(actual)),
        "dsl_scores_digest": digest(records(expected)),
        "holdings_digest": digest(weights_a),
        "top_k": top_k,
        "scope": "supplied_input_scores_rankings_and_target_weights",
    }


def run_research_exploration(
    source: str,
    ohlcv: pd.DataFrame,
    context: dict,
    *,
    expression: str,
    output_dir: Path,
    runner: DockerSandbox | None = None,
    reported_costs: list[dict] | None = None,
) -> dict:
    """One local, temporary research attempt. Never imports the paper/gate service.

    Scorecards have no executable net portfolio curve. Therefore this path writes
    an honest skipped trial plus a hypothesis record, and cannot claim DSR-family
    admission. A separate real replay must bind a net curve before promotion.
    """
    from quant_system.factors.scorecard import build_factor_scorecards
    from quant_system.research.trials import ResearchTrial, TrialsLedger

    output_dir = Path(output_dir).resolve()
    temporary_root = Path(tempfile.gettempdir()).resolve()
    if not output_dir.is_relative_to(temporary_root) or output_dir == temporary_root:
        raise ValueError("exploration_output_must_be_temporary")
    output_dir.mkdir(parents=True, exist_ok=False)
    review = review_factor(source, ohlcv, context, runner=runner, expected_expression=expression)
    report = {
        "schema": "research_exploration/v1",
        "status": "not_evaluated",
        "scope": "research_only",
        "promotion_authorized": False,
        "switch_authorized": False,
        "behavior": review,
        "cost_reference": verify_cost_trace(reported_costs),
        "translation": {"status": "not_evaluated", "reason": "behavior_not_passed"},
        "dsr_family": {
            "status": "not_evaluated",
            "reason": "scorecard_has_no_executable_net_returns",
        },
    }
    (output_dir / "factor.py").write_text(source, encoding="utf-8")
    (output_dir / "input.json").write_text(
        json.dumps({"ohlcv": records(ohlcv), "context": context}, allow_nan=False), encoding="utf-8"
    )
    if review["status"] == "pass":
        frame = prepare_input(ohlcv)
        dates = sorted(frame.timestamp.unique())
        if len(dates) > 64:
            report["causal_execution"] = {
                "status": "not_evaluated",
                "reason": "asof_session_budget_exceeded",
                "limit": 64,
            }
            causal_scores = None
        else:

            def asof_run(stamp):
                return run_factor_asof(source, frame, context, as_of=stamp, runner=runner)

            with ThreadPoolExecutor(max_workers=4) as pool:
                runs = list(pool.map(asof_run, dates))
            report["causal_execution"] = {
                "status": "pass" if all(run["status"] == "ok" for run in runs) else "not_evaluated",
                "scope": "physically_clipped_input_per_decision_date",
                "executions": [
                    {key: value for key, value in run.items() if key != "scores"} for run in runs
                ],
            }
            causal_scores = None
            if report["causal_execution"]["status"] == "pass":
                raw_scores = pd.DataFrame([row for run in runs for row in run["scores"]])
                raw_scores["timestamp"] = pd.to_datetime(raw_scores.timestamp, utc=True)
                # Explicitly absent/unpublished rows get null, never fabricated prices/scores.
                causal_scores = frame[KEYS].merge(raw_scores, on=KEYS, how="left")
        if causal_scores is not None:
            scores = checked_scores({"status": "ok", "scores": records(causal_scores)}, frame)
            report["batch_vs_causal_equal"] = _same(
                checked_scores({"status": "ok", "scores": review["scores"]}, frame), scores
            )
        else:
            scores = None
    else:
        scores = None
    if scores is not None:
        report["translation"] = verify_translation(expression, frame, scores)
        factor_id = "explore_" + review["source_sha256"][:16]
        factor_results = scores.rename(columns={"timestamp": "signal_ts", "score": "value"})
        factor_results["tradeable_ts"] = frame.groupby("symbol", sort=False).timestamp.shift(-1)
        factor_results["factor_id"] = factor_id
        factor_results["factor_version"] = "research-only"
        factor_results["factor_name"] = factor_id
        factor_results["lookback"] = report["translation"].get("lookback", 1)
        factor_results = factor_results.dropna(subset=["value", "tradeable_ts"])
        scorecard = build_factor_scorecards(
            factor_results=factor_results,
            ohlcv=frame,
            factor_metadata=[{"factor_id": factor_id, "direction": "higher_is_better"}],
        )
        encoded = json.dumps(scorecard, sort_keys=True, allow_nan=False)
        (output_dir / "scorecard.json").write_text(encoded, encoding="utf-8")
        report["scorecard_digest"] = hashlib.sha256(encoded.encode()).hexdigest()
        report["status"] = (
            "research_candidate"
            if report["translation"]["status"] == "pass"
            and report["cost_reference"]["status"] != "fail"
            and report["batch_vs_causal_equal"]
            else "rejected"
        )
    elif review["status"] == "fail":
        report["status"] = "rejected"
    hypothesis = {
        "schema": "exploration_hypothesis/v1",
        "source_sha256": review["source_sha256"],
        "input_digest": review["input_digest"],
        "expression": expression,
        "search_attempt": True,
        "status": report["status"],
        "research_only": True,
    }
    (output_dir / "hypotheses.jsonl").write_text(json.dumps(hypothesis) + "\n", encoding="utf-8")
    trial = ResearchTrial.skipped(
        kind="factor_scorecard",
        subject=review["source_sha256"],
        universe=ohlcv.symbol.unique().tolist(),
        reason="exploration_scorecard_without_net_replay",
        source=VERSION,
        metadata={
            "run_id": digest(hypothesis),
            "hypothesis": hypothesis,
            "behavior_review_digest": review.get("review_digest"),
        },
    )
    TrialsLedger(output_dir).append(trial)
    report["trial_id"] = trial.trial_id
    report["receipt_digest"] = digest(report)
    (output_dir / "receipt.json").write_text(
        json.dumps(report, sort_keys=True, allow_nan=False), encoding="utf-8"
    )
    return report
