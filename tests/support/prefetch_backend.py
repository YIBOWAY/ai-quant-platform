"""One read-only history seam for the browser-routing diagnostic, never production."""

import os
from pathlib import Path

from fastapi.routing import APIRoute


def create_app():
    from quant_system.api.server import create_app as platform_app

    root = Path(os.environ["QS_DATA_DIR"]).resolve()
    if (
        os.environ.get("QS_ENVIRONMENT") != "test"
        or not (root / ".hermes-playwright-run-root.json").is_file()
    ):
        raise RuntimeError("Owned isolated E2E data root is required")
    app = platform_app()

    async def empty_history(ticker: str = "SPY"):
        return {
            "symbol": ticker,
            "ticker": ticker,
            "source": "e2e-unavailable",
            "frequency": "1d",
            "row_count": 0,
            "rows": [],
            "metadata": {
                "provider": "e2e-unavailable",
                "requested_provider": "futu",
                "fetched_at": None,
            },
        }

    app.router.routes.insert(
        0, APIRoute("/api/market-data/history", empty_history, methods=["GET"])
    )
    return app
