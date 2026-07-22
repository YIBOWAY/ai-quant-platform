from __future__ import annotations

import stat

from typer.testing import CliRunner

from quant_system.api.safety.local_session import bootstrap_token_path
from quant_system.cli import app

runner = CliRunner()


def test_owner_bootstrap_token_cli_uses_owner_file_and_rotates(tmp_path) -> None:
    first = runner.invoke(
        app,
        ["owner-bootstrap-token", "--data-dir", str(tmp_path)],
    )
    assert first.exit_code == 0
    first_token = first.stdout.strip()
    assert len(first_token) >= 32

    token_path = bootstrap_token_path(tmp_path)
    assert token_path.read_text(encoding="ascii") == first_token
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600

    replay = runner.invoke(
        app,
        ["owner-bootstrap-token", "--data-dir", str(tmp_path)],
    )
    assert replay.exit_code == 0
    assert replay.stdout.strip() == first_token

    rotated = runner.invoke(
        app,
        ["owner-bootstrap-token", "--data-dir", str(tmp_path), "--rotate"],
    )
    assert rotated.exit_code == 0
    assert rotated.stdout.strip() != first_token
    assert token_path.read_text(encoding="ascii") == rotated.stdout.strip()
