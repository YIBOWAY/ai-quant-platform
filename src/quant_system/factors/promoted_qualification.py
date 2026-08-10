"""Fail-closed qualification metadata for resident promoted factors."""

from __future__ import annotations

import re
import stat
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from quant_system.factors.base import BaseFactor

PromotionScope = Literal["paper_only", "live_eligible"]
PromotionReviewer = Literal["auto", "manual"]

_PROMOTED_MODULE_PREFIX = "quant_system.factors.library.promoted."
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_HEADER_RE = re.compile(
    r"^# (promotion_scope|promotion_reviewer|automation_policy_digest|"
    r"intake_contract_digest): ([^\r\n]+)$"
)
_FIELDS = {
    "promotion_scope",
    "promotion_reviewer",
    "automation_policy_digest",
    "intake_contract_digest",
}


class PromotedFactorQualificationError(RuntimeError):
    """Qualification is absent, malformed, or could leak automation to live."""


@dataclass(frozen=True)
class PromotedFactorQualification:
    promotion_scope: PromotionScope
    reviewer: PromotionReviewer
    automation_policy_digest: str | None
    intake_contract_digest: str | None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


def _optional_digest(value: str) -> str | None:
    if value == "none":
        return None
    if _DIGEST_RE.fullmatch(value) is None:
        raise PromotedFactorQualificationError("invalid qualification digest")
    return value


def _parse_qualification(fields: dict[str, str]) -> PromotedFactorQualification:
    if set(fields) != _FIELDS:
        raise PromotedFactorQualificationError(
            "promoted factor qualification header is incomplete"
        )
    scope = fields["promotion_scope"]
    reviewer = fields["promotion_reviewer"]
    if scope not in {"paper_only", "live_eligible"}:
        raise PromotedFactorQualificationError("invalid promotion_scope")
    if reviewer not in {"auto", "manual"}:
        raise PromotedFactorQualificationError("invalid promotion_reviewer")
    policy_digest = _optional_digest(fields["automation_policy_digest"])
    intake_digest = _optional_digest(fields["intake_contract_digest"])
    if reviewer == "auto":
        if scope != "paper_only" or policy_digest is None or intake_digest is None:
            raise PromotedFactorQualificationError(
                "auto qualification must be paper_only and digest-bound"
            )
    elif policy_digest is not None or intake_digest is not None:
        raise PromotedFactorQualificationError(
            "manual qualification must not claim machine-policy digests"
        )
    return PromotedFactorQualification(
        promotion_scope=scope,  # type: ignore[arg-type]
        reviewer=reviewer,  # type: ignore[arg-type]
        automation_policy_digest=policy_digest,
        intake_contract_digest=intake_digest,
    )


def load_promoted_factor_qualification(
    factor_cls: type[BaseFactor],
) -> PromotedFactorQualification:
    """Read exact generated header metadata without trusting factor globals.

    Test doubles and non-promoted modules retain the historical manual/live
    default.  Every real promoted-package module must carry all four fields.
    """

    module_name = factor_cls.__module__
    if not module_name.startswith(_PROMOTED_MODULE_PREFIX):
        return PromotedFactorQualification(
            promotion_scope="live_eligible",
            reviewer="manual",
            automation_policy_digest=None,
            intake_contract_digest=None,
        )
    module = sys.modules.get(module_name)
    raw_path = getattr(module, "__file__", None) if module is not None else None
    if not isinstance(raw_path, str) or not raw_path:
        raise PromotedFactorQualificationError("promoted factor source is unavailable")
    path = Path(raw_path)
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_size > 1_000_000:
            raise PromotedFactorQualificationError("promoted factor source is unsafe")
        prefix = path.read_text(encoding="utf-8", errors="strict")[:8_192]
    except (OSError, UnicodeError) as exc:
        raise PromotedFactorQualificationError(
            "promoted factor source cannot be read"
        ) from exc
    fields: dict[str, str] = {}
    for line in prefix.splitlines()[:32]:
        match = _HEADER_RE.fullmatch(line)
        if match is not None:
            key, value = match.groups()
            if key in fields:
                raise PromotedFactorQualificationError(
                    "duplicate promoted factor qualification field"
                )
            fields[key] = value
    return _parse_qualification(fields)


__all__ = [
    "PromotedFactorQualification",
    "PromotedFactorQualificationError",
    "PromotionReviewer",
    "PromotionScope",
    "load_promoted_factor_qualification",
]

