from __future__ import annotations

import copy

import pytest

from quant_system.ops import restart_stack
from quant_system.ops.common import ReleaseOperationError


def _live_settings_document() -> dict[str, object]:
    common = {
        "kill_switch": True,
        "live_trading_enabled": False,
        "dry_run": True,
        "paper_trading": True,
    }
    return {
        "safety": {
            **common,
            "bind_address": "127.0.0.1",
        },
        "settings": {"safety": dict(common)},
    }


def test_live_settings_accepts_model_safety_without_bind_address() -> None:
    assert restart_stack.validate_live_settings_observation(_live_settings_document()) == {
        "kill_switch": True,
        "live_trading_enabled": False,
        "dry_run": True,
        "paper_trading": True,
        "bind_address": "127.0.0.1",
    }


@pytest.mark.parametrize(
    ("layer", "field", "unsafe_value"),
    (
        ("public", "kill_switch", False),
        ("public", "live_trading_enabled", True),
        ("public", "dry_run", False),
        ("public", "paper_trading", False),
        ("nested", "kill_switch", False),
        ("nested", "live_trading_enabled", True),
        ("nested", "dry_run", False),
        ("nested", "paper_trading", False),
    ),
)
def test_live_settings_rejects_unsafe_common_fields_in_both_layers(
    layer: str,
    field: str,
    unsafe_value: object,
) -> None:
    document = _live_settings_document()
    safety = (
        document["safety"] if layer == "public" else document["settings"]["safety"]  # type: ignore[index]
    )
    assert isinstance(safety, dict)
    safety[field] = unsafe_value

    with pytest.raises(ReleaseOperationError, match=field):
        restart_stack.validate_live_settings_observation(document)

    missing = copy.deepcopy(_live_settings_document())
    missing_safety = (
        missing["safety"] if layer == "public" else missing["settings"]["safety"]  # type: ignore[index]
    )
    assert isinstance(missing_safety, dict)
    del missing_safety[field]
    with pytest.raises(ReleaseOperationError, match=field):
        restart_stack.validate_live_settings_observation(missing)


@pytest.mark.parametrize("bind_address", (None, "0.0.0.0"))
def test_live_settings_requires_public_loopback_bind(bind_address: str | None) -> None:
    document = _live_settings_document()
    public = document["safety"]
    assert isinstance(public, dict)
    if bind_address is None:
        del public["bind_address"]
    else:
        public["bind_address"] = bind_address

    with pytest.raises(ReleaseOperationError, match="bind_address"):
        restart_stack.validate_live_settings_observation(document)


def test_live_settings_rejects_conflicting_optional_nested_bind() -> None:
    document = _live_settings_document()
    nested = document["settings"]["safety"]  # type: ignore[index]
    assert isinstance(nested, dict)
    nested["bind_address"] = "0.0.0.0"

    with pytest.raises(ReleaseOperationError, match="bind_address"):
        restart_stack.validate_live_settings_observation(document)
