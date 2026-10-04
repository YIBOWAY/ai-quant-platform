"""One cross-version warning token, written by the backend and tested by the UI."""

from __future__ import annotations

import json
import re
from pathlib import Path

from quant_system.config.settings import load_settings
from quant_system.execution import assistant_remote
from quant_system.execution import strategy_replacement as replacement
from quant_system.research import paper_evaluation, strategy_library
from tests.test_strategy_library import _definition
from tests.test_strategy_replacement import scenario  # noqa: F401

_FRONTEND = Path("src/frontend")
_PANEL = _FRONTEND / "components/research/StrategyLibraryPanel.tsx"
_REPORT_VIEW = _FRONTEND / "components/research/ResearchEvaluationView.tsx"
_STRING_CONSTANT = re.compile(r"(\w+)\s*=\s*\"(cumulative_sleeve_history_\w+)\"")


def _frontend_sources() -> dict[Path, str]:
    return {
        path: path.read_text(encoding="utf-8")
        for path in sorted((_FRONTEND / "components").rglob("*.tsx"))
        + sorted((_FRONTEND / "lib").rglob("*.ts"))
        if path.is_file()
    }


def _scope_constant_names(sources: dict[Path, str], value: str) -> set[str]:
    return {
        name
        for text in sources.values()
        for name, declared in _STRING_CONSTANT.findall(text)
        if declared == value
    }


def _consumes_scope(text: str, canonical: str, names: set[str]) -> bool:
    """The literal inline, or a frontend constant declared with exactly that value."""
    return canonical in text or any(name in text for name in names)


def test_owner_ui_reads_the_exact_token_the_backend_writes():
    canonical = replacement.PERFORMANCE_SCOPE_ACROSS_VERSIONS
    assert canonical == paper_evaluation.PERFORMANCE_SCOPE_ACROSS_VERSIONS
    sources = _frontend_sources()
    names = _scope_constant_names(sources, canonical)
    assert _consumes_scope(sources[_PANEL], canonical, names)
    assert _consumes_scope(sources[_REPORT_VIEW], canonical, names)
    assert not any(
        replacement.LEGACY_PERFORMANCE_SCOPE_ACROSS_VERSIONS in text
        for text in sources.values()
    ), "the pre-unification spelling must not return to the frontend"


def test_replacement_flow_emits_only_the_canonical_scope_token(scenario):  # noqa: F811
    settings, storage, repo, sleeve, config, definitions, request = scenario
    receipt = replacement.replace_verified_strategy(settings, **request)
    current = storage.load_sleeve(sleeve.sleeve_id)
    book = {row["candidate_id"]: row for row in assistant_remote.load_book(settings)["candidates"]}
    assert receipt["performance_scope"] == replacement.PERFORMANCE_SCOPE_ACROSS_VERSIONS
    assert current.metadata["performance_scope"] == replacement.PERFORMANCE_SCOPE_ACROSS_VERSIONS
    assert book["new"]["performance_scope"] == replacement.PERFORMANCE_SCOPE_ACROSS_VERSIONS
    assert replacement.LEGACY_PERFORMANCE_SCOPE_ACROSS_VERSIONS not in json.dumps(receipt)
    assert replacement.LEGACY_PERFORMANCE_SCOPE_ACROSS_VERSIONS not in json.dumps(
        current.metadata
    )
    assert replacement.LEGACY_PERFORMANCE_SCOPE_ACROSS_VERSIONS not in json.dumps(book["new"])


def test_candidate_kept_with_the_pre_unification_token_is_still_reported(tmp_path):
    settings = load_settings()
    settings.data.data_dir = tmp_path
    entry = strategy_library._save_definition(settings, _definition(), {"type": "study"})
    directory = strategy_library._directory(settings, entry["strategy_id"])
    strategy_library._write(directory / "entry.json", {**entry, "candidate_id": "candidate-legacy"})
    assistant_remote.save_book(
        settings,
        {
            "candidates": [
                {
                    "candidate_id": "candidate-legacy",
                    "status": "superseded",
                    "sleeve_id": "sleeve-legacy",
                    "replaced_by": "candidate-new",
                    "replacement_id": "replacement-" + "a" * 24,
                    "performance_scope": replacement.LEGACY_PERFORMANCE_SCOPE_ACROSS_VERSIONS,
                }
            ],
            "requests": [],
        },
    )
    value = strategy_library.read_strategy(settings, entry["strategy_id"])
    assert value["status"] == "superseded" and value["sleeve_id"] == "sleeve-legacy"
    assert value["performance_scope"] == replacement.PERFORMANCE_SCOPE_ACROSS_VERSIONS
