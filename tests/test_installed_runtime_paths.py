from __future__ import annotations

from pathlib import Path

import pytest

from quant_system.config.runtime_paths import is_unconfigured_runtime_path
from quant_system.config.settings import Settings
from quant_system.hermes.intent_payload_port import (
    IntentPayloadCliSettings,
    IntentPayloadPortError,
)
from quant_system.hermes.paper_gate_port import PaperGateCliSettings
from quant_system.hermes.release_runtime import platform_runtime_root

_PATH_ENV_KEYS = (
    "QS_HERMES_ARTIFACT_FEED_PATH",
    "QS_AGENT_V02_RELEASE_PLATFORM_RUNTIME_ROOT",
    "QS_AGENT_V02_RELEASE_EVIDENCE_FILE",
    "QS_AGENT_V02_CANDIDATE_PREFLIGHT_EVIDENCE_FILE",
    "QS_AGENT_V02_CANDIDATE_FINAL_EVIDENCE_FILE",
    "QS_INTENT_PAYLOAD_PYTHON_EXECUTABLE",
    "QS_INTENT_PAYLOAD_HQA_ROOT",
)


def _clear_path_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for key in _PATH_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_unconfigured_installed_runtime_paths_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_path_environment(monkeypatch, tmp_path)
    settings = Settings()

    assert is_unconfigured_runtime_path(settings.hermes_artifacts.feed_path)
    assert is_unconfigured_runtime_path(
        settings.agent_v02_release.platform_runtime_root
    )
    assert is_unconfigured_runtime_path(settings.agent_v02_release.evidence_file)
    assert is_unconfigured_runtime_path(
        settings.candidate_admission.preflight_evidence_file
    )
    assert is_unconfigured_runtime_path(
        settings.candidate_admission.final_evidence_file
    )
    assert is_unconfigured_runtime_path(settings.intent_payload.hqa_root)

    with pytest.raises(IntentPayloadPortError, match="not configured"):
        IntentPayloadCliSettings.from_settings(settings)
    paper = PaperGateCliSettings.from_settings(settings)
    assert is_unconfigured_runtime_path(paper.python_executable)
    assert is_unconfigured_runtime_path(paper.hqa_root)
    assert is_unconfigured_runtime_path(paper.platform_root)


def test_explicit_runtime_paths_resolve_without_source_layout_inference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    platform = tmp_path / "platform"
    hqa = tmp_path / "hqa"
    artifacts = hqa / "artifacts" / "hermes-feed"
    evidence = tmp_path / "evidence"
    python = hqa / ".venv" / "bin" / "python"
    for directory in (platform, artifacts, evidence, python.parent):
        directory.mkdir(parents=True, exist_ok=True)
    python.write_bytes(b"")
    feed = artifacts / "manifest.v1.json"
    release = evidence / "release.json"
    preflight = evidence / "preflight.json"
    final = evidence / "final.json"
    for runtime_file in (feed, release, preflight, final):
        runtime_file.write_text("{}\n", encoding="utf-8")

    bindings = {
        "QS_HERMES_ARTIFACT_FEED_PATH": feed,
        "QS_AGENT_V02_RELEASE_PLATFORM_RUNTIME_ROOT": platform,
        "QS_AGENT_V02_RELEASE_EVIDENCE_FILE": release,
        "QS_AGENT_V02_CANDIDATE_PREFLIGHT_EVIDENCE_FILE": preflight,
        "QS_AGENT_V02_CANDIDATE_FINAL_EVIDENCE_FILE": final,
        "QS_INTENT_PAYLOAD_PYTHON_EXECUTABLE": python,
        "QS_INTENT_PAYLOAD_HQA_ROOT": hqa,
    }
    for key, value in bindings.items():
        monkeypatch.setenv(key, str(value))

    settings = Settings()
    intent = IntentPayloadCliSettings.from_settings(settings)
    paper = PaperGateCliSettings.from_settings(settings)

    assert settings.hermes_artifacts.feed_path == feed
    assert settings.agent_v02_release.evidence_file == release
    assert settings.candidate_admission.preflight_evidence_file == preflight
    assert settings.candidate_admission.final_evidence_file == final
    assert intent.python_executable == python
    assert intent.hqa_root == hqa
    assert paper.platform_root == platform
    assert platform_runtime_root(settings) == platform
