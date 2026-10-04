from __future__ import annotations

import hashlib
import inspect
import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from quant_system.d34.docker_runtime import D34DockerReceipt
from quant_system.d34.engine_comparison import EngineReceipt
from quant_system.d34.research_request import digest_document
from quant_system.execution.assistant_remote import (
    AssistantRemoteError,
    hang_candidate,
    load_book,
    project_book,
    save_book,
    verify_registered_factor,
)
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.factors.examples import LiquidityFactor
from quant_system.factors.library.promoted.agent_candidate_wave2_sceneb_mom20_v3 import (
    AgentCandidateFactor,
)
from quant_system.options.seller_score import is_us_market_session
from tests.test_assistant_remote import _settings, _strong_returns


def _dates(n: int = 240) -> list[str]:
    result: list[str] = []
    current = date(2026, 8, 21)
    while len(result) < n:
        if is_us_market_session(current):
            result.append(f"{current.isoformat()}T00:00:00+00:00")
        current -= timedelta(days=1)
    return list(reversed(result))


class _Boundary:
    provider_name = "futu"

    def __init__(
        self,
        workspace: Path,
        *,
        returns: list[float | bool] | None = None,
        divergent: bool = False,
        turnover: float = 0.2,
        receipt_factor_id: str | None = None,
        receipt_source_digest: str | None = None,
    ) -> None:
        self.workspace = workspace
        self.returns = returns or _strong_returns()
        self.divergent = divergent
        self.turnover = turnover
        self.receipt_factor_id = receipt_factor_id
        self.receipt_source_digest = receipt_source_digest
        self.calls: list[str] = []
        self.requests: list[dict[str, object]] = []

    def fetch_ohlcv(self, symbols, *, start, end, interval):
        self.calls.append("futu")
        assert interval == "1d"
        rows = []
        sessions = _dates(len(self.returns))
        for offset, symbol in enumerate(symbols):
            for index, raw_date in enumerate(sessions):
                timestamp = pd.Timestamp(raw_date)
                close = 100.0 + offset + index * 0.1
                rows.append(
                    {
                        "symbol": symbol,
                        "timestamp": timestamp,
                        "open": close - 0.1,
                        "high": close + 0.2,
                        "low": close - 0.2,
                        "close": close,
                        "volume": 1_000_000,
                        "provider": "futu",
                        "interval": "1d",
                        "event_ts": timestamp,
                        "knowledge_ts": pd.Timestamp("2026-08-23T12:00:00Z"),
                        "price_adjustment": "qfq",
                    }
                )
        return pd.DataFrame(rows)

    def _host(self, raw: str) -> Path:
        return self.workspace / raw.removeprefix("/workspace/d34/")

    def run(self, *, job_id, command, timeout_seconds=None):
        del timeout_seconds
        self.calls.append(command[0])
        if command[0] == "qlib-adapt":
            output = self._host(command[command.index("--output-root") + 1])
            provider = output / "provider"
            provider.mkdir(parents=True)
            body = {"contract": "hqa.qlib_provider/v1", "provider_uri": str(provider)}
            return D34DockerReceipt(
                contract="hqa.d34_docker_receipt/v1",
                job_id=job_id,
                image_ref="fixture",
                image_digest="sha256:" + "9" * 64,
                command=tuple(command),
                output=body,
                receipt_digest=digest_document(body),
            )
        assert command[0] == "registered-verify"
        request_path = self._host(command[command.index("--request") + 1])
        request = json.loads(request_path.read_text(encoding="utf-8"))
        self.requests.append(request)
        output_root = self._host(command[command.index("--output-root") + 1])
        output_root.mkdir(parents=True)
        target = output_root / "target_weights.parquet"
        target.write_bytes(b"target-weights-fixture")
        body = {
            "contract": "hqa.d34_engine_receipt/v1",
            "engine": "qlib",
            "job_id": request["job_id"],
            "run_id": request["run_id"],
            "factor_id": self.receipt_factor_id or request["factor_id"],
            "source_digest": self.receipt_source_digest or request["source_digest"],
            "snapshot_id": request["snapshot_id"],
            "snapshot_digest": request["snapshot_digest"],
            "universe_digest": digest_document(request["universe"]),
            "calendar_digest": digest_document(request["calendar"]),
            "target_weights_digest": hashlib.sha256(target.read_bytes()).hexdigest(),
            "daily_returns": self.returns,
            "return_dates": request["calendar"],
            "terminal_nav": math.prod(1 + value for value in self.returns),
            "terminal_weights": {"SPY": 0.5, "QQQ": 0.5},
            "metrics": {"sharpe": 1.2},
            "qlib_config": {"expression": request["qlib_expression"]},
            "qlib_config_digest": digest_document({"expression": request["qlib_expression"]}),
        }
        receipt_digest = digest_document(body)
        raw = output_root / "qlib_receipt.json"
        raw.write_text(json.dumps({**body, "receipt_digest": receipt_digest}), encoding="utf-8")
        result = {
            "contract": "hqa.registered_factor_qlib_result/v1",
            "job_id": request["job_id"],
            "run_id": request["run_id"],
            "qlib_receipt_path": f"/workspace/d34/{raw.relative_to(self.workspace)}",
            "qlib_receipt_digest": receipt_digest,
            "target_weights_path": f"/workspace/d34/{target.relative_to(self.workspace)}",
            "target_weights_digest": hashlib.sha256(target.read_bytes()).hexdigest(),
        }
        return D34DockerReceipt(
            contract="hqa.d34_docker_receipt/v1",
            job_id=job_id,
            image_ref="fixture",
            image_digest="sha256:" + "9" * 64,
            command=tuple(command),
            output=result,
            receipt_digest=digest_document(result),
        )

    def replay(self, *, qlib_receipt, job_id, run_id, output_root, **_kwargs):
        self.calls.append("platform-replay")
        output = Path(output_root) / "replay-fixture"
        output.mkdir(parents=True)
        returns = (
            tuple(-value for value in qlib_receipt.daily_returns)
            if self.divergent
            else qlib_receipt.daily_returns
        )
        # Explicit artificial protocol originals, not market-engine evidence.
        # Keep the requested returns and turnover unchanged while materializing
        # the producer's declared configuration and output-file bindings.
        nav = 100_000.0
        marks = []
        for stamp, value in zip(qlib_receipt.return_dates, returns, strict=True):
            nav *= 1 + value
            marks.append({"timestamp": pd.Timestamp(stamp), "equity": nav})
        gross = self.turnover * 100_000.0
        frames = {
            "equity_curve.parquet": pd.DataFrame(marks),
            "trade_blotter.parquet": pd.DataFrame(
                [
                    {
                        "timestamp": pd.Timestamp(qlib_receipt.return_dates[0]),
                        "symbol": "SPY",
                        "side": "buy",
                        "quantity": gross / 100.0,
                        "requested_price": 100 / 1.0005,
                        "fill_price": 100.0,
                        "commission": gross * 0.0001,
                    }
                ]
            )
            if gross
            else pd.DataFrame(
                columns=["quantity", "fill_price", "requested_price", "commission", "side"]
            ),
            "orders.parquet": pd.DataFrame({"artificial": []}),
            "positions.parquet": pd.DataFrame({"artificial": []}),
            "attribution.parquet": pd.DataFrame({"artificial": []}),
        }
        output_digests = {}
        for name, frame in frames.items():
            frame.to_parquet(output / name, index=False)
            output_digests[name] = hashlib.sha256((output / name).read_bytes()).hexdigest()
        body = {
            "contract": "hqa.d34_engine_receipt/v1",
            "engine": "platform",
            "job_id": job_id,
            "run_id": run_id,
            "snapshot_digest": qlib_receipt.snapshot_digest,
            "universe_digest": qlib_receipt.universe_digest,
            "calendar_digest": qlib_receipt.calendar_digest,
            "target_weights_digest": qlib_receipt.target_weights_digest,
            "daily_returns": list(returns),
            "return_dates": list(qlib_receipt.return_dates),
            "terminal_nav": nav / 100_000.0,
            "terminal_weights": dict(qlib_receipt.terminal_weights),
            "metrics": {"turnover": self.turnover},
            "config": {
                "initial_cash": 100000.0,
                "commission_bps": 1.0,
                "slippage_bps": 5.0,
                "min_order_value": 0.0,
                "whole_share_orders": False,
                "execution_price": "next_open",
            },
            "output_digests": output_digests,
        }
        receipt_digest = digest_document(body)
        (output / "receipt.json").write_text(
            json.dumps({**body, "receipt_digest": receipt_digest}), encoding="utf-8"
        )
        return SimpleNamespace(
            output_dir=output,
            turnover_period=self.turnover,
            engine_receipt=EngineReceipt(
                engine="platform",
                snapshot_digest=qlib_receipt.snapshot_digest,
                universe_digest=qlib_receipt.universe_digest,
                calendar_digest=qlib_receipt.calendar_digest,
                target_weights_digest=qlib_receipt.target_weights_digest,
                daily_returns=returns,
                return_dates=qlib_receipt.return_dates,
                terminal_nav=nav / 100_000.0,
                terminal_weights=qlib_receipt.terminal_weights,
                receipt_digest=receipt_digest,
            ),
        )


