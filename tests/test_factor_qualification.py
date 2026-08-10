from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from quant_system.factors.base import BaseFactor
from quant_system.factors.promoted_qualification import (
    PromotedFactorQualificationError,
    load_promoted_factor_qualification,
)


class _QualifiedFactor(BaseFactor):
    factor_id = "qualified_factor"
    factor_name = "Qualified Factor"
    factor_version = "1.0.0"
    default_lookback = 10
    direction = "higher_is_better"
    description = "qualification fixture"

    def _compute_values(self, frame):
        return frame["close"] * 0.0


def _bind_module(tmp_path: Path, monkeypatch, header: str) -> type[BaseFactor]:
    module_name = "quant_system.factors.library.promoted.qualification_fixture"
    source = tmp_path / "qualification_fixture.py"
    source.write_text(header + "\n", encoding="utf-8")
    module = types.ModuleType(module_name)
    module.__file__ = str(source)
    monkeypatch.setitem(sys.modules, module_name, module)
    monkeypatch.setattr(_QualifiedFactor, "__module__", module_name)
    return _QualifiedFactor


def test_auto_qualification_must_be_paper_only_and_digest_bound(
    tmp_path: Path, monkeypatch
) -> None:
    factor_cls = _bind_module(
        tmp_path,
        monkeypatch,
        "\n".join(
            [
                "# promotion_scope: paper_only",
                "# promotion_reviewer: auto",
                f"# automation_policy_digest: {'a' * 64}",
                f"# intake_contract_digest: {'b' * 64}",
            ]
        ),
    )

    result = load_promoted_factor_qualification(factor_cls)

    assert result.promotion_scope == "paper_only"
    assert result.reviewer == "auto"
    assert result.automation_policy_digest == "a" * 64
    assert result.intake_contract_digest == "b" * 64


@pytest.mark.parametrize(
    "header",
    [
        "\n".join(
            [
                "# promotion_scope: live_eligible",
                "# promotion_reviewer: auto",
                f"# automation_policy_digest: {'a' * 64}",
                f"# intake_contract_digest: {'b' * 64}",
            ]
        ),
        "\n".join(
            [
                "# promotion_scope: paper_only",
                "# promotion_reviewer: auto",
                "# automation_policy_digest: none",
                f"# intake_contract_digest: {'b' * 64}",
            ]
        ),
        "# promotion_scope: paper_only",
    ],
)
def test_invalid_or_partial_qualification_fails_closed(
    tmp_path: Path, monkeypatch, header: str
) -> None:
    factor_cls = _bind_module(tmp_path, monkeypatch, header)

    with pytest.raises(PromotedFactorQualificationError):
        load_promoted_factor_qualification(factor_cls)


def test_manual_live_qualification_has_no_machine_digests(
    tmp_path: Path, monkeypatch
) -> None:
    factor_cls = _bind_module(
        tmp_path,
        monkeypatch,
        "\n".join(
            [
                "# promotion_scope: live_eligible",
                "# promotion_reviewer: manual",
                "# automation_policy_digest: none",
                "# intake_contract_digest: none",
            ]
        ),
    )

    result = load_promoted_factor_qualification(factor_cls)

    assert result.promotion_scope == "live_eligible"
    assert result.reviewer == "manual"
    assert result.automation_policy_digest is None
    assert result.intake_contract_digest is None

