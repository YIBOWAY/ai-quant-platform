"""Derive the conclusion-change set from persisted v2 verdicts — no switching.

After the parallel phase the review agent needs the list of historical entries
whose conclusion would flip if v2 became authoritative. This module computes
exactly that, and nothing else: it never flips ``GATE_V2_AUTHORITATIVE`` and it
never rewrites a verdict. The Phase2 authorization permits an automatic switch
only after the separate integration, evidence and acceptance checks pass. This
pure report cannot substitute for those checks or request redundant approval.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def derive_conclusion_changes_v2(verdicts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Partition verdicts into changed / unchanged; return review material only."""
    changed: list[dict[str, Any]] = []
    unchanged = 0
    undecidable = 0
    for index, record in enumerate(verdicts):
        parallel = record.get("verdict_parallel") or {}
        if parallel.get("v1_passed") is None:
            undecidable += 1
            continue
        if parallel.get("conclusion_changed"):
            changed.append(
                {
                    "index": index,
                    "schema_version": record.get("schema_version"),
                    "v1_passed": parallel.get("v1_passed"),
                    "v2_passed": parallel.get("v2_passed"),
                    "grade": (record.get("grade") or {}).get("grade"),
                    "tier": (record.get("tier_recommendation") or {}).get("tier"),
                    "family_digest": (record.get("family") or {}).get("family_digest"),
                }
            )
        else:
            unchanged += 1
    return {
        "switch_authorized": False,
        "changed": changed,
        "changed_count": len(changed),
        "unchanged_count": unchanged,
        "undecidable_count": undecidable,
    }


def switch_review_document(changes: Mapping[str, Any]) -> str:
    """Render evidence for the authorized, separately verified switching workflow."""
    lines = [
        "# Gate v2 parallel-phase switch review (draft)",
        "",
        "Status: **NOT switched**. v2 is observation-only; `GATE_V2_AUTHORITATIVE` is `False`.",
        "",
        f"- changed conclusions: {changes.get('changed_count', 0)}",
        f"- unchanged conclusions: {changes.get('unchanged_count', 0)}",
        f"- undecidable (no v1 verdict recorded): {changes.get('undecidable_count', 0)}",
        "",
        "## Entries whose conclusion would change",
        "",
        "| # | v1 | v2 | grade | tier | family_digest |",
        "|---|---|---|---|---|---|",
    ]
    for item in changes.get("changed", []):
        lines.append(
            f"| {item['index']} | {item['v1_passed']} | {item['v2_passed']} | "
            f"{item['grade']} | {item['tier']} | {item['family_digest']} |"
        )
    return "\n".join(lines) + "\n"