def _verify(settings, boundary: _Boundary):
    return verify_registered_factor(
        settings,
        factor_id=AgentCandidateFactor.factor_id,
        universe=["SPY", "QQQ"],
        boundary=boundary,
        now=lambda: datetime(2026, 8, 23, 12, tzinfo=UTC),
    )


def test_verify_from_registered_generates_dual_engine_evidence_once_and_is_idempotent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    boundary = _Boundary(tmp_path / "_runtime/d34")

    first = _verify(settings, boundary)
    replay = _verify(settings, boundary)

    assert first == replay
    assert first["status"] == "verified"
    assert first["sleeve_id"] is None
    assert first["source"] == "registered_factor"
    assert first["verification_gates"]["dsr"]["passed"] is True
    assert first["verification_gates"]["cost_sensitivity"]["passed"] is True
    assert first["evidence_ref"]["job_id"].startswith("job-registered-")
    assert boundary.calls.count("futu") == 1
    assert boundary.calls.count("registered-verify") == 1
    assert boundary.calls.count("platform-replay") == 1
    assert boundary.requests[0]["factor_id"] == AgentCandidateFactor.factor_id
    assert boundary.requests[0]["qlib_expression"] == "$close/Ref($close,20)-1"
    assert len(project_book(settings)["candidates"]) == 1
    assert not (tmp_path / "api_runs").exists()


