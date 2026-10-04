from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

from typer.testing import CliRunner

from quant_system.d34 import cli as d34_cli

runner = CliRunner()


def _install(
    monkeypatch,
    *,
    paper_enabled: bool,
    cycle_result=None,
    emergency_active: bool = False,
    signal_statuses: list[str] | None = None,
) -> dict:
    calls = {"cycle": 0, "mandate": 0, "jobs": 0, "docker": 0}

    class _Boom:
        def __init__(self, *args, **kwargs):
            raise AssertionError("paper-cycle must not touch research authorities")

    monkeypatch.setattr(
        d34_cli,
        "observe_paper_emergency_stop",
        lambda *_args, **_kwargs: {
            "active": paper_enabled is False and emergency_active,
            "reason": None,
            "created_at": None,
        },
    )
    # cli.py no longer imports the mandate authority at all; keep the tripwire
    # so a future re-introduction on the paper-cycle path still fails.
    monkeypatch.setattr(d34_cli, "PostgresMandateAuthority", _Boom, raising=False)
    monkeypatch.setattr(d34_cli, "PostgresJobAuthority", _Boom, raising=False)
    monkeypatch.setattr(d34_cli, "PostgresRegistryAuthority", _Boom, raising=False)
    monkeypatch.setattr(d34_cli, "D34DockerRuntime", _Boom, raising=False)
    monkeypatch.setattr(
        d34_cli,
        "build_paper_account_repository",
        lambda *args, **kwargs: object(),
    )

    class _SleeveStorage:
        def list_sleeves(self):
            return (
                [
                    SimpleNamespace(
                        sleeve_id="sleeve-test",
                        status=SimpleNamespace(value="running"),
                        metadata={
                            "automation_managed": True,
                            "automation_source": "d34",
                        },
                    )
                ]
                if signal_statuses
                else []
            )

        def load_signals(self, sleeve_id):
            assert sleeve_id == "sleeve-test"
            signal_date = datetime.now().astimezone().date().isoformat()
            return [
                SimpleNamespace(
                    signal_date=signal_date,
                    status=SimpleNamespace(value=status),
                )
                for status in signal_statuses or []
            ]

    monkeypatch.setattr(
        d34_cli, "PaperStrategySleeveStorage", lambda *args, **kwargs: _SleeveStorage()
    )
    monkeypatch.setattr(d34_cli, "PaperPriceSource", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        d34_cli,
        "PaperStrategyOperationsRunner",
        lambda **kwargs: object(),
    )

    def fake_cycle(*, now, sleeve_storage, runner):
        calls["cycle"] += 1
        return cycle_result or {
            "sleeves_checked": 1,
            "signals_generated": 1,
            "executions_created": 1,
            "executions_processed": 1,
            "executions_filled": 0,
            "executions_blocked": 0,
        }

    monkeypatch.setattr(d34_cli, "run_d34_paper_cycle", fake_cycle)
    import pathlib

    fake_settings = SimpleNamespace(
        data=SimpleNamespace(data_dir=pathlib.Path("/tmp/test-d34-paper-cycle")),
        safety=SimpleNamespace(
            paper_trading=True,
            live_trading_enabled=False,
            paper_observation_enabled=paper_enabled,
        ),
    )
    monkeypatch.setattr(d34_cli, "load_settings", lambda: fake_settings)
    return calls


def test_paper_cycle_runs_cycle_and_emits_receipt(monkeypatch) -> None:
    calls = _install(monkeypatch, paper_enabled=True)

    result = runner.invoke(d34_cli.d34_app, ["paper-cycle"])

    assert result.exit_code == 0, result.output
    receipt = json.loads(result.output.strip().splitlines()[-1])
    assert receipt["contract"] == "hqa.d34_paper_cycle/v1"
    assert receipt["status"] == "ok"
    assert receipt["trading"]["sleeves_checked"] == 1
    assert receipt["gate"]["paper_trading"] is True
    assert receipt["gate"]["live_trading_enabled"] is False
    assert receipt["gate"]["paper_observation_enabled"] is True
    assert receipt["gate"]["emergency_stop_active"] is False
    assert receipt["gate"]["research_factory_gate"] == "ignored_by_design"
    assert calls["cycle"] == 1


