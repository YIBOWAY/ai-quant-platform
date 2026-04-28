from __future__ import annotations

from typing import Any

_SECRET_MARKERS = ("key", "secret", "token", "password", "private")


def mask_secret_fields(payload: Any) -> Any:
    """Recursively mask values whose field names look credential-like."""

    if isinstance(payload, dict):
        masked: dict[str, Any] = {}
        for key, value in payload.items():
            if any(marker in key.lower() for marker in _SECRET_MARKERS):
                masked[key] = "***" if value is not None else None
            else:
                masked[key] = mask_secret_fields(value)
        return masked
    if isinstance(payload, list):
        return [mask_secret_fields(item) for item in payload]
    return payload
