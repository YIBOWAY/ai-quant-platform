from quant_system.config.settings import SafetySettings
from quant_system.execution.paper_observation import (
    hung_observation_allows_fill,
    hung_observation_open_for_sleeve,
    hung_sleeve_eligible,
)


def test_hung_observation_open_when_live_is_killed() -> None:
    settings = type("S", (), {"safety": SafetySettings()})()

    assert hung_observation_allows_fill(settings, emergency_stop=False) is True
    assert hung_observation_allows_fill(settings, emergency_stop=True) is False
    assert hung_observation_allows_fill(settings, emergency_stop=False, authority_available=False) is False
    assert hung_observation_allows_fill(settings, emergency_stop=False, sleeve_eligible=False) is False


def test_hung_observation_closed_when_live_enabled() -> None:
    settings = type(
        "S",
        (),
        {
            "safety": SafetySettings(
                live_trading_enabled=True,
                manual_live_trading_confirmation="I_UNDERSTAND_THIS_ENABLES_LIVE_TRADING",
            )
        },
    )()

    assert hung_observation_allows_fill(settings, emergency_stop=False) is False


def test_hung_observation_closed_when_flag_off() -> None:
    settings = type(
        "S",
        (),
        {"safety": SafetySettings(paper_observation_enabled=False)},
    )()

    assert hung_observation_allows_fill(settings, emergency_stop=False) is False


def test_hung_observation_closed_when_authority_is_unknown() -> None:
    settings = type("S", (), {"safety": SafetySettings()})()
    sleeve = type(
        "Sleeve",
        (),
        {
            "mode": "allocated",
            "status": "running",
            "metadata": {
                "automation_managed": True,
                "promotion_scope": "paper_only",
                "source_digest": "a" * 64,
            },
        },
    )()

    assert hung_sleeve_eligible(sleeve) is True
    assert (
        hung_observation_open_for_sleeve(
            settings,
            sleeve,
            {
                "emergency_stop": False,
                "authority_available": False,
                "blockers": ["d34_authority_unavailable"],
            },
        )
        is False
    )


def test_manual_sleeve_is_not_hung_eligible() -> None:
    sleeve = type(
        "Sleeve",
        (),
        {"mode": "allocated", "status": "running", "metadata": {}},
    )()

    assert hung_sleeve_eligible(sleeve) is False


def test_preview_seed_sleeve_is_not_hung_eligible() -> None:
    sleeve = type(
        "Sleeve",
        (),
        {
            "mode": "allocated",
            "status": "running",
            "metadata": {
                "automation_managed": True,
                "promotion_scope": "paper_only",
                "preview_label": "hung_observation_demo",
                "official_observation": False,
                "fossil": True,
            },
        },
    )()

    assert hung_sleeve_eligible(sleeve) is False


def test_digest_less_automation_sleeve_is_not_hung_eligible() -> None:
    sleeve = type(
        "Sleeve",
        (),
        {
            "mode": "allocated",
            "status": "running",
            "metadata": {
                "automation_managed": True,
                "promotion_scope": "paper_only",
            },
        },
    )()

    assert hung_sleeve_eligible(sleeve) is False
