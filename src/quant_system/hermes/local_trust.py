"""Solo-owner local trust mode: bypass identity ritual, never safety.

Trust mode substitutes the identity-ritual half of candidate admission
(admission records, preflight evidence, three-repo runtime digests, clean
checkout, connector ceremony) with a synthetic in-memory decision.  It never
substitutes trading safety: every red line below is re-asserted before the
bypass may apply, and a violation silently falls back to the full fail-closed
ritual gate, which then closes on the same safety blockers.  Trust mode can
therefore never be the reason a write path opens while an unsafe flag is set.

The checks use only plain ``settings`` attribute reads — no I/O and no
exceptions — so this module cannot fail open.
"""

from __future__ import annotations

import hashlib

from quant_system.config.settings import Settings

#: Documented, ordered red lines. Each entry: (blocker string, description).
#: Deliberately minimal: live trading OFF is the only real-money boundary.
#: kill_switch / paper / dry_run are research-mode toggles the solo owner may
#: flip freely; the settings validator independently requires an explicit
#: confirmation phrase before live trading can ever be enabled.
TRUST_RED_LINES: tuple[tuple[str, str], ...] = (
    ("live_trading_enabled", "safety.live_trading_enabled must be False"),
)


def trust_red_line_blockers(settings: Settings) -> tuple[str, ...]:
    """Return the safety blockers that forbid trust mode. Empty == clean."""

    if settings.safety.live_trading_enabled is not False:
        return ("live_trading_enabled",)
    return ()


def trust_mode_active(settings: Settings) -> bool:
    """True only when the flag is set and every red line holds."""

    local_trust = getattr(settings, "local_trust", None)
    if local_trust is None or local_trust.mode is not True:
        return False
    return not trust_red_line_blockers(settings)


def trust_mode_requested_but_refused(settings: Settings) -> tuple[str, ...]:
    """Red-line blockers when the operator asked for trust mode in vain."""

    local_trust = getattr(settings, "local_trust", None)
    if local_trust is None or local_trust.mode is not True:
        return ()
    return trust_red_line_blockers(settings)


def trust_runtime_digest(settings: Settings) -> str:
    """Stable synthetic runtime identity used only under trust mode.

    Both the connector (liveness acquire) and the composer readiness probe
    derive the same digest from the configured workspace id, so liveness
    matching still works without requiring a clean git checkout or the
    frozen boot digest.  It is deliberately NOT a git commit digest and can
    never satisfy the real release/candidate identity comparisons.
    """

    payload = (
        b"agent-v0.2-local-trust\x00"
        + settings.agent_v02_release.workspace_id.encode("utf-8")
        + b"\x00"
    )
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "TRUST_RED_LINES",
    "trust_mode_active",
    "trust_mode_requested_but_refused",
    "trust_red_line_blockers",
    "trust_runtime_digest",
]