def test_paper_cycle_receipt_surfaces_data_unavailable_signal(monkeypatch) -> None:
    calls = _install(
        monkeypatch,
        paper_enabled=True,
        cycle_result={
            "sleeves_checked": 1,
            "signals_generated": 1,
            "executions_created": 0,
            "executions_processed": 0,
            "executions_filled": 0,
            "executions_blocked": 0,
        },
        signal_statuses=["data_unavailable"],
    )

    result = runner.invoke(d34_cli.d34_app, ["paper-cycle"])

    assert result.exit_code == 0, result.output
    receipt = json.loads(result.output.strip().splitlines()[-1])
    assert receipt["calendar_ran"] is True
    assert receipt["status"] == "data_unavailable"
    assert receipt["signal_outcomes"] == {
        "data_unavailable": 1,
        "generated": 0,
        "invalid": 0,
        "read_failed": 0,
        "provider_error_codes": [],
    }
    assert receipt["trading"]["signals_generated"] == 1
    assert receipt["trading"]["executions_created"] == 0
    assert calls["cycle"] == 1


def test_paper_cycle_receipt_keeps_partial_sleeve_failure_visible(monkeypatch):
    _install(
        monkeypatch,
        paper_enabled=True,
        cycle_result={
            "sleeves_checked": 2,
            "signals_generated": 1,
            "executions_created": 1,
            "executions_processed": 0,
            "executions_filled": 0,
            "executions_blocked": 0,
            "sleeves_failed": 1,
            "sleeve_errors": [
                {
                    "sleeve_id": "broken",
                    "stage": "signal",
                    "code": "strategy_algorithm_source_mismatch",
                }
            ],
        },
    )
    result = runner.invoke(d34_cli.d34_app, ["paper-cycle"])
    assert result.exit_code == 0, result.output
    receipt = json.loads(result.output.strip().splitlines()[-1])
    assert receipt["status"] == "partial_failed"
    assert receipt["trading"]["sleeves_failed"] == 1
    assert receipt["trading"]["executions_created"] == 1


def test_signal_receipt_read_failure_is_isolated_and_reported():
    class MixedStorage:
        def list_sleeves(self):
            return [
                SimpleNamespace(
                    sleeve_id=identifier,
                    status="running",
                    metadata={"automation_managed": True, "automation_source": "d34"},
                )
                for identifier in ["broken", "healthy"]
            ]

        def load_signals(self, sleeve_id):
            if sleeve_id == "broken":
                raise ValueError("broken signal file")
            return [SimpleNamespace(signal_date="2026-09-11", status="generated")]

    counts = d34_cli._paper_cycle_signal_outcomes(
        MixedStorage(),
        signal_date="2026-09-11",
    )
    assert counts["generated"] == 1
    assert counts["read_failed"] == 1


def test_dry_run_emits_plan_and_skips_live_cycle(monkeypatch) -> None:
    calls = _install(monkeypatch, paper_enabled=True)
    planned = {"called": 0}

    def fake_plan(**kwargs):
        planned["called"] += 1
        assert kwargs["dry_run"] is True
        return {
            "contract": "hqa.d34_paper_cycle_plan/v1",
            "dry_run": True,
            "signal_window_open": True,
            "execution_window_open": False,
            "would_write": False,
        }

    monkeypatch.setattr(d34_cli, "plan_d34_paper_cycle", fake_plan)
    monkeypatch.setattr(d34_cli, "PaperCycleDryPlanner", lambda **kwargs: object())

    result = runner.invoke(
        d34_cli.d34_app,
        ["paper-cycle", "--dry-run", "--as-of", "2026-08-19T06:15:00+08:00"],
    )

    assert result.exit_code == 0, result.output
    receipt = json.loads(result.output.strip().splitlines()[-1])
    assert receipt["status"] == "dry_run"
    assert receipt["plan"]["would_write"] is False
    assert receipt["as_of"].startswith("2026-08-19T06:15:00")
    assert calls["cycle"] == 0
    assert planned["called"] == 1


def test_as_of_without_dry_run_is_rejected(monkeypatch) -> None:
    calls = _install(monkeypatch, paper_enabled=True)

    result = runner.invoke(
        d34_cli.d34_app,
        ["paper-cycle", "--as-of", "2026-08-19T06:15:00+08:00"],
    )

    assert result.exit_code != 0
    assert "as_of_requires_dry_run" in result.output
    assert calls["cycle"] == 0


def test_paper_cycle_blocked_when_observation_gate_closed(monkeypatch) -> None:
    calls = _install(monkeypatch, paper_enabled=False, emergency_active=True)

    result = runner.invoke(d34_cli.d34_app, ["paper-cycle"])

    assert result.exit_code == 0, result.output
    receipt = json.loads(result.output.strip().splitlines()[-1])
    assert receipt["status"] == "blocked"
    assert receipt["trading"]["sleeves_checked"] == 0
    assert calls["cycle"] == 0
