"""Read-only infrastructure preflight for the autonomous D-34 worker."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from quant_system.d34.docker_runtime import D34DockerReceipt, D34DockerRuntimeError

PREFLIGHT_CONTRACT = "hqa.d34_preflight/v1"
LLM_PREFLIGHT_CONTRACT = "hqa.d34_llm_preflight/v2"
LLM_PREFLIGHT_TIMEOUT_SECONDS = 120
_LLM_SMOKE_CONTRACT = "hqa.d34_llm_smoke/v1"
_SAFETY_CONTRACT = "hqa.effective_paper_safety/v2"
_SMOKE_CONTRACTS = {
    "versions": "hqa.d34_container_versions/v1",
    "qlib-smoke": "hqa.d34_qlib_smoke/v1",
    "llm-smoke": "hqa.d34_llm_smoke/v1",
    "futu-smoke": "hqa.d34_futu_socket_smoke/v1",
    "docker-smoke": "hqa.d34_docker_child_smoke/v1",
}


class DockerBoundary(Protocol):
    def run(
        self,
        *,
        job_id: str,
        command: tuple[str, ...],
        timeout_seconds: int | None = None,
    ) -> D34DockerReceipt: ...


class D34PreflightError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


@dataclass(frozen=True)
class D34PreflightReceipt:
    ready: bool
    checked_at: str
    image_digest: str
    docker_receipt_digest: str
    safety_contract: str
    live_execution_enabled: bool
    research_blockers: tuple[str, ...]
    paper_blockers: tuple[str, ...]
    smoke_contracts: dict[str, str]
    receipt_digest: str
    contract: str = PREFLIGHT_CONTRACT

    def to_public_dict(self) -> dict[str, object]:
        return {
            "contract": self.contract,
            "ready": self.ready,
            "checked_at": self.checked_at,
            "image_digest": self.image_digest,
            "docker_receipt_digest": self.docker_receipt_digest,
            "safety_contract": self.safety_contract,
            "live_execution_enabled": self.live_execution_enabled,
            "research_blockers": list(self.research_blockers),
            "paper_blockers": list(self.paper_blockers),
            "smoke_contracts": self.smoke_contracts,
            "receipt_digest": self.receipt_digest,
        }


def run_d34_preflight(
    *,
    workspace_root: Path,
    docker_runtime: DockerBoundary,
    safety_observer: Callable[[], Mapping[str, Any]],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> D34PreflightReceipt:
    """Prove DB authorities and all external runtime seams without mutations."""

    safety = dict(safety_observer())
    if safety.get("contract") != _SAFETY_CONTRACT:
        raise D34PreflightError(
            "d34_preflight_safety_contract_invalid",
            "D-34 effective safety contract is unavailable",
        )
    if safety.get("live_execution_enabled") is not False:
        raise D34PreflightError(
            "d34_preflight_live_boundary_invalid",
            "D-34 preflight requires live execution to remain disabled",
        )

    docker_receipt = docker_runtime.run(
        job_id="job-d34-preflight",
        command=("smoke",),
    )
    output = docker_receipt.output
    if output.get("contract") != "hqa.d34_container_smoke/v1":
        raise D34PreflightError(
            "d34_preflight_smoke_contract_invalid",
            "D-34 container smoke contract is invalid",
        )
    observed_contracts = {
        name: str(value.get("contract", ""))
        for name, value in output.items()
        if name in _SMOKE_CONTRACTS and isinstance(value, Mapping)
    }
    if observed_contracts != _SMOKE_CONTRACTS:
        raise D34PreflightError(
            "d34_preflight_smoke_incomplete",
            "D-34 container smoke did not prove every runtime seam",
        )

    checked_at = now().astimezone(UTC).isoformat()
    document = {
        "contract": PREFLIGHT_CONTRACT,
        "ready": True,
        "checked_at": checked_at,
        "image_digest": docker_receipt.image_digest,
        "docker_receipt_digest": docker_receipt.receipt_digest,
        "safety_contract": str(safety["contract"]),
        "live_execution_enabled": False,
        "research_blockers": list(safety.get("research_blockers", ())),
        "paper_blockers": list(safety.get("blockers", ())),
        "smoke_contracts": dict(sorted(observed_contracts.items())),
    }
    receipt = D34PreflightReceipt(
        ready=True,
        checked_at=checked_at,
        image_digest=docker_receipt.image_digest,
        docker_receipt_digest=docker_receipt.receipt_digest,
        safety_contract=str(safety["contract"]),
        live_execution_enabled=False,
        research_blockers=tuple(str(value) for value in safety.get("research_blockers", ())),
        paper_blockers=tuple(str(value) for value in safety.get("blockers", ())),
        smoke_contracts=dict(sorted(observed_contracts.items())),
        receipt_digest=_digest(document),
    )
    path = workspace_root / "preflight" / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(receipt.to_public_dict(), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)
    return receipt


@dataclass(frozen=True)
class D34LlmPreflightReceipt:
    job_id: str
    ready: bool
    checked_at: str
    image_digest: str
    docker_receipt_digest: str
    llm_contract: str
    code: str | None
    receipt_digest: str
    contract: str = LLM_PREFLIGHT_CONTRACT

    def to_public_dict(self) -> dict[str, object]:
        return {
            "contract": self.contract,
            "job_id": self.job_id,
            "ready": self.ready,
            "checked_at": self.checked_at,
            "image_digest": self.image_digest,
            "docker_receipt_digest": self.docker_receipt_digest,
            "llm_contract": self.llm_contract,
            "code": self.code,
            "receipt_digest": self.receipt_digest,
        }


def _persist_llm_preflight(workspace_root: Path, receipt: D34LlmPreflightReceipt) -> None:
    path = workspace_root / "jobs" / receipt.job_id / "llm_preflight.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(receipt.to_public_dict(), sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def _llm_smoke_ready(output: Mapping[str, Any]) -> bool:
    return output.get("contract") == _LLM_SMOKE_CONTRACT and output.get("json_mode") is True


def run_d34_llm_preflight(
    *,
    workspace_root: Path,
    job_id: str,
    docker_runtime: DockerBoundary,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> D34LlmPreflightReceipt:
    """Run one in-container chat completion bound to an already leased job."""

    if not job_id.startswith("job-"):
        raise D34PreflightError("d34_preflight_job_invalid", "preflight job is invalid")

    checked_at = now().astimezone(UTC).isoformat()
    image_digest = ""
    docker_receipt_digest = ""
    llm_contract = ""
    ready = False
    failure_code = "d34_preflight_llm_failed"
    try:
        docker_receipt = docker_runtime.run(
            job_id=job_id,
            command=("llm-smoke",),
            timeout_seconds=LLM_PREFLIGHT_TIMEOUT_SECONDS,
        )
        image_digest = docker_receipt.image_digest
        docker_receipt_digest = docker_receipt.receipt_digest
        output = docker_receipt.output
        llm_contract = str(output.get("contract", ""))
        ready = _llm_smoke_ready(output)
    except D34DockerRuntimeError:
        pass
    except Exception as exc:  # noqa: BLE001 - preflight failure is a typed job outcome
        failure_code = str(getattr(exc, "code", type(exc).__name__))[:128]

    document = {
        "contract": LLM_PREFLIGHT_CONTRACT,
        "job_id": job_id,
        "ready": ready,
        "checked_at": checked_at,
        "image_digest": image_digest,
        "docker_receipt_digest": docker_receipt_digest,
        "llm_contract": llm_contract,
        "code": None if ready else failure_code,
    }
    receipt = D34LlmPreflightReceipt(
        job_id=job_id,
        ready=ready,
        checked_at=checked_at,
        image_digest=image_digest,
        docker_receipt_digest=docker_receipt_digest,
        llm_contract=llm_contract,
        code=None if ready else failure_code,
        receipt_digest=_digest(document),
    )
    _persist_llm_preflight(workspace_root, receipt)
    return receipt


__all__ = [
    "D34LlmPreflightReceipt",
    "D34PreflightError",
    "D34PreflightReceipt",
    "LLM_PREFLIGHT_CONTRACT",
    "PREFLIGHT_CONTRACT",
    "run_d34_llm_preflight",
    "run_d34_preflight",
]
