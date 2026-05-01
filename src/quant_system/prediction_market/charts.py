from __future__ import annotations

import json
from pathlib import Path

from quant_system.prediction_market.backtest import PredictionMarketBacktestResult


def write_prediction_market_charts(
    *,
    result: PredictionMarketBacktestResult,
    output_dir: str | Path,
) -> dict:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    charts = [
        _write_bar_chart(
            root / "opportunity_count.svg",
            "Opportunity Count",
            [("opportunities", result.metrics.opportunity_count)],
        ),
        _write_histogram(root / "edge_histogram.svg", result),
        _write_line_chart(root / "cumulative_estimated_edge.svg", result),
        _write_sensitivity(root / "parameter_sensitivity.svg", result),
    ]
    index = {"charts": charts}
    (root / "chart_index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return index


def _write_bar_chart(path: Path, title: str, values: list[tuple[str, float]]) -> dict:
    max_value = max((value for _, value in values), default=1) or 1
    bars = []
    for index, (label, value) in enumerate(values):
        height = 120 * (value / max_value)
        x = 40 + index * 90
        y = 160 - height
        bars.append(f'<rect x="{x}" y="{y:.2f}" width="48" height="{height:.2f}" fill="#58d68d" />')
        bars.append(f'<text x="{x}" y="182" font-size="10" fill="#dce7df">{label}</text>')
        bars.append(
            f'<text x="{x}" y="{y - 6:.2f}" font-size="10" fill="#dce7df">'
            f"{value:.2f}</text>"
        )
    _write_svg(path, title, "\n".join(bars))
    return {"name": "opportunity_count", "path": path.name, "title": title}


def _write_histogram(path: Path, result: PredictionMarketBacktestResult) -> dict:
    values = [item.net_edge_bps for item in result.opportunities]
    if not values:
        values = [0]
    bucket_size = 250
    buckets: dict[str, int] = {}
    for value in values:
        bucket = int(value // bucket_size) * bucket_size
        label = f"{bucket}-{bucket + bucket_size}"
        buckets[label] = buckets.get(label, 0) + 1
    _write_bar_chart(path, "Edge Distribution", list(buckets.items()))
    return {"name": "edge_histogram", "path": path.name, "title": "Edge Distribution"}


def _write_line_chart(path: Path, result: PredictionMarketBacktestResult) -> dict:
    points = result.equity_curve
    max_value = max((point.cumulative_estimated_edge for point in points), default=1) or 1
    if not points:
        polyline = ""
    else:
        coords = []
        for index, point in enumerate(points):
            x = 40 + index * (220 / max(len(points) - 1, 1))
            y = 160 - 120 * (point.cumulative_estimated_edge / max_value)
            coords.append(f"{x:.2f},{y:.2f}")
        polyline = (
            f'<polyline points="{" ".join(coords)}" fill="none" '
            'stroke="#58d68d" stroke-width="3" />'
        )
    _write_svg(path, "Cumulative Estimated Edge", polyline)
    return {
        "name": "cumulative_estimated_edge",
        "path": path.name,
        "title": "Cumulative Estimated Edge",
    }


def _write_sensitivity(path: Path, result: PredictionMarketBacktestResult) -> dict:
    base = result.config.min_edge_bps
    values = []
    for multiplier in [0.5, 1.0, 1.5, 2.0]:
        threshold = base * multiplier
        count = sum(1 for item in result.opportunities if item.edge_bps >= threshold)
        values.append((f"{threshold:.0f}bps", count))
    _write_bar_chart(path, "Sensitivity by Min Edge", values)
    return {
        "name": "parameter_sensitivity",
        "path": path.name,
        "title": "Sensitivity by Min Edge",
    }


def _write_svg(path: Path, title: str, body: str) -> None:
    path.write_text(
        "\n".join(
            [
                '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="220" '
                'viewBox="0 0 320 220">',
                '<rect width="320" height="220" fill="#0e1511" />',
                f'<text x="20" y="26" font-size="16" fill="#f1f5f9">{title}</text>',
                '<line x1="32" y1="170" x2="288" y2="170" stroke="#34423a" />',
                '<line x1="32" y1="40" x2="32" y2="170" stroke="#34423a" />',
                body,
                "</svg>",
            ]
        ),
        encoding="utf-8",
    )
