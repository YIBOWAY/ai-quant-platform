from pathlib import Path


def test_paper_run_form_respects_replay_safety_lock() -> None:
    form = Path("src/frontend/components/forms/PaperRunForm.tsx").read_text(
        encoding="utf-8"
    )
    page = Path("src/frontend/app/paper-trading/page.tsx").read_text(encoding="utf-8")

    assert "replayKillSwitch = true" in form
    assert "replayKillSwitch?: boolean;" in form
    assert "enable_kill_switch: false" in form
    assert "disabled={!isHydrated || mutation.isPending || replayKillSwitch}" in form
    assert "replayKillSwitch ? text.killSwitchEnabled : text.killSwitchDisabled" in form
    assert "replayKillSwitch ? text.readOnly : text.replayReady" in form
    assert "text.replayLocked" in form

    assert "replayKillSwitch={health.safety?.kill_switch !== false}" in page
