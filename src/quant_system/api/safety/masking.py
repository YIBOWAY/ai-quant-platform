from __future__ import annotations

from typing import Any

from pydantic import SecretBytes, SecretStr

_SECRET_MARKERS = ("key", "secret", "token", "password", "private")


def mask_secret_fields(payload: Any, *, _force: bool = False) -> Any:
    """Recursively mask secret values while preserving nested settings structure."""

    if isinstance(payload, SecretStr | SecretBytes):
        return "***"
    if isinstance(payload, dict):
        masked: dict[str, Any] = {}
        for key, value in payload.items():
            child_force = _force or any(marker in key.lower() for marker in _SECRET_MARKERS)
            masked[key] = mask_secret_fields(value, _force=child_force)
        return masked
    if isinstance(payload, list):
        return [mask_secret_fields(item, _force=_force) for item in payload]
    if _force:
        return "***" if payload is not None else None
    return payload
