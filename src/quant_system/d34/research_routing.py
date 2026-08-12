"""Read-only projection for the D-34 default research entry and D-33 fallback."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

ROUTING_CONTRACT = "hqa.d34_research_routing/v1"
ROUTING_STATE_CONTRACT = "hqa.d34_research_routing_state/v1"
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class D34ResearchRoutingAuthority:
    """Durable local cutover receipt; the database safety view remains authoritative."""

    def __init__(
        self,
        path: Path,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.path = path
        self.now = now

    def observe(self) -> dict[str, object]:
        if not self.path.exists():
            return {
                "contract": ROUTING_STATE_CONTRACT,
                "requested_default": "d33",
                "final_acceptance_digest": None,
                "reason": "D-34 final acceptance has not been recorded",
                "updated_at": None,
            }
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("d34_research_routing_state_invalid") from exc
        if not self._valid(payload):
            raise ValueError("d34_research_routing_state_invalid")
        return payload

    def activate_d34(
        self,
        *,
        safety: Mapping[str, object],
        final_acceptance_digest: str,
        reason: str,
    ) -> dict[str, object]:
        if _DIGEST_RE.fullmatch(final_acceptance_digest) is None or not reason.strip():
            raise ValueError("d34_research_cutover_invalid")
        projected = project_research_routing(
            safety,
            {
                "contract": ROUTING_STATE_CONTRACT,
                "requested_default": "d34",
                "final_acceptance_digest": final_acceptance_digest,
                "reason": reason.strip(),
                "updated_at": self.now().isoformat(),
            },
        )
        if projected["default_research_entry"] != "d34":
            raise ValueError("d34_research_cutover_not_qualified")
        state = {
            "contract": ROUTING_STATE_CONTRACT,
            "requested_default": "d34",
            "final_acceptance_digest": final_acceptance_digest,
            "reason": reason.strip(),
            "updated_at": self.now().isoformat(),
        }
        self._write(state)
        return state

    def restore_d33(self, *, reason: str) -> dict[str, object]:
        if not reason.strip():
            raise ValueError("d34_research_fallback_invalid")
        state = {
            "contract": ROUTING_STATE_CONTRACT,
            "requested_default": "d33",
            "final_acceptance_digest": None,
            "reason": reason.strip(),
            "updated_at": self.now().isoformat(),
        }
        self._write(state)
        return state

    def _write(self, state: Mapping[str, object]) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(
            json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)

    @staticmethod
    def _valid(payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        requested = payload.get("requested_default")
        digest = payload.get("final_acceptance_digest")
        return (
            payload.get("contract") == ROUTING_STATE_CONTRACT
            and requested in {"d33", "d34"}
            and isinstance(payload.get("reason"), str)
            and bool(payload["reason"].strip())
            and (payload.get("updated_at") is None or isinstance(payload["updated_at"], str))
            and (
                (requested == "d33" and digest is None)
                or (
                    requested == "d34"
                    and isinstance(digest, str)
                    and _DIGEST_RE.fullmatch(digest) is not None
                )
            )
        )


def project_research_routing(
    safety: Mapping[str, object],
    state: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Choose one new-research entry without stopping D-33 sleeve maintenance."""
    if safety.get("contract") != "hqa.effective_paper_safety/v2":
        raise ValueError("d34_research_routing_safety_invalid")
    workspace_id = safety.get("workspace_id")
    d33 = safety.get("d33")
    d34 = safety.get("d34")
    soak = safety.get("soak")
    emergency = safety.get("emergency_stop")
    if (
        not isinstance(workspace_id, str)
        or not workspace_id
        or not isinstance(d33, Mapping)
        or not isinstance(d34, Mapping)
        or not isinstance(soak, Mapping)
        or not isinstance(emergency, Mapping)
        or type(d33.get("mode_enabled")) is not bool
        or type(d33.get("auto_land_enabled")) is not bool
        or type(d34.get("mandate_active")) is not bool
        or type(soak.get("time_gate_ready")) is not bool
        or type(emergency.get("active")) is not bool
    ):
        raise ValueError("d34_research_routing_safety_invalid")
    soak_fields = (
        "completed_cycles",
        "required_completed_cycles",
        "canary_observation_days",
        "required_canary_observation_days",
    )
    if any(type(soak.get(field)) is not int for field in soak_fields):
        raise ValueError("d34_research_routing_safety_invalid")
    state = state or {
        "contract": ROUTING_STATE_CONTRACT,
        "requested_default": "d33",
        "final_acceptance_digest": None,
        "reason": "D-34 final acceptance has not been recorded",
        "updated_at": None,
    }
    if not D34ResearchRoutingAuthority._valid(state):
        raise ValueError("d34_research_routing_state_invalid")

    requested_default = str(state["requested_default"])
    d34_is_default = bool(
        requested_default == "d34" and soak["time_gate_ready"] and d34["mandate_active"]
    )
    emergency_active = bool(emergency["active"])
    reason_codes: list[str] = []
    if d34_is_default:
        reason_codes.append("d34_final_acceptance_recorded")
    elif requested_default == "d34" and soak["time_gate_ready"]:
        reason_codes.append("d34_mandate_inactive")
    elif requested_default == "d33" and soak["time_gate_ready"]:
        reason_codes.append("d34_final_acceptance_pending")
    else:
        reason_codes.append("d34_time_gate_pending")
    if emergency_active:
        reason_codes.append("emergency_stop_active")

    return {
        "contract": ROUTING_CONTRACT,
        "workspace_id": workspace_id,
        "requested_default": requested_default,
        "final_acceptance_digest": state["final_acceptance_digest"],
        "default_research_entry": "d34" if d34_is_default else "d33",
        "d33_new_intake_enabled": not d34_is_default and not emergency_active,
        "d33_maintenance_enabled": bool(d33["mode_enabled"] and d33["auto_land_enabled"]),
        "reason_codes": reason_codes,
        "soak": {field: soak[field] for field in (*soak_fields, "time_gate_ready")},
    }


__all__ = [
    "D34ResearchRoutingAuthority",
    "ROUTING_CONTRACT",
    "ROUTING_STATE_CONTRACT",
    "project_research_routing",
]
