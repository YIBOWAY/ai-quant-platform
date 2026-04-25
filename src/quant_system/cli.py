from __future__ import annotations

import json
from typing import Any

import typer

from quant_system import __version__
from quant_system.config.settings import load_settings
from quant_system.logging.setup import configure_logging

_SECRET_FIELDS: frozenset[str] = frozenset({"manual_live_trading_confirmation"})

app = typer.Typer(
    help="AI quant research, backtesting, and paper-trading platform CLI.",
    no_args_is_help=True,
)
config_app = typer.Typer(help="Inspect local configuration.")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        callback=_version_callback,
        is_eager=True,
        help="Show package version and exit.",
    ),
) -> None:
    """Run platform utility commands."""


def _mask_secrets(payload: Any) -> Any:
    """Recursively replace sensitive fields with a non-revealing marker."""
    if isinstance(payload, dict):
        return {
            key: (
                ("<set>" if value else "<unset>")
                if key in _SECRET_FIELDS
                else _mask_secrets(value)
            )
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [_mask_secrets(item) for item in payload]
    return payload


@config_app.command("show")
def show_config() -> None:
    """Print the effective local settings as JSON, with secrets masked."""
    settings = load_settings()
    masked = _mask_secrets(settings.model_dump(mode="json"))
    typer.echo(json.dumps(masked, indent=2, sort_keys=True))


@app.command()
def doctor() -> None:
    """Run a lightweight Phase 0 health check."""
    settings = load_settings()
    configure_logging(settings.log_level)

    live_state = (
        "live trading enabled"
        if settings.safety.live_trading_enabled
        else "live trading disabled"
    )
    typer.echo("Phase 0 foundation is available")
    typer.echo(f"Safety mode: dry_run={settings.safety.dry_run}, {live_state}")
    typer.echo(f"Environment: {settings.environment}")


app.add_typer(config_app, name="config")


if __name__ == "__main__":
    app()