def test_registered_candidate_identity_is_evidence_scoped_across_universes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    boundary = _Boundary(tmp_path / "_runtime/d34")

    first = verify_registered_factor(
        settings,
        factor_id=AgentCandidateFactor.factor_id,
        universe=["SPY", "QQQ"],
        boundary=boundary,
        now=lambda: datetime(2026, 8, 23, 12, tzinfo=UTC),
    )
    first_replay = verify_registered_factor(
        settings,
        factor_id=AgentCandidateFactor.factor_id,
        universe=["SPY", "QQQ"],
        boundary=boundary,
        now=lambda: datetime(2026, 8, 23, 12, tzinfo=UTC),
    )
    second = verify_registered_factor(
        settings,
        factor_id=AgentCandidateFactor.factor_id,
        universe=["SPY", "IWM"],
        boundary=boundary,
        now=lambda: datetime(2026, 8, 23, 12, tzinfo=UTC),
    )
    second_replay = verify_registered_factor(
        settings,
        factor_id=AgentCandidateFactor.factor_id,
        universe=["SPY", "IWM"],
        boundary=boundary,
        now=lambda: datetime(2026, 8, 23, 12, tzinfo=UTC),
    )

    assert first_replay["candidate_id"] == first["candidate_id"]
    assert second_replay["candidate_id"] == second["candidate_id"]
    assert first["candidate_id"] != second["candidate_id"]
    assert first["evidence_ref"]["job_id"] != second["evidence_ref"]["job_id"]
    assert len(project_book(settings)["candidates"]) == 2


