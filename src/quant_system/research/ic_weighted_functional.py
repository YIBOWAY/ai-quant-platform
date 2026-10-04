"""Pure diagnostic building blocks for mean sessionwise Pearson IC.

The caller supplies one frozen factor/horizon panel and its complete signal
calendar. Weights change the empirical measure, never rows, labels or dates.
No joint standard error, significance, model approval or funding is computed.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


class ICInputError(ValueError):
    """An explicit invalid input or degenerate resampling realization."""


def _require(condition, reason):
    if not condition:
        raise ICInputError(reason)


def _diagnostic(**payload):
    return {
        **payload,
        "method_role": "candidate_method_diagnostic",
        "joint_cluster_se": None,
        "joint_cluster_status": "not_evaluated",
        "significance_computed": False,
        "admission_authority": False,
        "funding_authority": False,
    }


@dataclass(frozen=True)
class ICPanel:
    """Prepared arrays are copied and read-only; clustering IDs remain unqualified."""

    dates: tuple[str, ...]
    entities: tuple[str, ...]
    symbols: tuple[str, ...]
    date_codes: np.ndarray
    entity_codes: np.ndarray
    x: np.ndarray
    y: np.ndarray
    eligible: np.ndarray
    valid_dates: np.ndarray
    input_digest: str
    method_role: str = field(default="candidate_method_diagnostic", init=False)
    joint_cluster_se: None = field(default=None, init=False)
    joint_cluster_status: str = field(default="not_evaluated", init=False)
    significance_computed: bool = field(default=False, init=False)
    admission_authority: bool = field(default=False, init=False)
    funding_authority: bool = field(default=False, init=False)


def _readonly(values):
    array = np.array(values, copy=True)
    array.flags.writeable = False
    return array


def _date_key(value):
    stamp = pd.Timestamp(value)
    _require(not pd.isna(stamp), "ic_date_missing")
    return (
        stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    ).isoformat()


def _moments(x, y, weights):
    positive = weights > 0
    _require(int(positive.sum()) >= 2, "ic_weighted_sample_too_small")
    total = float(weights.sum())
    _require(math.isfinite(total) and total > 0, "ic_weight_total_invalid")
    # Keep zero-weight excluded observations out of arithmetic, including NaN.
    x, y, probability = x[positive], y[positive], weights[positive] / total
    dx = x - float(probability @ x)
    dy = y - float(probability @ y)
    vx, vy = float(probability @ (dx * dx)), float(probability @ (dy * dy))
    _require(
        math.isfinite(vx) and math.isfinite(vy) and vx > 0 and vy > 0, "ic_zero_or_invalid_scale"
    )
    zx, zy = dx / math.sqrt(vx), dy / math.sqrt(vy)
    correlation = float(probability @ (zx * zy))
    _require(math.isfinite(correlation) and abs(correlation) <= 1 + 1e-12, "ic_invalid_correlation")
    return correlation, zx, zy


def prepare_panel(frame: pd.DataFrame, *, signal_calendar) -> ICPanel:
    """Preserve zero-eligible date holes; reject other original degeneracies.

    One eligible row or zero within-date scale is an error, not a dropped date.
    Existing excluded rows remain outside the calculation even if numeric.
    entry_ts and return_end_ts are verified and hashed, never recomputed.
    """
    names = [
        "symbol",
        "entity_id",
        "signal_ts",
        "entry_ts",
        "return_end_ts",
        "value",
        "forward_return",
        "eligible",
    ]
    _require(
        not frame.columns.duplicated().any() and set(names).issubset(frame), "ic_columns_invalid"
    )
    data = frame[names].copy(deep=True)
    _require(len(data) > 0, "ic_empty_panel")
    cell_identity = {}
    for name in ("factor_id", "horizon"):
        if name in frame:
            _require(
                frame[name].notna().all() and frame[name].nunique() == 1,
                "ic_one_factor_horizon_required",
            )
            value = frame[name].iloc[0]
            value = value.item() if isinstance(value, np.generic) else value
            _require(
                isinstance(value, str) and bool(value.strip())
                if name == "factor_id"
                else type(value) is int and value > 0,
                "ic_cell_identity_invalid",
            )
            cell_identity[name] = value
    for name in ("symbol", "entity_id"):
        _require(
            data[name].map(lambda v: isinstance(v, str) and bool(v.strip())).all(),
            "ic_identifier_invalid",
        )
    _require(
        pd.api.types.is_bool_dtype(data.eligible.dtype) and data.eligible.notna().all(),
        "ic_eligibility_not_boolean",
    )
    for name in ("value", "forward_return"):
        _require(
            pd.api.types.is_numeric_dtype(data[name])
            and not pd.api.types.is_bool_dtype(data[name]),
            "ic_non_numeric_value",
        )
    for name in ("signal_ts", "entry_ts", "return_end_ts"):
        data[name] = pd.to_datetime(data[name], utc=True, errors="raise")
    _require(data.signal_ts.notna().all(), "ic_signal_date_missing")
    _require(not data.duplicated(["symbol", "signal_ts"]).any(), "ic_duplicate_security_date")
    calendar = pd.DatetimeIndex(pd.to_datetime(signal_calendar, utc=True, errors="raise"))
    _require(
        len(calendar) > 0
        and not calendar.hasnans
        and not calendar.has_duplicates
        and calendar.is_monotonic_increasing,
        "ic_calendar_invalid",
    )
    data = data.sort_values(["signal_ts", "symbol"], ignore_index=True)
    date_codes = calendar.get_indexer(data.signal_ts)
    _require((date_codes >= 0).all(), "ic_signal_outside_calendar")
    eligible = data.eligible.to_numpy(dtype=bool)
    x = data.value.to_numpy(dtype=float, na_value=np.nan)
    y = data.forward_return.to_numpy(dtype=float, na_value=np.nan)
    _require(not np.isinf(x).any() and not np.isinf(y).any(), "ic_infinite_input")
    _require(
        (np.isfinite(x[eligible]) & np.isfinite(y[eligible])).all(), "ic_eligible_pair_missing"
    )
    _require(
        ((data.entry_ts > data.signal_ts) & (data.return_end_ts > data.entry_ts))[eligible].all(),
        "ic_label_time_invalid",
    )
    entities = tuple(sorted(data.entity_id.unique()))
    entity_codes = pd.Index(entities).get_indexer(data.entity_id)
    valid = np.zeros(len(calendar), dtype=bool)
    for index in range(len(calendar)):
        mask = eligible & (date_codes == index)
        if mask.any():
            _moments(x[mask], y[mask], np.ones(int(mask.sum())))
            valid[index] = True
    _require(valid.any(), "ic_no_effective_dates")
    records = []
    for row in data.itertuples(index=False):
        records.append(
            [
                row.symbol,
                row.entity_id,
                row.signal_ts.isoformat(),
                None if pd.isna(row.entry_ts) else row.entry_ts.isoformat(),
                None if pd.isna(row.return_end_ts) else row.return_end_ts.isoformat(),
                None if pd.isna(row.value) else float(row.value),
                None if pd.isna(row.forward_return) else float(row.forward_return),
                bool(row.eligible),
            ]
        )
    dates = tuple(day.isoformat() for day in calendar)
    identity = hashlib.sha256(
        json.dumps(
            {"cell": cell_identity, "dates": dates, "rows": records},
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return ICPanel(
        dates,
        entities,
        tuple(data.symbol),
        _readonly(date_codes),
        _readonly(entity_codes),
        _readonly(x),
        _readonly(y),
        _readonly(eligible),
        _readonly(valid),
        identity,
    )


def _weights(value, keys, *, dates=False):
    if value is None:
        return np.ones(len(keys))
    _require(isinstance(value, Mapping), "ic_weights_not_mapping")
    normalized = {_date_key(k) if dates else k: v for k, v in value.items()}
    _require(
        len(normalized) == len(value) and set(normalized) == set(keys), "ic_weight_keys_mismatch"
    )
    _require(
        all(
            isinstance(v, (int, float, np.integer, np.floating))
            and not isinstance(v, (bool, np.bool_))
            and math.isfinite(float(v))
            and float(v) >= 0
            for v in normalized.values()
        ),
        "ic_weights_invalid",
    )
    result = np.array([normalized[k] for k in keys], dtype=float)
    _require(math.isfinite(float(result.sum())) and result.sum() > 0, "ic_weight_total_invalid")
    return result


def weighted_ic(panel: ICPanel, *, entity_weights=None, date_weights=None):
    """Evaluate F(w,v); the original valid-date set cannot change under weights."""
    ew = _weights(entity_weights, panel.entities)
    dw = _weights(date_weights, panel.dates, dates=True)
    denominator = float(dw[panel.valid_dates].sum())
    _require(math.isfinite(denominator) and denominator > 0, "ic_no_weighted_effective_dates")
    values = np.full(len(panel.dates), np.nan)
    counts = []
    for index, _day in enumerate(panel.dates):
        mask = panel.eligible & (panel.date_codes == index)
        counts.append(int(mask.sum()))
        if panel.valid_dates[index]:
            # Verify even a zero-time-weight valid date; no silent date dropping.
            values[index], _, _ = _moments(
                panel.x[mask], panel.y[mask], ew[panel.entity_codes[mask]]
            )
    mean = float(dw[panel.valid_dates] @ values[panel.valid_dates] / denominator)
    return _diagnostic(
        evaluation_status="evaluated",
        input_digest=panel.input_digest,
        mean_ic=mean,
        effective_dates=int(panel.valid_dates.sum()),
        calendar_slots=len(panel.dates),
        entity_weight_semantics="caller_supplied_clusters_not_certified_independent_issuers",
        daily=[
            {"signal_ts": day, "ic": None if np.isnan(value) else float(value), "n_original": count}
            for day, value, count in zip(panel.dates, values, counts, strict=True)
        ],
    )


def analytic_contributions(panel: ICPanel):
    """Unit-weight derivatives only; no sum of entity/time variances is formed."""
    base = weighted_ic(panel)
    count = int(panel.valid_dates.sum())
    entity = np.zeros(len(panel.entities))
    time = np.zeros(len(panel.dates))
    psi_rows, psi_sums = [], []
    for index, day in enumerate(panel.dates):
        positions = np.flatnonzero(panel.eligible & (panel.date_codes == index))
        if not panel.valid_dates[index]:
            psi_sums.append(None)
            continue
        r, zx, zy = _moments(panel.x[positions], panel.y[positions], np.ones(len(positions)))
        psi = zx * zy - r * (zx * zx + zy * zy) / 2
        np.add.at(entity, panel.entity_codes[positions], psi / (count * len(positions)))
        time[index] = (r - base["mean_ic"]) / count
        psi_sums.append(float(psi.sum()))
        psi_rows.extend(
            {
                "symbol": panel.symbols[p],
                "entity_id": panel.entities[panel.entity_codes[p]],
                "signal_ts": day,
                "psi": float(value),
            }
            for p, value in zip(positions, psi, strict=True)
        )
    return _diagnostic(
        evaluation_status="evaluated",
        input_digest=panel.input_digest,
        mean_ic=base["mean_ic"],
        entity_derivatives=dict(zip(panel.entities, entity.tolist(), strict=True)),
        date_derivatives=dict(zip(panel.dates, time.tolist(), strict=True)),
        psi_sums_by_original_date=psi_sums,
        psi_rows=psi_rows,
        interpretation="derivatives_of_weighted_statistic_not_joint_sampling_variance",
    )


def draw_resample_weights(
    panel: ICPanel,
    *,
    seed: int,
    block_length: int,
    resample_entities: bool = True,
    resample_time: bool = True,
):
    """One circular-block draw over the FULL date axis, shared by all entities.

    Block length is a caller-frozen diagnostic parameter, not a validated choice.
    Labels remain stored at their original dates; no pseudo-price path is built.
    Entity and time draws use independent sub-streams so the time blocks for one
    seed stay identical across entity populations and toggles (paired comparisons
    need that stability).
    """
    _require(type(seed) is int and seed >= 0, "ic_seed_invalid")
    size = len(panel.dates)
    _require(type(block_length) is int and 1 <= block_length <= size, "ic_block_length_invalid")
    _require(
        type(resample_entities) is bool and type(resample_time) is bool,
        "ic_resampling_flag_invalid",
    )
    rng_entities = np.random.default_rng([seed, 0])
    rng_time = np.random.default_rng([seed, 1])
    ids = (
        rng_entities.integers(len(panel.entities), size=len(panel.entities))
        if resample_entities
        else np.arange(len(panel.entities))
    )
    entity = np.bincount(ids, minlength=len(panel.entities))
    if resample_time:
        starts = rng_time.integers(size, size=math.ceil(size / block_length))
        indices = ((starts[:, None] + np.arange(block_length)) % size).ravel()[:size]
    else:
        starts, indices = np.array([], dtype=int), np.arange(size)
    dates = np.bincount(indices, minlength=size)
    return _diagnostic(
        input_digest=panel.input_digest,
        seed=seed,
        block_length=block_length,
        entity_weights=dict(zip(panel.entities, entity.tolist(), strict=True)),
        date_weights=dict(zip(panel.dates, dates.tolist(), strict=True)),
        entity_draw_indices=ids.tolist(),
        date_draw_indices=indices.tolist(),
        block_start_indices=starts.tolist(),
        time_draw_shared_by_all_entities=True,
        labels_reconstructed=False,
        block_length_validated=False,
    )


def resample_ic(
    panel: ICPanel,
    *,
    seed: int,
    block_length: int,
    resample_entities: bool = True,
    resample_time: bool = True,
):
    """Attempt one draw and retain a degenerate outcome; never redraw to get success.

    Aggregation contract: report rejection frequency as rejected / attempted.
    A rejected draw has no numeric IC and must not be imputed as zero or added
    to a variance denominator. Variance over only successful draws describes a
    conditional distribution; it is not an unconditional uncertainty estimate.
    A future inference harness must preregister and calibrate degeneracy handling
    before using these draws for variance, coverage or significance claims.
    """
    draw = draw_resample_weights(
        panel,
        seed=seed,
        block_length=block_length,
        resample_entities=resample_entities,
        resample_time=resample_time,
    )
    try:
        result = weighted_ic(
            panel, entity_weights=draw["entity_weights"], date_weights=draw["date_weights"]
        )
    except ICInputError as exc:
        return _diagnostic(
            evaluation_status="rejected",
            reason=str(exc),
            attempted_draws=1,
            rejected_draws=1,
            draw=draw,
        )
    return _diagnostic(
        evaluation_status="evaluated", attempted_draws=1, rejected_draws=0, draw=draw, result=result
    )
