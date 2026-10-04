"""research_request.json 跨容器边界的 digest 一致性（行为级回归）。

生产事故原型：worker 在 research_request.json 里写入宿主侧谱系字段 job_key，
容器边界（rdagent_qlib_runtime）用 D34ResearchRequest.model_validate 解析后
digest 的是 model_dump(mode="json")（extra 字段被丢弃），而宿主侧 persist 期望的
却是原始 dict 的 digest —— 两侧永远不等，每个生产批次都会触发
d34_experiment_trials_identity_mismatch。

这里的测试不复读字段清单，而是走真实边界：真实 _write_json 落盘 → 真实
model_validate（与 rdagent_qlib_runtime 同一调用）→ 真实
persist_host_d34_experiment_trials 全量校验 → 断言台账真的落了行。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from quant_system.d34.research_driver import (
    EXPERIMENT_TRIAL_BATCH_CONTRACT,
    D34ResearchRequest,
)
from quant_system.d34.worker import (
    _D34WorkerValidationError,
    _digest,
    _research_request_digest,
    _write_json,
    persist_host_d34_experiment_trials,
)
from quant_system.research.trials import TrialsLedger


def _calendar() -> list[str]:
    return [
        timestamp.isoformat()
        for timestamp in pd.bdate_range("2026-08-03", periods=5, tz="UTC")
    ]


def _research_request(provider_root: Path) -> dict[str, object]:
    """与 worker._run_lease 写盘的 research_request 同构（含宿主侧 job_key）。"""
    return {
        "contract": "hqa.d34_research_request/v2",
        "job_id": "job-boundary-0001",
        "run_id": "attempt-boundary-0001",
        "resource_envelope_id": "local-paper-research-v1",
        "resource_policy_digest": "f539564775cd6f0c51fbd8478697265c1f4df86987513dad5e7a842b92191270",
        "snapshot_id": "snapshot-boundary-0001",
        "snapshot_digest": "a" * 64,
        "snapshot_source": "futu",
        "provider_uri": str(provider_root),
        "universe": ["SPY", "QQQ"],
        "calendar": _calendar(),
        "max_iterations": 3,
        "experiments_per_iteration": 3,
        "top_k": 1,
        "initial_cash": 100_000.0,
        "budget_reservation_usd": 10.0,
        "objective": "Boundary digest identity regression.",
        "job_key": "request:2026-08-23:" + "b" * 12,
    }


def _write_batch(
    job_root: Path,
    *,
    request: D34ResearchRequest,
    daily_returns: list[float],
) -> Path:
    """按 research_driver 落批格式手写一批（1 成功 + 1 失败尝试）。"""
    calendar = list(request.calendar)
    universe = list(request.universe)
    attempts = [
        {
            "experiment_id": "iteration-01-experiment-01",
            "status": "succeeded",
            "attempt_receipt_digest": _digest({"experiment_id": "iteration-01-experiment-01"}),
        },
        {
            "experiment_id": "iteration-01-experiment-02",
            "status": "failed",
            "attempt_receipt_digest": _digest({"experiment_id": "iteration-01-experiment-02"}),
        },
    ]
    body = {
        "contract": EXPERIMENT_TRIAL_BATCH_CONTRACT,
        "job_id": request.job_id,
        "request_digest": request.request_digest,
        "universe": universe,
        "universe_digest": _digest(universe),
        "calendar_digest": _digest(calendar),
        "return_dates": calendar,
        "experiment_count": 2,
        "successful_experiment_count": 1,
        "attempts": attempts,
        "selected_experiment": "iteration-01-experiment-01",
        "experiments": [
            {
                "experiment_id": "iteration-01-experiment-01",
                "subject": "momentum:iteration-01-experiment-01",
                "proposal_digest": _digest({"operator": "momentum"}),
                "experiment_receipt_digest": _digest({"status": "succeeded"}),
                "daily_returns": daily_returns,
            }
        ],
    }
    batch_path = (
        job_root / "research" / f"experiment-trials-{request.request_digest[:32]}.json"
    )
    _write_json(batch_path, {**body, "receipt_digest": _digest(body)})
    return batch_path


def test_host_request_digest_matches_container_boundary(tmp_path: Path) -> None:
    provider_root = tmp_path / "provider"
    provider_root.mkdir()
    job_root = tmp_path / "jobs" / "job-boundary-0001"
    job_root.mkdir(parents=True)

    raw = _research_request(provider_root)
    request_path = job_root / "research_request.json"
    _write_json(request_path, raw)

    # 真实容器边界：与 rdagent_qlib_runtime 同一调用。
    container_request = D34ResearchRequest.model_validate(
        json.loads(request_path.read_text(encoding="utf-8"))
    )

    # 复现事故条件：谱系字段在场时，原始 dict digest 必然不等于容器 digest，
    # 证明本测试夹具确实覆盖当初的阻断机制，而不是空转。
    assert "job_key" in raw
    assert _digest(raw) != container_request.request_digest

    # 修复后的宿主期望必须与容器一致；批次文件名两侧拼接也随之一致。
    assert _research_request_digest(raw) == container_request.request_digest


def test_persist_round_trip_accepts_container_digested_batch(tmp_path: Path) -> None:
    provider_root = tmp_path / "provider"
    provider_root.mkdir()
    job_root = tmp_path / "jobs" / "job-boundary-0001"
    job_root.mkdir(parents=True)
    platform_root = tmp_path / "platform"
    platform_root.mkdir()

    raw = _research_request(provider_root)
    container_request = D34ResearchRequest.model_validate(raw)
    daily_returns = [0.0, 0.001, -0.0005, 0.002, -0.001]
    batch_path = _write_batch(job_root, request=container_request, daily_returns=daily_returns)

    result = persist_host_d34_experiment_trials(
        data_root=platform_root / "data",
        batch_path=batch_path,
        expected_file_digest=hashlib.sha256(batch_path.read_bytes()).hexdigest(),
        expected_batch_digest=str(
            json.loads(batch_path.read_text(encoding="utf-8"))["receipt_digest"]
        ),
        expected_job_id=str(raw["job_id"]),
        expected_request_digest=_research_request_digest(raw),
        expected_universe=list(raw["universe"]),
        expected_calendar_digest=_digest(list(raw["calendar"])),
        expected_experiment_count=2,
    )

    # 后果断言：台账真的追加了 2 行（1 成功 + 1 失败墓碑），scope  census 通过。
    assert result["successful_experiment_count"] == 1
    assert result["completed_experiment_count"] == 2
    assert result["trial_coverage"]["passed"] is True
    ledger = TrialsLedger(platform_root / "data" / "trials")
    trials = ledger.list()
    assert len(trials) == 2
    statuses = {trial.metadata["attempt_status"] for trial in trials}
    assert statuses == {"succeeded", "failed"}
    assert all(
        trial.metadata["request_digest"] == container_request.request_digest
        for trial in trials
    )


def test_persist_round_trip_rejects_raw_dict_digest(tmp_path: Path) -> None:
    """反事实锚：若宿主仍按原始 dict 取 digest（修复前行为），身份校验必须拒绝。"""
    provider_root = tmp_path / "provider"
    provider_root.mkdir()
    job_root = tmp_path / "jobs" / "job-boundary-0001"
    job_root.mkdir(parents=True)
    platform_root = tmp_path / "platform"
    platform_root.mkdir()

    raw = _research_request(provider_root)
    container_request = D34ResearchRequest.model_validate(raw)
    batch_path = _write_batch(
        job_root, request=container_request, daily_returns=[0.0, 0.001, -0.0005, 0.002, -0.001]
    )

    with pytest.raises(_D34WorkerValidationError) as excinfo:
        persist_host_d34_experiment_trials(
            data_root=platform_root / "data",
            batch_path=batch_path,
            expected_file_digest=hashlib.sha256(batch_path.read_bytes()).hexdigest(),
            expected_batch_digest=str(
                json.loads(batch_path.read_text(encoding="utf-8"))["receipt_digest"]
            ),
            expected_job_id=str(raw["job_id"]),
            expected_request_digest=_digest(raw),
            expected_universe=list(raw["universe"]),
            expected_calendar_digest=_digest(list(raw["calendar"])),
            expected_experiment_count=2,
        )
    assert excinfo.value.code == "d34_experiment_trials_identity_mismatch"
    # 后果断言：被拒批次不得落任何台账行。
    assert TrialsLedger(platform_root / "data" / "trials").list() == []
