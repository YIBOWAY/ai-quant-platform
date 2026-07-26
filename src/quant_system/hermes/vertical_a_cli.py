"""Fixed Platform CLI port for one durable Vertical-A Futu read-only request.

The HQA/Hermes canonical Run invokes this module only after it knows the exact
Platform Session and Hermes Run references.  The command commits the provider
attempt before constructing or calling the Futu facade.  Every uncertain
post-claim failure is sealed ``outcome_unknown`` and is never auto-replayed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer

from quant_system.config.settings import load_settings
from quant_system.hermes.agent_workspace import PlatformAgentWorkspace
from quant_system.hermes.agent_workspace_actions import (
    BindOptionsVerticalA,
    WorkspaceRef,
    canonical_auth_envelope_digest,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.dark_identity_profile import PLATFORM_WORKSPACE_ID
from quant_system.hermes.vertical_a_durable_authority import (
    PostgresVerticalAAuthority,
    VerticalADurableAuthorityError,
)
from quant_system.hermes.vertical_ro_provider import (
    VerticalRoProviderError,
    build_futu_ro_facade,
)

app = typer.Typer(
    help="Execute one exact durable Vertical-A Futu read-only request.",
    no_args_is_help=True,
)

_INGRESS_CONTRACT = "agent-v0.2-options-research/v1"
_INGRESS_FIELDS = frozenset({"ticker", "expiry", "strike", "goal_note"})
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_TICKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,31}$")
_EXPIRY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_PLATFORM_CONTEXT = {
    "command_id": "HERMES_PLATFORM_COMMAND_ID",
    "platform_session_id": "HERMES_PLATFORM_SESSION_ID",
    "hermes_run_id": "HERMES_PLATFORM_RUN_ID",
    "hermes_session_id": "HERMES_PLATFORM_MANAGED_SESSION_ID",
}


class VerticalAIngressError(RuntimeError):
    """Stable, secret-free refusal from the Hermes natural-language tool port."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@app.callback()
def main() -> None:
    """Expose an explicit, stable command group for HQA/Hermes."""


