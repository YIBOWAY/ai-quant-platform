from __future__ import annotations

import plistlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_launchagent_is_supervised_without_fixed_smoke_input() -> None:
    wrapper = (ROOT / "scripts" / "run_agent_v02_connector.sh").read_text(encoding="utf-8")
    template = plistlib.loads(
        (ROOT / "scripts" / "launchd" / "com.aiquant.agent-v02-connector.plist.template")
        .read_bytes()
        .replace(b"__ROOT__", str(ROOT).encode("utf-8"))
    )

    assert "--mode supervised_dispatch" in wrapper
    assert "--poll-interval-seconds" in wrapper
    assert "--fixed-input" not in wrapper
    assert 'PYTHONPATH="$ROOT/src' in wrapper
    assert template["RunAtLoad"] is True
    assert template["KeepAlive"] is True
    assert template["ProgramArguments"] == [str(ROOT / "scripts" / "run_agent_v02_connector.sh")]


def test_installer_precreates_owner_only_logs_and_is_replayable() -> None:
    installer = (ROOT / "scripts" / "install_agent_v02_connector_launchagent.sh").read_text(
        encoding="utf-8"
    )

    assert "install -d -m 700" in installer
    assert "install -m 600 /dev/null" in installer
    assert "launchctl bootout" in installer
    assert "launchctl bootstrap" in installer
