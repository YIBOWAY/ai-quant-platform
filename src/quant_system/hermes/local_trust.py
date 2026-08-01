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
TRUST_RED_LINES: tuple[tuple[str, str], ...] = (
    ("kill_switch_off", "safety.kill_switch must be True"),
    ("live_trading_enabled", "safety.live_trading_enabled must be False"),
    ("paper_trading_off", "safety.paper_trading must be True"),
    ("dry_run_off", "safety.dry_run must be True"),
    (
        "manual_live_approval_guard_off",
        "safety.no_live_trade_without_manual_approval must be True",
    ),
    (
        "paper_pending_order_processor_enabled",
        "paper_account.auto_process_pending_orders_enabled must be False",
    ),
    (
        "live_trading_confirmation_present",
        "safety.manual_live_trading_confirmation must be empty",
    ),
)


def trust_red_line_blockers(settings: Settings) -> tuple[str, ...]:
    """Return the safety blockers that forbid trust mode. Empty == clean."""

    blockers: list[str] = []
    if settings.safety.kill_switch is not True:
        blockers.append("kill_switch_off")
    if settings.safety.live_trading_enabled is not False:
        blockers.append("live_trading_enabled")
    if settings.safety.paper_trading is not True:
        blockers.append("paper_trading_off")
    if settings.safety.dry_run is not True:
        blockers.append("dry_run_off")
    if settings.safety.no_live_trade_without_manual_approval is not True:
        blockers.append("manual_live_approval_guard_off")
    if settings.paper_account.auto_process_pending_orders_enabled is not False:
        blockers.append("paper_pending_order_processor_enabled")
    if settings.safety.manual_live_trading_confirmation != "":
        blockers.append("live_trading_confirmation_present")
    return tuple(blockers)


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