def test_registered_digest_command_cannot_fund_without_current_family_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    verified = _verify(settings, _Boundary(tmp_path / "_runtime/d34"))
    assert PaperStrategySleeveStorage(tmp_path / "api_runs").list_sleeves() == []
    # One recorded artificial hypothesis cannot supply a complete statistical
    # family. An explicit owner digest command never replaces current quality.
    from quant_system.research.capital_evidence import current_candidate_quality
    from quant_system.research.trials import TrialsLedger

    quality = current_candidate_quality(settings, verified, [verified])
    assert quality["eligible"] is False
    assert quality["n_family_members"] == 1
    assert "family_evidence_incomplete" in quality["reasons"]
    assert len(TrialsLedger(tmp_path / "trials").list()) == 1
    book_path = tmp_path / "assistant_remote/book.json"
    before = book_path.read_bytes()
    for _ in range(2):
        with pytest.raises(AssistantRemoteError) as rejected:
            hang_candidate(
                settings,
                candidate_id=verified["candidate_id"],
                expected_source_digest=verified["source_digest"],
            )
        assert rejected.value.code == "new_capital_quality_failed:" + ",".join(quality["reasons"])
        assert book_path.read_bytes() == before
        assert PaperStrategySleeveStorage(tmp_path / "api_runs").list_sleeves() == []
        assert not (tmp_path / "api_runs").exists()
    saved = load_book(settings)["candidates"][0]
    assert saved["status"] == "verified" and saved["sleeve_id"] is None


