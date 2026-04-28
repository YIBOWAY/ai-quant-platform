from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quant_system.agent.models import utc_now_iso


class AgentAuditLog:
    """Append-only JSONL audit log for one agent task."""

    def __init__(self, output_dir: str | Path, *, task_id: str) -> None:
        self.output_dir = Path(output_dir)
        self.task_id = task_id
        self.audit_dir = self.output_dir / "agent" / "audit"
        self.path = self.audit_dir / f"{task_id}.jsonl"

    def record(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        event = {
            "timestamp": utc_now_iso(),
            "task_id": self.task_id,
            "event_type": event_type,
            "payload": payload or {},
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
