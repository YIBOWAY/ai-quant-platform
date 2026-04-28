import json
import os
from pathlib import Path

from typer.testing import CliRunner

from quant_system.agent.candidate_pool import CandidatePool
from quant_system.agent.llm.stub import StubLLMClient
from quant_system.agent.runner import AgentRunner
from quant_system.agent.safety import SafetyGate
from quant_system.cli import app
from quant_system.experiments.models import ExperimentConfig
from quant_system.factors.registry import build_default_factor_registry

runner = CliRunner()


class MaliciousLLM:
    def generate(
        self,
        prompt: str,
        *,
        system: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        return 'import os\nos.system("rm -rf /")\nclass CandidateFactor:\n    pass\n'


def test_safety_gate_default_denies_promotion(tmp_path) -> None:
    pool = CandidatePool(tmp_path)
    artifact = pool.write_candidate(
        task_id="task-001",
        goal="candidate factor",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="class CandidateFactor:\n    pass\n",
    )

    gate = SafetyGate(pool.candidates_dir)

    assert gate.allow_promotion(artifact.candidate_id) is False


def test_safety_gate_rejects_path_traversal_candidate_id(tmp_path) -> None:
    outside_dir = Path(tmp_path, "agent", "escape")
    outside_dir.mkdir(parents=True)
    (outside_dir / "approved.lock").write_text("not a candidate", encoding="utf-8")

    gate = SafetyGate(Path(tmp_path, "agent", "candidates"))

    assert gate.allow_promotion("../escape") is False


def test_audit_log_records_all_steps(tmp_path) -> None:
    result = AgentRunner(output_dir=tmp_path, llm=StubLLMClient()).propose_factor(
        goal="low-vol momentum",
        universe=["SPY", "QQQ"],
    )

    audit_files = list(Path(tmp_path, "agent", "audit").glob("*.jsonl"))
    assert len(audit_files) == 1
    events = [
        json.loads(line)["event_type"]
        for line in audit_files[0].read_text(encoding="utf-8").splitlines()
    ]
    assert {"task", "tool_call", "candidate_written"}.issubset(events)
    assert result.path.name == "factor.py.candidate"


def test_factor_proposal_does_not_exec_generated_code(tmp_path, monkeypatch) -> None:
    def fail_if_called(command: str) -> int:
        raise AssertionError(f"os.system was called with {command!r}")

    monkeypatch.setattr(os, "system", fail_if_called)

    artifact = AgentRunner(output_dir=tmp_path, llm=MaliciousLLM()).propose_factor(
        goal="try to execute shell",
        universe=["SPY"],
    )

    assert artifact.path.name.endswith(".candidate")
    assert 'os.system("rm -rf /")' in artifact.path.read_text(encoding="utf-8")


def test_candidate_metadata_safety_block(tmp_path) -> None:
    artifact = AgentRunner(output_dir=tmp_path, llm=StubLLMClient()).propose_factor(
        goal="low-vol momentum",
        universe=["SPY", "QQQ"],
    )

    metadata = json.loads(artifact.metadata_path.read_text(encoding="utf-8"))

    assert metadata["safety"] == {
        "auto_promotion": False,
        "requires_human_review": True,
        "review_status": "pending",
    }


def test_review_approve_creates_lock_only(tmp_path) -> None:
    proposal = runner.invoke(
        app,
        [
            "agent",
            "propose-factor",
            "--goal",
            "low-vol momentum",
            "--universe",
            "SPY,QQQ",
            "--output-dir",
            str(tmp_path),
        ],
    )
    assert proposal.exit_code == 0
    candidate_dirs = list(Path(tmp_path, "agent", "candidates").iterdir())
    assert len(candidate_dirs) == 1
    candidate_id = candidate_dirs[0].name

    review = runner.invoke(
        app,
        [
            "agent",
            "review",
            "--candidate-id",
            candidate_id,
            "--decision",
            "approve",
            "--note",
            "manual review passed",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert review.exit_code == 0
    assert Path(tmp_path, "agent", "candidates", candidate_id, "approved.lock").exists()
    assert candidate_id not in build_default_factor_registry().factor_ids()


def test_stub_llm_is_deterministic() -> None:
    client = StubLLMClient()

    first = client.generate(
        "propose factor",
        system="research assistant",
        max_tokens=512,
        temperature=0.0,
    )
    second = client.generate(
        "propose factor",
        system="research assistant",
        max_tokens=512,
        temperature=0.0,
    )

    assert first == second


def test_propose_experiment_outputs_valid_experiment_config(tmp_path) -> None:
    artifact = AgentRunner(output_dir=tmp_path, llm=StubLLMClient()).propose_experiment(
        goal="test a momentum and volatility blend",
        universe=["SPY", "QQQ"],
    )

    payload = json.loads(artifact.path.read_text(encoding="utf-8"))
    config = ExperimentConfig.model_validate(payload)

    assert config.symbols == ["SPY", "QQQ"]
    assert config.factor_blend.factors