@pytest.mark.parametrize(
    ("mode", "factor_id", "expected_code"),
    [
        (None, "not_registered_factor", "registered_factor_not_supported"),
        ("divergent", AgentCandidateFactor.factor_id, "registered_factor_dual_engine_rejected"),
        ("zero", AgentCandidateFactor.factor_id, "dsr_performance_required"),
        ("cost", AgentCandidateFactor.factor_id, "cost_sensitivity_failed"),
        ("bool", AgentCandidateFactor.factor_id, "registered_engine_receipt_invalid"),
    ],
)
def test_verify_from_registered_fails_before_candidate_write(
    tmp_path: Path,
    monkeypatch,
    mode: str | None,
    factor_id: str,
    expected_code: str,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    external = _Boundary(
        tmp_path / "_runtime/d34",
        returns=(
            [0.0] * 240
            if mode == "zero"
            else [True, *_strong_returns()[1:]]
            if mode == "bool"
            else None
        ),
        divergent=mode == "divergent",
        turnover=1_000_000.0 if mode == "cost" else 0.2,
    )

    with pytest.raises(AssistantRemoteError) as rejected:
        verify_registered_factor(
            settings,
            factor_id=factor_id,
            universe=["SPY", "QQQ"],
            boundary=external,
            now=lambda: datetime(2026, 8, 23, 12, tzinfo=UTC),
        )

    assert rejected.value.code == expected_code
    assert project_book(settings)["candidates"] == []
    assert not (tmp_path / "api_runs").exists()


def test_registered_factor_requires_an_exact_source_adapter_before_io(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    boundary = _Boundary(tmp_path / "_runtime/d34")

    with pytest.raises(AssistantRemoteError) as unsupported:
        verify_registered_factor(
            settings,
            factor_id=LiquidityFactor.factor_id,
            universe=["SPY", "QQQ"],
            boundary=boundary,
            now=lambda: datetime(2026, 8, 23, 12, tzinfo=UTC),
        )

    assert unsupported.value.code == "registered_factor_not_supported"
    assert boundary.calls == []
    assert project_book(settings)["candidates"] == []


def test_registered_factor_rejects_source_changed_after_adapter_registration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    boundary = _Boundary(tmp_path / "_runtime/d34")

    def changed_compute(self, frame):
        return frame.groupby("symbol", sort=False)["close"].pct_change(5)

    assert inspect.getsource(AgentCandidateFactor._compute_values) != inspect.getsource(
        changed_compute
    )
    monkeypatch.setattr(AgentCandidateFactor, "_compute_values", changed_compute)

    with pytest.raises(AssistantRemoteError) as unsupported:
        _verify(settings, boundary)

    assert unsupported.value.code == "registered_factor_not_supported"
    assert boundary.calls == []
    assert project_book(settings)["candidates"] == []


@pytest.mark.parametrize(
    ("receipt_factor_id", "receipt_source_digest"),
    [
        ("macd", None),
        (None, "0" * 64),
    ],
)
def test_registered_factor_rejects_swapped_raw_factor_lineage(
    tmp_path: Path,
    monkeypatch,
    receipt_factor_id: str | None,
    receipt_source_digest: str | None,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    boundary = _Boundary(
        tmp_path / "_runtime/d34",
        receipt_factor_id=receipt_factor_id,
        receipt_source_digest=receipt_source_digest,
    )

    with pytest.raises(AssistantRemoteError) as rejected:
        _verify(settings, boundary)

    assert rejected.value.code == "registered_engine_receipt_invalid"
    assert project_book(settings)["candidates"] == []


def test_verify_from_registered_rejects_correlated_hung_peer_without_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    returns = _strong_returns()
    dates = [value[:10] for value in _dates()]
    book = load_book(settings)
    book["candidates"] = [
        {
            "candidate_id": "existing-hung-peer",
            "status": "hung",
            "sleeve_id": "paper-existing",
            "performance": {"daily_returns": returns, "return_dates": dates},
        }
    ]
    save_book(settings, book)
    before = (tmp_path / "assistant_remote/book.json").read_bytes()

    with pytest.raises(AssistantRemoteError) as rejected:
        _verify(settings, _Boundary(tmp_path / "_runtime/d34"))

    assert rejected.value.code == "correlated_duplicate"
    assert (tmp_path / "assistant_remote/book.json").read_bytes() == before


def test_registered_evidence_tamper_is_zero_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    boundary = _Boundary(tmp_path / "_runtime/d34")
    verified = _verify(settings, boundary)
    book_path = tmp_path / "assistant_remote/book.json"
    book_path.unlink()
    root = tmp_path / "_runtime/d34/jobs" / verified["evidence_ref"]["job_id"]
    platform_raw = next((root / "platform-replay").rglob("receipt.json"))
    platform_raw.write_text("{}", encoding="utf-8")

    with pytest.raises(AssistantRemoteError) as rejected:
        _verify(settings, boundary)

    assert rejected.value.code == "registered_evidence_file_invalid"
    assert not book_path.exists()


def test_verify_from_registered_cli_has_no_self_signed_receipt_entry(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from quant_system import assistant_remote_cli

    settings = _settings(tmp_path, monkeypatch)
    observed: dict[str, object] = {}
    monkeypatch.setattr(assistant_remote_cli, "load_settings", lambda: settings)
    monkeypatch.setattr(
        assistant_remote_cli,
        "verify_registered_factor",
        lambda _settings, **kwargs: (
            observed.update(kwargs) or {"status": "verified", "sleeve_id": None}
        ),
    )

    code = assistant_remote_cli.main(
        [
            "verify-from-registered",
            "--factor-id",
            AgentCandidateFactor.factor_id,
            "--universe",
            "SPY",
            "--universe",
            "QQQ",
        ]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "verified"
    assert observed == {
        "factor_id": AgentCandidateFactor.factor_id,
        "universe": ["SPY", "QQQ"],
    }
