from __future__ import annotations

from pathlib import Path

from quant_system.agent.paths import (
    PLATFORM_REPO_ROOT,
    resolve_agent_output_dir,
    resolve_candidates_dir,
    resolve_legacy_candidates_dir,
)


def test_agent_root_has_one_repo_default_and_explicit_env_override(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("QS_AGENT_OUTPUT_DIR", raising=False)
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path / "must-not-move-agent-root"))
    monkeypatch.chdir(tmp_path)
    assert resolve_agent_output_dir() == (
        PLATFORM_REPO_ROOT / "data" / "agent_run"
    )
    monkeypatch.setenv("QS_AGENT_OUTPUT_DIR", str(tmp_path / "agent-output"))
    assert resolve_agent_output_dir() == tmp_path / "agent-output"
    assert resolve_legacy_candidates_dir() == (
        PLATFORM_REPO_ROOT / "data" / "agent" / "candidates"
    )


def test_resolve_candidates_dir_appends_agent_candidates_once(tmp_path) -> None:
    agent = tmp_path / "agent-output"
    assert resolve_candidates_dir(agent) == agent / "agent" / "candidates"


def test_explicit_relative_agent_output_dir_is_repo_anchored(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("QS_AGENT_OUTPUT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    resolved = resolve_agent_output_dir("relative-agent-root")
    assert resolved == PLATFORM_REPO_ROOT / "relative-agent-root"
    assert resolved.is_absolute()


def test_active_candidate_consumers_do_not_hardcode_agent_run_paths() -> None:
    """Source regression: no CWD-relative or QS_DATA_DIR-derived candidate roots."""
    roots = [
        Path("src/quant_system/cli.py"),
        Path("src/quant_system/api/routes"),
        Path("src/quant_system/agent"),
        Path("src/frontend/playwright.config.ts"),
    ]
    forbidden_substrings = (
        'Path("data/agent_run")',
        "Path('data/agent_run')",
        '="data/agent_run"',
        "='data/agent_run'",
        '="data/agent_run/agent/candidates"',
        "='data/agent_run/agent/candidates'",
        "AGENT_CANDIDATES_DIR",
    )
    # QS_DATA_DIR must never appear as a candidate-root derivation source in
    # active agent/candidate consumers (playwright may still set it for general data).
    qs_data_candidate_patterns = (
        "QS_DATA_DIR",  # checked only under agent + routes + cli, not playwright
    )

    offenders: list[str] = []
    for root in roots:
        paths = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in paths:
            if not path.is_file():
                continue
            if path.suffix not in {".py", ".ts", ".tsx"}:
                continue
            # paths.py is the single allowed definition of the repo default.
            if path.as_posix().endswith("quant_system/agent/paths.py"):
                continue
            text = path.read_text(encoding="utf-8")
            for needle in forbidden_substrings:
                if needle in text:
                    offenders.append(f"{path}: contains {needle!r}")
            if path.as_posix().endswith("playwright.config.ts"):
                continue
            for needle in qs_data_candidate_patterns:
                if needle not in text:
                    continue
                # Allow comments/help text about QS_DATA_DIR for non-candidate
                # output dirs (experiment/report). Flag only candidate-adjacent use.
                for line_no, line in enumerate(text.splitlines(), start=1):
                    if "QS_DATA_DIR" not in line:
                        continue
                    lowered = line.lower()
                    if (
                        "candidate" in lowered
                        or "agent_run" in lowered
                        or "agent_output" in lowered
                    ):
                        offenders.append(
                            f"{path}:{line_no}: QS_DATA_DIR near candidate context: {line.strip()}"
                        )

    assert not offenders, "hardcoded/derived candidate roots:\n" + "\n".join(offenders)
