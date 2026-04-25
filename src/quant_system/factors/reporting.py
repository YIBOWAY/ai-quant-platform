from __future__ import annotations

import pandas as pd


def _format_timestamp(value: object) -> str:
    if pd.isna(value):
        return "n/a"
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _safe_mean(series: pd.Series) -> float:
    value = series.dropna().mean()
    return float(value) if pd.notna(value) else float("nan")


def _nunique_or_zero(frame: pd.DataFrame, column: str) -> int:
    if column not in frame.columns:
        return 0
    return int(frame[column].nunique())


def generate_factor_report(
    *,
    factor_results: pd.DataFrame,
    signal_frame: pd.DataFrame,
    ic_frame: pd.DataFrame,
    quantile_frame: pd.DataFrame,
    title: str = "Phase 2 Factor Report",
) -> str:
    lines: list[str] = [f"# {title}", ""]
    lines.extend(
        [
            "## Scope",
            "",
            "This report evaluates research factors only. It does not place orders and "
            "does not represent live-trading readiness.",
            "",
        ]
    )

    if factor_results.empty:
        lines.extend(["## Summary", "", "No factor rows were generated.", ""])
        return "\n".join(lines)

    factor_names = (
        factor_results.loc[:, ["factor_id", "factor_name"]]
        .drop_duplicates()
        .sort_values("factor_id")
    )
    lines.extend(
        [
            "## Summary",
            "",
            f"- Factor rows: {len(factor_results)}",
            f"- Signal rows: {len(signal_frame)}",
            f"- Symbols: {_nunique_or_zero(factor_results, 'symbol')}",
            f"- First signal: {_format_timestamp(factor_results['signal_ts'].min())}",
            f"- Last signal: {_format_timestamp(factor_results['signal_ts'].max())}",
            "",
            "## Factors",
            "",
        ]
    )
    for row in factor_names.itertuples(index=False):
        lines.append(f"- {row.factor_id}: {row.factor_name}")
    lines.append("")

    lines.extend(["## Information Coefficient", ""])
    if ic_frame.empty:
        lines.extend(
            [
                "No IC rows were available. This usually means the universe is too small.",
                "",
            ]
        )
    else:
        summary = (
            ic_frame.groupby("factor_id", as_index=False)
            .agg(
                mean_ic=("ic", _safe_mean),
                mean_rank_ic=("rank_ic", _safe_mean),
                periods=("ic", "count"),
            )
            .sort_values("factor_id")
        )
        lines.extend(
            [
                "| factor_id | mean_ic | mean_rank_ic | periods |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for row in summary.itertuples(index=False):
            lines.append(
                f"| {row.factor_id} | {row.mean_ic:.6f} | {row.mean_rank_ic:.6f} | "
                f"{row.periods} |"
            )
        lines.append("")

    lines.extend(["## Quantile Returns", ""])
    if quantile_frame.empty:
        lines.extend(
            [
                "No quantile rows were available. Use more symbols or a longer sample window.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "| factor_id | quantile | mean_forward_return | count |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for row in quantile_frame.itertuples(index=False):
            count = getattr(row, "count", 0)
            lines.append(
                f"| {row.factor_id} | {row.quantile} | {row.mean_forward_return:.6f} | "
                f"{count} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Bias Controls",
            "",
            "- Factor values are stamped with `signal_ts`.",
            "- Actionable rows use the next available bar as `tradeable_ts`.",
            "- Evaluation joins factor values to forward returns only after factor computation.",
            "- The last bar per symbol is excluded from actionable signals because no next "
            "bar exists.",
            "",
        ]
    )
    return "\n".join(lines)
