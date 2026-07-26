from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from quant_system.hermes.paper_gate_source_evidence import (
    PaperGateSourceEvidenceError,
    read_verified_gate1_source,
)


def test_exact_utf8_source_is_digest_verified(tmp_path: Path) -> None:
    source = tmp_path / "reversal_factor.py"
    payload = (
        b"# Short-term reversal / long-term momentum\n"
        b"def factor(short_return: float, long_return: float) -> float:\n"
        b"    return -short_return + long_return\n"
    )
    source.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    evidence = read_verified_gate1_source(
        source_file_ref=str(source),
        reviewed_source_sha256=digest,
    )

    assert evidence.source_utf8.encode() == payload
    assert evidence.byte_length == len(payload)
    assert evidence.observed_source_sha256 == digest
    assert evidence.to_public_dict(
        gate_id="gate-paper-1",
        workspace_id="workspace-root",
    )["source_utf8"] == payload.decode()


def test_source_digest_drift_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "factor.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    source.write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(
        PaperGateSourceEvidenceError,
        match="no longer match",
    ) as error:
        read_verified_gate1_source(
            source_file_ref=str(source),
            reviewed_source_sha256=digest,
        )
    assert error.value.code == "paper_gate_source_digest_mismatch"


def test_symlink_leaf_and_non_python_source_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "factor.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    alias = tmp_path / "alias.py"
    alias.symlink_to(source)

    with pytest.raises(PaperGateSourceEvidenceError) as symlink_error:
        read_verified_gate1_source(
            source_file_ref=str(alias),
            reviewed_source_sha256=digest,
        )
    assert symlink_error.value.code == "paper_gate_source_unavailable"

    text = tmp_path / "factor.txt"
    text.write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(PaperGateSourceEvidenceError) as suffix_error:
        read_verified_gate1_source(
            source_file_ref=str(text),
            reviewed_source_sha256=hashlib.sha256(text.read_bytes()).hexdigest(),
        )
    assert suffix_error.value.code == "paper_gate_source_invalid"


def test_parent_symlink_is_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    source = real / "factor.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)

    with pytest.raises(PaperGateSourceEvidenceError) as error:
        read_verified_gate1_source(
            source_file_ref=str(alias / "factor.py"),
            reviewed_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        )
    assert error.value.code == "paper_gate_source_unavailable"


def test_non_utf8_and_oversized_source_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "factor.py"
    source.write_bytes(b"\xff\xfe")
    with pytest.raises(PaperGateSourceEvidenceError) as utf8_error:
        read_verified_gate1_source(
            source_file_ref=str(source),
            reviewed_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        )
    assert utf8_error.value.code == "paper_gate_source_not_utf8"

    source.write_bytes(b"x" * (1_048_576 + 1))
    with pytest.raises(PaperGateSourceEvidenceError) as size_error:
        read_verified_gate1_source(
            source_file_ref=str(source),
            reviewed_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        )
    assert size_error.value.code == "paper_gate_source_invalid"


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="requires O_NOFOLLOW")
def test_no_follow_contract_is_available_on_release_platform() -> None:
    assert os.O_NOFOLLOW > 0