def _emit(payload: dict[str, object], *, stderr: bool = False) -> None:
    target = sys.stderr if stderr else sys.stdout
    target.write(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
    target.flush()


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _platform_context() -> dict[str, str]:
    context: dict[str, str] = {}
    for field, name in _PLATFORM_CONTEXT.items():
        value = os.environ.get(name)
        if type(value) is not str or value != value.strip() or _ID_RE.fullmatch(value) is None:
            raise VerticalAIngressError(
                "vertical_a_managed_run_context_missing",
                "an exact managed Hermes Run context is required",
            )
        context[field] = value
    return context


def _normalize_ingress_request(request: object) -> dict[str, object]:
    if type(request) is not dict or set(request) != _INGRESS_FIELDS:
        raise VerticalAIngressError(
            "vertical_a_request_invalid",
            "options request requires exact ticker, expiry, strike and goal_note fields",
        )
    ticker = request.get("ticker")
    expiry = request.get("expiry")
    strike = request.get("strike")
    goal_note = request.get("goal_note")
    if type(ticker) is not str or _TICKER_RE.fullmatch(ticker) is None:
        raise VerticalAIngressError(
            "vertical_a_request_invalid",
            "ticker must be a bounded symbol",
        )
    if type(expiry) is not str or _EXPIRY_RE.fullmatch(expiry) is None:
        raise VerticalAIngressError(
            "vertical_a_request_invalid",
            "expiry must be an exact YYYY-MM-DD date",
        )
    try:
        parsed_expiry = datetime.strptime(expiry, "%Y-%m-%d").date()
    except ValueError as exc:
        raise VerticalAIngressError(
            "vertical_a_request_invalid",
            "expiry must be a valid calendar date",
        ) from exc
    if parsed_expiry <= datetime.now(UTC).date():
        raise VerticalAIngressError(
            "vertical_a_request_invalid",
            "expiry must be in the future",
        )
    if (
        type(strike) is bool
        or not isinstance(strike, int | float)
        or float(strike) <= 0
        or float(strike) != float(strike)
        or float(strike) in (float("inf"), float("-inf"))
    ):
        raise VerticalAIngressError(
            "vertical_a_request_invalid",
            "strike must be a positive finite number",
        )
    if (
        type(goal_note) is not str
        or not goal_note.strip()
        or len(goal_note) > 2_000
        or not goal_note.isprintable()
    ):
        raise VerticalAIngressError(
            "vertical_a_request_invalid",
            "goal_note must be bounded nonempty printable text",
        )
    return {
        "ticker": ticker.upper(),
        "expiry": expiry,
        "strike": float(strike),
        "goal_note": goal_note.strip(),
    }


def _live_auth_envelope(
    *,
    ticker: str,
    command_id: str,
    now: datetime,
) -> dict[str, object]:
    body: dict[str, object] = {
        "tickers": [ticker],
        "fields": ["bid", "ask", "delta", "iv", "expiry", "strike"],
        "max_calls": 1,
        "window_start": (now - timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "window_end": (now + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "grant_id": "hermes-nl-" + hashlib.sha256(command_id.encode()).hexdigest()[:24],
    }
    body["grant_digest"] = canonical_auth_envelope_digest(body)
    return body


def execute_from_hermes_request(request: object) -> dict[str, object]:
    """Seed and execute one live Futu RO request inside the current Hermes Run."""

    normalized = _normalize_ingress_request(request)
    context = _platform_context()
    identity_document = {
        **normalized,
        "command_id": context["command_id"],
        "platform_session_id": context["platform_session_id"],
        "hermes_run_id": context["hermes_run_id"],
        "hermes_session_id": context["hermes_session_id"],
    }
    identity_digest = hashlib.sha256(
        json.dumps(
            identity_document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    client_action_id = "vertical-a-nl-" + identity_digest[:32]
    now = datetime.now(UTC)
    action = BindOptionsVerticalA(
        client_action_id=client_action_id,
        workspace=WorkspaceRef(workspace_id=PLATFORM_WORKSPACE_ID),
        ticker=str(normalized["ticker"]),
        goal_note=str(normalized["goal_note"]),
        expiry=str(normalized["expiry"]),
        strike=float(normalized["strike"]),
        # Production durable authority ignores caller quote fields and obtains
        # the real values from its one-call Futu RO facade after the claim.
        bid=0.0,
        ask=0.0,
        delta=0.0,
        iv=0.0,
        apr=0.0,
        include_provider_evidence=True,
        provider_mode="live_futu_ro",
        auth_envelope=_live_auth_envelope(
            ticker=str(normalized["ticker"]),
            command_id=context["command_id"],
            now=now,
        ),
    )
    settings = load_settings()
    receipt = PlatformAgentWorkspace(
        settings,
        mutation_enabled=bool(settings.local_mutation.enabled),
    ).act(str(ROOT_USER_ID), action)
    if (
        receipt.status not in {"accepted", "reconciling"}
        or receipt.domain_request_id is None
        or receipt.domain_admission_id is None
        or receipt.domain_admission_digest is None
        or _DIGEST_RE.fullmatch(receipt.domain_admission_digest) is None
    ):
        raise VerticalAIngressError(
            receipt.reason_code or "vertical_a_seed_unavailable",
            "the durable options request was not admitted",
        )
    if receipt.domain_request_status == "completed" and receipt.result_id is not None:
        return {
            "action_digest": receipt.action_digest,
            "client_action_id": client_action_id,
            "contract": _INGRESS_CONTRACT,
            "domain_request_id": receipt.domain_request_id,
            "ingress_command_id": context["command_id"],
            "ok": True,
            "replayed": True,
            "result_id": receipt.result_id,
            "run_ref": f"run:{context['hermes_run_id']}",
            "session_ref": f"session:{context['platform_session_id']}",
            "status": "completed",
        }
    if receipt.domain_request_status != "awaiting_run":
        raise VerticalAIngressError(
            "vertical_a_outcome_unknown",
            "the prior provider attempt requires operator reconciliation",
        )

    completed = execute_request(
        request_id=receipt.domain_request_id,
        expected_action_digest=receipt.action_digest,
        expected_admission_id=receipt.domain_admission_id,
        expected_admission_digest=receipt.domain_admission_digest,
        session_ref=f"session:{context['platform_session_id']}",
        run_ref=f"run:{context['hermes_run_id']}",
        worker_id="hqa-hermes-options-tool",
    )
    if (
        completed.get("status") != "completed"
        or completed.get("domain_request_id") != receipt.domain_request_id
        or completed.get("command_id") != context["command_id"]
        or completed.get("session_ref") != f"session:{context['platform_session_id']}"
        or completed.get("run_ref") != f"run:{context['hermes_run_id']}"
    ):
        raise VerticalAIngressError(
            "vertical_a_completion_identity_mismatch",
            "the completed options result does not match this managed Hermes Run",
        )
    return {
        **completed,
        "action_digest": receipt.action_digest,
        "client_action_id": client_action_id,
        "contract": _INGRESS_CONTRACT,
        "ingress_command_id": context["command_id"],
        "ok": True,
        "replayed": False,
    }


def execute_request(
    *,
    request_id: str,
    expected_action_digest: str,
    expected_admission_id: str,
    expected_admission_digest: str,
    session_ref: str,
    run_ref: str,
    worker_id: str,
) -> dict[str, object]:
    """Claim, call the sole read-only facade and finalize one exact request."""

    settings = load_settings()
    authority = PostgresVerticalAAuthority(settings)
    claim = authority.claim_request(
        request_id=request_id,
        expected_action_digest=expected_action_digest,
        expected_admission_id=expected_admission_id,
        expected_admission_digest=expected_admission_digest,
        session_ref=session_ref,
        run_ref=run_ref,
        worker_id=worker_id,
    )
    try:
        facade = build_futu_ro_facade(settings)
        quote = facade.fetch_option_quote_row(
            ticker=claim.ticker,
            expiry=claim.expiry,
            strike=claim.strike,
            option_type="PUT",
        )
        completed = authority.finalize_verified_futu_quote(
            claim_id=claim.claim_id,
            expected_claim_digest=claim.claim_digest,
            quote=quote,
        )
    except VerticalRoProviderError as exc:
        authority.mark_outcome_unknown(
            claim_id=claim.claim_id,
            expected_claim_digest=claim.claim_digest,
            error_code=f"futu_{exc.code}",
        )
        raise VerticalADurableAuthorityError(
            "provider_outcome_unknown",
            "Futu call began after durable pre-call commit; no automatic retry",
        ) from exc
    except VerticalADurableAuthorityError as exc:
        authority.mark_outcome_unknown(
            claim_id=claim.claim_id,
            expected_claim_digest=claim.claim_digest,
            error_code="vertical_a_finalize_uncertain",
        )
        raise VerticalADurableAuthorityError(
            "provider_outcome_unknown",
            "Futu call began but the durable result receipt was not confirmed; no automatic retry",
        ) from exc
    except Exception as exc:
        authority.mark_outcome_unknown(
            claim_id=claim.claim_id,
            expected_claim_digest=claim.claim_digest,
            error_code="vertical_a_postclaim_uncertain",
        )
        raise VerticalADurableAuthorityError(
            "provider_outcome_unknown",
            "post-claim outcome is uncertain; no automatic retry",
        ) from exc
    return {
        "capture_digest": completed.capture_digest,
        "claim_id": completed.claim_id,
        "command_id": claim.command_id,
        "domain_request_id": completed.request_id,
        "provider_receipt_id": completed.provider_receipt_id,
        "result_id": completed.result_id,
        "run_ref": completed.run_ref,
        "session_ref": completed.session_ref,
        "status": "completed",
    }


@app.command("execute-from-hermes")
def execute_from_hermes_command() -> None:
    """Read one closed JSON request from stdin and bind it to this Hermes Run."""

    try:
        raw = sys.stdin.buffer.read(65_537)
        if not raw or len(raw) > 65_536:
            raise VerticalAIngressError(
                "vertical_a_request_invalid",
                "options request must be a nonempty JSON object no larger than 64 KiB",
            )
        request = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_json_constant,
        )
        payload = execute_from_hermes_request(request)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        _emit(
            {
                "contract": _INGRESS_CONTRACT,
                "error_code": "vertical_a_request_invalid",
                "message": "options request is invalid JSON",
                "ok": False,
                "status": "unavailable",
            },
            stderr=True,
        )
        raise typer.Exit(code=2) from exc
    except (VerticalAIngressError, VerticalADurableAuthorityError) as exc:
        _emit(
            {
                "contract": _INGRESS_CONTRACT,
                "error_code": exc.code,
                "message": exc.message,
                "ok": False,
                "status": "unavailable",
            },
            stderr=True,
        )
        raise typer.Exit(code=2) from exc
    _emit(payload)


@app.command("execute")
def execute_command(
    request_id: Annotated[str, typer.Option("--request-id")],
    expected_action_digest: Annotated[
        str,
        typer.Option("--expected-action-digest"),
    ],
    expected_admission_id: Annotated[
        str,
        typer.Option("--expected-admission-id"),
    ],
    expected_admission_digest: Annotated[
        str,
        typer.Option("--expected-admission-digest"),
    ],
    session_ref: Annotated[str, typer.Option("--session-ref")],
    run_ref: Annotated[str, typer.Option("--run-ref")],
    worker_id: Annotated[str, typer.Option("--worker-id")],
) -> None:
    """Execute one exact request and print one canonical JSON receipt."""

    try:
        payload = execute_request(
            request_id=request_id,
            expected_action_digest=expected_action_digest,
            expected_admission_id=expected_admission_id,
            expected_admission_digest=expected_admission_digest,
            session_ref=session_ref,
            run_ref=run_ref,
            worker_id=worker_id,
        )
    except VerticalADurableAuthorityError as exc:
        _emit(
            {
                "error_code": exc.code,
                "message": exc.message,
                "status": "unavailable",
            },
            stderr=True,
        )
        raise typer.Exit(code=2) from exc
    _emit(payload)


if __name__ == "__main__":  # pragma: no cover - exercised as a CLI process
    app()


__all__ = [
    "VerticalAIngressError",
    "app",
    "execute_from_hermes_request",
    "execute_request",
]
