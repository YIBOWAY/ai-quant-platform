"""G4: the switch derivation reads a ledger and writes nothing.

``derive_conclusion_changes_v2`` / ``switch_review_document`` are the only
consumers of the persisted v2 verdicts. They must derive the conclusion-change
list from a **read-only** view of the ledger, never touch a production ledger,
and never flip the switch.
"""

from __future__ import annotations

import ast
import copy
from pathlib import Path

from quant_system.research import gate_v2 as g
from quant_system.research.gate_v2 import switch

_SWITCH_SOURCE = Path(switch.__file__).read_text(encoding="utf-8")

# Calls that would mutate or create anything on disk / in a ledger.
_MUTATORS = {
    "open",
    "fdopen",
    "write",
    "write_text",
    "write_bytes",
    "dump",
    "dumps",
    "append_verdict_v2",
    "replace",
    "unlink",
    "remove",
    "mkdir",
    "makedirs",
    "fsync",
    "flock",
}


def _verdict(*, v1: bool | None, v2: bool, index: int) -> dict:
    changed = v1 is not None and bool(v1) != bool(v2)
    return {
        "schema_version": g.GATE_V2_SCHEMA_VERSION,
        "verdict_parallel": {
            "v1_passed": v1,
            "v2_passed": v2,
            "conclusion_changed": changed,
        },
        "grade": {"grade": g.GRADE_SUPPORTED if v2 else g.GRADE_INSUFFICIENT},
        "tier_recommendation": {"tier": "T2" if v2 else "T0"},
        "family": {"family_digest": f"{index:064d}"},
    }


def _ledger() -> list[dict]:
    return [
        _verdict(v1=True, v2=False, index=0),  # changed: v1 pass -> v2 fail
        _verdict(v1=True, v2=True, index=1),  # unchanged
        _verdict(v1=None, v2=True, index=2),  # undecidable (no v1 verdict)
        _verdict(v1=False, v2=True, index=3),  # changed: v1 fail -> v2 pass
    ]


def test_the_change_set_is_partitioned_from_the_ledger() -> None:
    report = g.derive_conclusion_changes_v2(_ledger())
    assert report["switch_authorized"] is False
    assert report["changed_count"] == 2
    assert report["unchanged_count"] == 1
    assert report["undecidable_count"] == 1
    assert [item["index"] for item in report["changed"]] == [0, 3]


def test_each_changed_entry_carries_its_review_columns() -> None:
    report = g.derive_conclusion_changes_v2(_ledger())
    entry = report["changed"][1]  # the second changed row == ledger index 3
    assert entry["index"] == 3
    assert entry["v1_passed"] is False
    assert entry["v2_passed"] is True
    assert entry["grade"] == g.GRADE_SUPPORTED
    assert entry["tier"] == "T2"
    assert entry["family_digest"] == f"{3:064d}"
    assert entry["schema_version"] == g.GATE_V2_SCHEMA_VERSION


def test_an_empty_ledger_is_valid_and_changes_nothing() -> None:
    report = g.derive_conclusion_changes_v2([])
    assert report == {
        "switch_authorized": False,
        "changed": [],
        "changed_count": 0,
        "unchanged_count": 0,
        "undecidable_count": 0,
    }


def test_the_ledger_is_read_only_and_never_mutated() -> None:
    ledger = _ledger()
    before = copy.deepcopy(ledger)
    g.derive_conclusion_changes_v2(ledger)
    assert ledger == before


def test_the_derivation_is_deterministic() -> None:
    assert g.derive_conclusion_changes_v2(_ledger()) == g.derive_conclusion_changes_v2(_ledger())


def test_the_module_contains_no_writer_or_io_call() -> None:
    tree = ast.parse(_SWITCH_SOURCE)
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)
    assert called.isdisjoint(_MUTATORS), called & _MUTATORS
    assert "Path" not in _SWITCH_SOURCE
    assert "append_verdict_v2" not in _SWITCH_SOURCE
    # No assignment to a switch, anywhere: the derivation never flips one.
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        for target in targets:
            name = getattr(target, "id", None) or getattr(target, "attr", None) or ""
            assert "AUTHORITATIVE" not in name and "ENABLED" not in name, ast.dump(target)


def test_the_review_document_is_a_not_switched_stub() -> None:
    document = g.switch_review_document(g.derive_conclusion_changes_v2(_ledger()))
    assert document.startswith("# Gate v2 parallel-phase switch review (draft)")
    assert "NOT switched" in document
    assert "changed conclusions: 2" in document
    assert "unchanged conclusions: 1" in document
    assert "undecidable (no v1 verdict recorded): 1" in document
    assert "| 0 | True | False |" in document
    assert "| 3 | False | True |" in document
    assert document.endswith("\n")
