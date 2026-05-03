from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import numpy as np

from quant_system.prediction_market.backtest import PredictionMarketBacktestResult
from quant_system.prediction_market.timeseries_backtest import (
    PredictionMarketTimeseriesBacktestResult,
)


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


def write_prediction_market_timeseries_charts(
    *,
    result: PredictionMarketTimeseriesBacktestResult,
    output_dir: str | Path,
) -> dict:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    charts = [
        _write_daily_opportunity_chart(root / "daily_opportunities.png", result),
        _write_edge_histogram_png(root / "edge_distribution.png", result),
        _write_cumulative_profit_chart(root / "cumulative_estimated_profit.png", result),
        _write_sensitivity_heatmap(root / "parameter_sensitivity.png", result),
    ]
    index = {"charts": charts}
    (root / "chart_index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return index


def _write_daily_opportunity_chart(
    path: Path,
    result: PredictionMarketTimeseriesBacktestResult,
) -> dict:
    values = [item.opportunity_count for item in result.daily_summary] or [0]
    canvas = _chart_canvas()
    _draw_axes(canvas)
    _draw_bar_series(canvas, values, color=(88, 214, 141))
    _save_png(path, canvas)
    return {
        "name": "daily_opportunities",
        "path": path.name,
        "title": "Daily Opportunity Count",
    }


def _write_edge_histogram_png(
    path: Path,
    result: PredictionMarketTimeseriesBacktestResult,
) -> dict:
    values = [item.edge_bps for item in result.opportunities]
    if not values:
        buckets = [0]
    else:
        min_value = 0
        max_value = max(values)
        bucket_count = min(8, max(len(values), 1))
        bucket_width = max((max_value - min_value) / bucket_count, 1.0)
        counts = [0] * bucket_count
        for value in values:
            index = min(int((value - min_value) / bucket_width), bucket_count - 1)
            counts[index] += 1
        buckets = counts
    canvas = _chart_canvas()
    _draw_axes(canvas)
    _draw_bar_series(canvas, buckets, color=(255, 184, 77))
    _save_png(path, canvas)
    return {
        "name": "edge_distribution",
        "path": path.name,
        "title": "Edge Distribution Histogram",
    }


def _write_cumulative_profit_chart(
    path: Path,
    result: PredictionMarketTimeseriesBacktestResult,
) -> dict:
    values = [item.cumulative_estimated_profit for item in result.equity_curve] or [0.0]
    canvas = _chart_canvas()
    _draw_axes(canvas)
    _draw_line_series(canvas, values, color=(102, 179, 255))
    _save_png(path, canvas)
    return {
        "name": "cumulative_estimated_profit",
        "path": path.name,
        "title": "Cumulative Estimated Profit",
    }


def _write_sensitivity_heatmap(
    path: Path,
    result: PredictionMarketTimeseriesBacktestResult,
) -> dict:
    canvas = _chart_canvas()
    rows = [
        [item.opportunity_count for item in result.sensitivity],
        [item.simulated_trade_count for item in result.sensitivity],
        [item.cumulative_estimated_profit for item in result.sensitivity],
    ]
    _draw_heatmap(canvas, rows)
    _save_png(path, canvas)
    return {
        "name": "parameter_sensitivity",
        "path": path.name,
        "title": "Parameter Sensitivity Heatmap",
    }


def _chart_canvas(width: int = 640, height: int = 360) -> np.ndarray:
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    canvas[:, :] = np.array([14, 21, 17], dtype=np.uint8)
    return canvas


def _draw_axes(canvas: np.ndarray) -> None:
    height, width, _ = canvas.shape
    canvas[40:42, 48 : width - 32] = np.array([52, 66, 58], dtype=np.uint8)
    canvas[40 : height - 44, 48:50] = np.array([52, 66, 58], dtype=np.uint8)
    canvas[height - 44 : height - 42, 48 : width - 32] = np.array(
        [52, 66, 58],
        dtype=np.uint8,
    )


def _draw_bar_series(
    canvas: np.ndarray,
    values: list[float],
    *,
    color: tuple[int, int, int],
) -> None:
    height, width, _ = canvas.shape
    plot_left, plot_right = 60, width - 40
    plot_top, plot_bottom = 56, height - 56
    span = max(len(values), 1)
    bar_width = max((plot_right - plot_left) // (span * 2), 8)
    max_value = max(values, default=1) or 1
    for index, value in enumerate(values):
        x0 = plot_left + index * ((plot_right - plot_left) // span) + 8
        x1 = min(x0 + bar_width, plot_right)
        scaled = 0 if max_value == 0 else int((value / max_value) * (plot_bottom - plot_top))
        y0 = plot_bottom - scaled
        canvas[y0:plot_bottom, x0:x1] = np.array(color, dtype=np.uint8)


def _draw_line_series(
    canvas: np.ndarray,
    values: list[float],
    *,
    color: tuple[int, int, int],
) -> None:
    height, width, _ = canvas.shape
    plot_left, plot_right = 60, width - 40
    plot_top, plot_bottom = 56, height - 56
    max_value = max(values, default=1.0)
    min_value = min(values, default=0.0)
    span = max(max_value - min_value, 1e-9)
    if len(values) == 1:
        y = plot_bottom - int(((values[0] - min_value) / span) * (plot_bottom - plot_top))
        canvas[max(y - 1, 0) : min(y + 2, height), plot_left:plot_left + 4] = np.array(
            color,
            dtype=np.uint8,
        )
        return
    points = []
    for index, value in enumerate(values):
        x = plot_left + int(index * ((plot_right - plot_left) / max(len(values) - 1, 1)))
        y = plot_bottom - int(((value - min_value) / span) * (plot_bottom - plot_top))
        points.append((x, y))
    for start, end in zip(points, points[1:], strict=False):
        _draw_line(canvas, start, end, color=color)


def _draw_heatmap(canvas: np.ndarray, rows: list[list[float]]) -> None:
    height, width, _ = canvas.shape
    plot_left, plot_right = 60, width - 40
    plot_top, plot_bottom = 56, height - 56
    row_count = len(rows)
    col_count = max((len(row) for row in rows), default=1)
    all_values = [value for row in rows for value in row] or [0.0]
    min_value = min(all_values)
    max_value = max(all_values)
    span = max(max_value - min_value, 1e-9)
    cell_width = max((plot_right - plot_left) // col_count, 24)
    cell_height = max((plot_bottom - plot_top) // row_count, 24)
    for row_index, row in enumerate(rows):
        for col_index, value in enumerate(row):
            intensity = (value - min_value) / span if span else 0.0
            color = np.array(
                [
                    int(40 + 180 * intensity),
                    int(70 + 120 * (1 - intensity)),
                    int(90 + 120 * intensity),
                ],
                dtype=np.uint8,
            )
            x0 = plot_left + col_index * cell_width
            y0 = plot_top + row_index * cell_height
            canvas[y0 : y0 + cell_height - 4, x0 : x0 + cell_width - 4] = color


def _draw_line(
    canvas: np.ndarray,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    color: tuple[int, int, int],
) -> None:
    x0, y0 = start
    x1, y1 = end
    steps = max(abs(x1 - x0), abs(y1 - y0), 1)
    for step in range(steps + 1):
        x = int(x0 + ((x1 - x0) * step / steps))
        y = int(y0 + ((y1 - y0) * step / steps))
        canvas[
            max(y - 1, 0) : min(y + 2, canvas.shape[0]),
            max(x - 1, 0) : min(x + 2, canvas.shape[1]),
        ] = np.array(color, dtype=np.uint8)


def _save_png(path: Path, canvas: np.ndarray) -> None:
    height, width, channels = canvas.shape
    if channels != 3:
        raise ValueError("expected an RGB canvas")
    raw = b"".join(b"\x00" + canvas[row].tobytes() for row in range(height))
    compressed = zlib.compress(raw, level=9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack("!I", len(data))
            + tag
            + data
            + struct.pack("!I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    payload = b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            chunk(
                b"IHDR",
                struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0),
            ),
            chunk(b"IDAT", compressed),
            chunk(b"IEND", b""),
        ]
    )
    path.write_bytes(payload)
