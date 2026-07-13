from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from quant_system.cli import app

runner = CliRunner()

SOURCE = """from quant_system.factors.base import BaseFactor, FactorMetadata


class ExternalCandidateFactor(BaseFactor):
    factor_id = "external_candidate_factor"
    factor_name = "External Candidate Factor"
    factor_version = "0.1.0-candidate"
    description = "Externally generated source-file candidate."

    @property
    def metadata(self):
        return FactorMetadata(
            factor_id=self.factor_id,
            factor_name=self.factor_name,
            factor_version=self.factor_version,
            description=self.description,
            lookback=self.lookback,
            direction="higher_is_better",
        )

    def _compute_values(self, frame):
        return frame.groupby("symbol")["close"].pct_change(self.lookback)
"""


def _kv_output(text: str) -> dict[str, str]:
    pairs = {}
    for token in text.strip().split():
        key, _, value = token.partition("=")
        pairs[key] = value
    return pairs


def test_agent_propose_factor_accepts_source_file_and_keeps_candidate_pending(tmp_path):
    source_file = tmp_path / "factor_src.py"
    source_file.write_text(SOURCE, encoding="utf-8")
    output_dir = tmp_path / "agent_run"

    result = runner.invoke(
        app,
        [
            "agent",
            "propose-factor",
            "--goal",
            "external source factor",
            "--source-file",
            str(source_file),
            "--agent-output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    parsed = _kv_output(result.output)
    assert parsed["candidate_id"].startswith("factor-external_source_factor-")
    assert parsed["status"] == "pending"
    candidate_path = Path(parsed["path"])
    metadata_path = Path(parsed["metadata"])
    assert candidate_path.read_text(encoding="utf-8") == SOURCE
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["status"] == "pending"
    assert metadata["source"] == "agent_factor_proposal"
    assert metadata["generator"] == "external-source"
    assert metadata["source_file_name"] == "factor_src.py"
