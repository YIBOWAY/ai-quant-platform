from __future__ import annotations

import hashlib
from pathlib import Path

from quant_system.d34.artifact_factor import load_d34_paper_factor_registry
from quant_system.factors.registry import build_factor_registry


def test_digest_bound_d34_factor_loads_only_through_paper_artifact_path(
    tmp_path: Path,
) -> None:
    source = b'''from __future__ import annotations
import pandas as pd
from quant_system.factors.base import BaseFactor

class GeneratedFactor(BaseFactor):
    factor_id = "d34_oracle"
    factor_name = "D34 Oracle"
    default_lookback = 2
    direction = "higher_is_better"
    description = "Known adapter oracle."

    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:
        return frame.groupby("symbol", sort=False)["close"].pct_change(
            self.lookback, fill_method=None
        )

D34_FACTOR = GeneratedFactor
'''
    path = tmp_path / "factor.py"
    path.write_bytes(source)
    digest = hashlib.sha256(source).hexdigest()

    registry = load_d34_paper_factor_registry(
        code_path=path,
        expected_code_digest=digest,
        expected_factor_id="d34_oracle",
    )

    assert registry.factor_ids() == ["d34_oracle"]
    assert registry.origins() == {"d34_oracle": "d34_artifact"}
    assert registry.create("d34_oracle", lookback=2).metadata.factor_id == "d34_oracle"
    assert "d34_oracle" not in build_factor_registry(purpose="live").factor_ids()


def test_d34_factor_loader_rejects_changed_bytes(tmp_path: Path) -> None:
    path = tmp_path / "factor.py"
    path.write_text("D34_FACTOR = object\n", encoding="utf-8")

    try:
        load_d34_paper_factor_registry(
            code_path=path,
            expected_code_digest="0" * 64,
            expected_factor_id="d34_oracle",
        )
    except ValueError as exc:
        assert str(exc) == "d34_artifact_code_digest_mismatch"
    else:
        raise AssertionError("changed artifact bytes were accepted")
