"""Trusted local JSON port for durable paper Gate registration/observation.

Hermes/HQA may register metadata-only Gate challenges through this fixed
subprocess surface.  It never accepts prompt, transcript, source bytes, human
notes, provider credentials, or browser-originated arbitrary rows.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping

import typer

from quant_system.config.settings import load_settings
from quant_system.hermes.paper_gate_authority import (
    PaperGateAuthority,
    PaperGateAuthorityError,
    PaperGateAuthorityUnavailable,
    RegisterPaperGateChallenge,
    RegisterPaperGateCompletion,
)
from quant_system.hermes.paper_run_attestation import (
    AttestPaperRun,
    PaperRunAttestationAuthority,
    PaperRunAttestationError,
)

_CONTRACT = "agent-v0.2-paper-gate-cli/v1"
_MAX_STDIN_BYTES = 64 * 1024
_REGISTER_FIELDS = frozenset(RegisterPaperGateChallenge.__dataclass_fields__)
_COMPLETE_FIELDS = frozenset(RegisterPaperGateCompletion.__dataclass_fields__)
_ATTEST_FIELDS = frozenset(
    {
        "command_id",
        "hermes_run_id",
        "hermes_session_id",
        "mode",
        "platform_session_id",
        "workspace_id",
    }
)
_RETRYABLE_ERROR_CODES = frozenset(
    {
        "paper_gate_authority_unavailable",
        "paper_run_attestation_unavailable",
    }
)

paper_gate_app = typer.Typer(
    help=(
        "Register or inspect durable paper Gate metadata through strict JSON "
        "stdin. This is an internal HQA/Hermes port, not a browser API."
    ),
    no_args_is_help=True,
)


class PaperGateCliInputError(ValueError):
    """The single JSON request did not match the fixed CLI contract."""


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise PaperGateCliInputError(f"stdin JSON contains duplicate field: {key}")
        document[key] = value
    return document


def _reject_nonfinite(value: str) -> object:
    raise PaperGateCliInputError(f"stdin JSON contains non-finite number: {value}")


def _emit(payload: Mapping[str, object]) -> None:
    typer.echo(
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _stdin_object(*, exact_fields: frozenset[str]) -> dict[str, object]:
    raw = sys.stdin.buffer.read(_MAX_STDIN_BYTES + 1)
    if not raw or len(raw) > _MAX_STDIN_BYTES:
        raise PaperGateCliInputError("stdin must contain one bounded JSON object")
    try:
        text = raw.decode("utf-8")
        document = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_nonfinite,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        PaperGateCliInputError,
    ) as exc:
        if isinstance(exc, PaperGateCliInputError):
            raise
        raise PaperGateCliInputError("stdin must contain exactly one UTF-8 JSON object") from exc
    if not isinstance(document, dict):
        raise PaperGateCliInputError("stdin JSON must be an object")
    if any(type(key) is not str for key in document):
        raise PaperGateCliInputError("stdin JSON keys must be strings")
    unknown = set(document) - exact_fields
    if unknown:
        raise PaperGateCliInputError(
            "stdin JSON contains unknown fields: " + ",".join(sorted(unknown))
        )
    return dict(document)


def _run(operation: str, callback: Callable[[], Mapping[str, object]]) -> None:
    try:
        payload = dict(callback())
    except PaperGateCliInputError as exc:
        _emit(
            {
                "contract": _CONTRACT,
                "error_code": "paper_gate_cli_invalid_input",
                "message": str(exc),
                "ok": False,
                "operation": operation,
            }
        )
        raise typer.Exit(code=2) from None
    except (TypeError, PaperGateAuthorityError, PaperRunAttestationError) as exc:
        code = (
            exc.code
            if isinstance(exc, PaperGateAuthorityError | PaperRunAttestationError)
            else "paper_gate_cli_invalid_input"
        )
        _emit(
            {
                "contract": _CONTRACT,
                "error_code": code,
                "message": str(exc)[:500],
                "ok": False,
                "operation": operation,
            }
        )
        raise typer.Exit(code=1 if code in _RETRYABLE_ERROR_CODES else 2) from None
    except Exception as exc:  # noqa: BLE001 - fixed port fails closed
        _emit(
            {
                "contract": _CONTRACT,
                "error_code": "paper_gate_cli_unavailable",
                "message": str(exc)[:500] or exc.__class__.__name__,
                "ok": False,
                "operation": operation,
            }
        )
        raise typer.Exit(code=1) from None
    _emit(
        {
            "contract": _CONTRACT,
            "ok": True,
            "operation": operation,
            **payload,
        }
    )


@paper_gate_app.command("register")
def register_command() -> None:
    """Register one exact Gate challenge from metadata-only JSON stdin."""

    def _register() -> Mapping[str, object]:
        document = _stdin_object(exact_fields=_REGISTER_FIELDS)
        missing = {
            "attempt_ref",
            "command_id",
            "expected_task_version",
            "gate_id",
            "gate_kind",
            "hermes_run_id",
            "hermes_session_id",
            "hqa_gate_ref",
            "platform_session_id",
            "task_ref",
            "workspace_id",
        } - set(document)
        if missing:
            raise PaperGateCliInputError(
                "stdin JSON is missing required fields: " + ",".join(sorted(missing))
            )
        request = RegisterPaperGateChallenge(**document)  # type: ignore[arg-type]
        record = PaperGateAuthority(load_settings()).register_challenge(request)
        return {"gate": record.to_operator_dict()}

    _run("register", _register)


@paper_gate_app.command("attest-run")
def attest_run_command() -> None:
    """Attest one exact Platform Command/Hermes Run binding, read-only."""

    def _attest() -> Mapping[str, object]:
        document = _stdin_object(exact_fields=_ATTEST_FIELDS)
        if set(document) != _ATTEST_FIELDS:
            missing = _ATTEST_FIELDS - set(document)
            raise PaperGateCliInputError(
                "attest-run stdin JSON is missing fields: "
                + ",".join(sorted(missing))
            )
        attestation = PaperRunAttestationAuthority(load_settings()).attest(
            AttestPaperRun(**document)  # type: ignore[arg-type]
        )
        return {"attestation": attestation}

    _run("attest-run", _attest)


@paper_gate_app.command("show")
def show_command() -> None:
    """Show one exact durable Gate in its bound Workspace and Session."""

    def _show() -> Mapping[str, object]:
        required = frozenset(
            {
                "gate_id",
                "platform_session_id",
                "workspace_id",
            }
        )
        document = _stdin_object(exact_fields=required)
        if set(document) != required or any(type(document[field]) is not str for field in required):
            raise PaperGateCliInputError(
                "show requires exactly string gate_id, workspace_id, and platform_session_id"
            )
        record = PaperGateAuthority(load_settings()).get_operator_record(str(document["gate_id"]))
        if (
            record.get("workspace_id") != document["workspace_id"]
            or record.get("platform_session_id") != document["platform_session_id"]
        ):
            raise PaperGateAuthorityUnavailable(
                "paper gate continuation context does not match",
                code="paper_gate_context_mismatch",
            )
        return {"gate": record}

    _run("show", _show)


@paper_gate_app.command("complete")
def complete_command() -> None:
    """Register the immutable HQA terminal receipt after human Git commit."""

    def _complete() -> Mapping[str, object]:
        document = _stdin_object(exact_fields=_COMPLETE_FIELDS)
        if set(document) != _COMPLETE_FIELDS:
            missing = _COMPLETE_FIELDS - set(document)
            raise PaperGateCliInputError(
                "complete stdin JSON is missing fields: " + ",".join(sorted(missing))
            )
        completion = PaperGateAuthority(load_settings()).register_completion(
            RegisterPaperGateCompletion(**document)  # type: ignore[arg-type]
        )
        return {"completion": completion.to_operator_dict()}

    _run("complete", _complete)


@paper_gate_app.command("list")
def list_command() -> None:
    """List bounded Gate projections for one workspace."""

    def _list() -> Mapping[str, object]:
        document = _stdin_object(exact_fields=frozenset({"workspace_id"}))
        if set(document) != {"workspace_id"} or type(document["workspace_id"]) is not str:
            raise PaperGateCliInputError("list requires exactly string workspace_id")
        return {
            "gates": PaperGateAuthority(load_settings()).list_observed(
                str(document["workspace_id"])
            )
        }

    _run("list", _list)


if __name__ == "__main__":  # pragma: no cover - exercised via executable
    paper_gate_app()


__all__ = ["paper_gate_app"]
