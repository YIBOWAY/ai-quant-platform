from __future__ import annotations

from pathlib import Path
from typing import Any

from quant_system.config.settings import Settings, reload_settings


def build_services(
    *,
    settings: Settings | None = None,
    output_dir: str | Path | None = None,
    bind_address: str = "127.0.0.1",
) -> dict[str, Any]:
    """Build the small app-state payload shared by Phase 9 routes.

    Phase 9 intentionally keeps this thin: construct settings, resolve paths,
    and expose them via ``app.state``. Existing Phase 1-8 functions remain the
    source of business logic.
    """

    active_settings = settings or reload_settings()
    base_dir = Path(output_dir) if output_dir is not None else active_settings.data.data_dir
    return {
        "settings": active_settings,
        "bind_address": bind_address,
        "output_dir": base_dir,
        "api_runs_dir": base_dir / "api_runs",
    }
