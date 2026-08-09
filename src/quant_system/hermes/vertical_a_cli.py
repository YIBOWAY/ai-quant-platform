"""Fixed Platform CLI port for one durable Vertical-A Futu read-only request.

The HQA/Hermes canonical Run invokes this module only after it knows the exact
Platform Session and Hermes Run references.  The command commits the provider
attempt before constructing or calling the Futu facade.  Every uncertain
post-claim failure is sealed ``outcome_unknown`` and is never auto-replayed.
"""

from __future__ import annotations

import json
import sys
from typing import Annotated

import typer

from quant_system.config.settings import load_settings
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
        "domain_request_id": completed.request_id,
        "provider_receipt_id": completed.provider_receipt_id,
        "result_id": completed.result_id,
        "run_ref": completed.run_ref,
        "session_ref": completed.session_ref,
        "status": "completed",
    }


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


__all__ = ["app", "execute_request"]
