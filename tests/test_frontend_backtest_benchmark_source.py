from pathlib import Path


def test_backtest_pages_render_benchmark_source_badge() -> None:
    list_page = Path("src/frontend/app/backtest/page.tsx").read_text(encoding="utf-8")
    detail_page = Path("src/frontend/app/backtest/[runId]/page.tsx").read_text(
        encoding="utf-8"
    )

    assert "benchmark?.source ? <DataSourceBadge source={benchmark.source} /> : null" in list_page
    assert "benchmark?.source ? <DataSourceBadge source={benchmark.source} /> : null" in detail_page


def test_backtest_detail_page_uses_persisted_benchmark_from_detail_response() -> None:
    list_page = Path("src/frontend/app/backtest/page.tsx").read_text(encoding="utf-8")
    detail_page = Path("src/frontend/app/backtest/[runId]/page.tsx").read_text(
        encoding="utf-8"
    )

    assert "getBenchmark" not in list_page
    assert "getBenchmark" not in detail_page
    assert "const benchmark = detail?.benchmark ?? null" in list_page
    assert "const benchmark = detail.benchmark" in detail_page
