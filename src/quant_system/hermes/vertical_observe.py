"""V7g-A-M1: project hermetic Vertical A Task/Attempt/Run onto workspace spine.

Promotes L5b empty task/attempt/run slots when the hermetic vertical binder has
rows. Empty remains honest. Never invents rows from ordinary conversation
commands. Health ready when projector mounted.
"""

from __future__ import annotations

from typing import Any

from quant_system.hermes.vertical_binding_authority import (
    VerticalBindingAuthority,
    default_vertical_binding_authority,
)


def project_workspace_tasks(
    workspace_id: str,
    *,
    authority: VerticalBindingAuthority | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    auth = authority or default_vertical_binding_authority()
    return [r.to_public_dict() for r in auth.list_tasks(workspace_id, limit=limit)]


def project_workspace_attempts(
    workspace_id: str,
    *,
    authority: VerticalBindingAuthority | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    auth = authority or default_vertical_binding_authority()
    return [r.to_public_dict() for r in auth.list_attempts(workspace_id, limit=limit)]


def project_workspace_runs(
    workspace_id: str,
    *,
    authority: VerticalBindingAuthority | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    auth = authority or default_vertical_binding_authority()
    return [r.to_public_dict() for r in auth.list_runs(workspace_id, limit=limit)]


def task_ids_for_spine(
    workspace_id: str,
    *,
    authority: VerticalBindingAuthority | None = None,
    limit: int = 50,
) -> list[str]:
    """Id-only projection for WorkspaceSnapshot.tasks: tuple[str, ...]."""
    return [
        str(r["task_id"])
        for r in project_workspace_tasks(
            workspace_id, authority=authority, limit=limit
        )
        if r.get("task_id")
    ]


def attempt_ids_for_spine(
    workspace_id: str,
    *,
    authority: VerticalBindingAuthority | None = None,
    limit: int = 50,
) -> list[str]:
    return [
        str(r["attempt_id"])
        for r in project_workspace_attempts(
            workspace_id, authority=authority, limit=limit
        )
        if r.get("attempt_id")
    ]


def run_ids_for_spine(
    workspace_id: str,
    *,
    authority: VerticalBindingAuthority | None = None,
    limit: int = 50,
) -> list[str]:
    return [
        str(r["run_id"])
        for r in project_workspace_runs(
            workspace_id, authority=authority, limit=limit
        )
        if r.get("run_id")
    ]


def vertical_authority_health() -> dict[str, str]:
    """Hermetic vertical Task/Attempt/Run projector mounted; empty honest."""
    return {
        "task": "ready",
        "attempt": "ready",
        "run": "ready",
    }


__all__ = [
    "attempt_ids_for_spine",
    "project_workspace_attempts",
    "project_workspace_runs",
    "project_workspace_tasks",
    "run_ids_for_spine",
    "task_ids_for_spine",
    "vertical_authority_health",
]
