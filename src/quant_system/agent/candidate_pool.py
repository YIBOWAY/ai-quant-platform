from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from quant_system.agent.models import (
    CandidateArtifact,
    CandidateStatus,
    ReviewRecord,
    utc_now_iso,
)

_SAFE_ID_PATTERN = re.compile(r"[^A-Za-z0-9_]+")
_SAFE_CANDIDATE_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")


def _slug(value: str, *, fallback: str = "candidate", max_length: int = 40) -> str:
    cleaned = _SAFE_ID_PATTERN.sub("_", value.lower()).strip("_")
    return (cleaned or fallback)[:max_length].strip("_") or fallback


def _candidate_id(*, task_id: str, artifact_type: str, goal: str) -> str:
    digest = hashlib.sha256(f"{task_id}|{artifact_type}|{goal}".encode()).hexdigest()[:10]
    return f"{_slug(artifact_type)}-{_slug(goal)}-{digest}"


class CandidatePool:
    """Stores agent outputs as inert candidate artifacts for human review."""

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self.candidates_dir = self.output_dir / "agent" / "candidates"

    def write_candidate(
        self,
        *,
        task_id: str,
        goal: str,
        artifact_type: str,
        filename: str,
        content: str,
        universe: list[str] | None = None,
        metadata_extra: dict[str, Any] | None = None,
    ) -> CandidateArtifact:
        candidate_id = _candidate_id(task_id=task_id, artifact_type=artifact_type, goal=goal)
        candidate_dir = self.candidates_dir / candidate_id
        candidate_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = candidate_dir / filename
        artifact_path.write_text(content, encoding="utf-8")
        metadata_path = candidate_dir / "metadata.json"
        metadata = {
            "candidate_id": candidate_id,
            "task_id": task_id,
            "artifact_type": artifact_type,
            "goal": goal,
            "universe": universe or [],
            "status": CandidateStatus.PENDING.value,
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
            "files": [filename],
            "safety": {
                "auto_promotion": False,
                "requires_human_review": True,
                "review_status": "pending",
            },
        }
        metadata.update(metadata_extra or {})
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return CandidateArtifact(
            candidate_id=candidate_id,
            task_id=task_id,
            artifact_type=artifact_type,
            path=artifact_path,
            metadata_path=metadata_path,
            status=CandidateStatus.PENDING,
        )

    def list_candidates(self) -> list[dict[str, Any]]:
        if not self.candidates_dir.exists():
            return []
        candidates: list[dict[str, Any]] = []
        metadata_paths = sorted(
            self.candidates_dir.glob("*/metadata.json"),
            key=lambda path: (path.stat().st_mtime_ns, path.parent.name),
            reverse=True,
        )
        for metadata_path in metadata_paths:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            candidate_dir = metadata_path.parent
            if (candidate_dir / "approved.lock").exists():
                metadata["status"] = CandidateStatus.APPROVED.value
            elif (candidate_dir / "rejected.lock").exists():
                metadata["status"] = CandidateStatus.REJECTED.value
            candidates.append(metadata)
        return candidates

    def review(
        self,
        *,
        candidate_id: str,
        decision: Literal["approve", "reject"],
        note: str,
    ) -> ReviewRecord:
        if _SAFE_CANDIDATE_ID.fullmatch(candidate_id) is None:
            raise FileNotFoundError(f"candidate {candidate_id!r} does not exist")
        candidate_dir = self.candidates_dir / candidate_id
        metadata_path = candidate_dir / "metadata.json"
        if not metadata_path.exists():
            raise FileNotFoundError(f"candidate {candidate_id!r} does not exist")

        record = ReviewRecord(candidate_id=candidate_id, decision=decision, note=note)
        with (candidate_dir / "reviews.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")

        status = CandidateStatus.APPROVED if decision == "approve" else CandidateStatus.REJECTED
        lock_name = "approved.lock" if decision == "approve" else "rejected.lock"
        (candidate_dir / lock_name).write_text(record.model_dump_json(indent=2), encoding="utf-8")

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["status"] = status.value
        metadata["updated_at"] = utc_now_iso()
        metadata["safety"]["review_status"] = status.value
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return record
