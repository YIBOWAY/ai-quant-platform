"""Read-only infrastructure preflight for the autonomous D-34 worker."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from quant_system.d34.docker_runtime import D34DockerReceipt

PREFLIGHT_CONTRACT = "hqa.d34_preflight/v1"
_SAFETY_CONTRACT = "hqa.d34_effective_safety/v2"
_SMOKE_CONTRACTS = {
    "versions": "hqa.d34_container_versions/v1",
    "qlib-smoke": "hqa.d34_qlib_smoke/v1",
    "llm-smoke": "hqa.d34_llm_smoke/v1",
    "futu-smoke": "hqa.d34_futu_socket_smoke/v1",
    "docker-smoke": "hqa.d34_docker_child_smoke/v1",
}


class DockerBoundary(Protocol):
    def run(self, *, job_id: str, command: tuple[str, ...]) -> D34DockerReceipt: ...


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


__all__ = [
    "D34PreflightError",
    "D34PreflightReceipt",
    "PREFLIGHT_CONTRACT",
    "run_d34_preflight",
]
