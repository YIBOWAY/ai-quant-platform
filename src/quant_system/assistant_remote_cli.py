"""Owner same-chat research, candidate book and digest-bound paper hang.

Usage:
  printf '%s' CLOSED_JSON | python -m quant_system.assistant_remote_cli research
  python -m quant_system.assistant_remote_cli request --operation-id DIGEST
  python -m quant_system.assistant_remote_cli book
  python -m quant_system.assistant_remote_cli reconcile-result --job-id ID
  python -m quant_system.assistant_remote_cli verify-from-registered
      --factor-id ID --universe SYMBOL [--universe SYMBOL ...]
  python -m quant_system.assistant_remote_cli hang --candidate-id ID --expected-source-digest DIGEST
"""

from __future__ import annotations

import argparse
import json
import sys

from quant_system.config.settings import load_settings
from quant_system.execution.assistant_remote import (
    AssistantRemoteError,
    hang_candidate,
    intake_research_operation,
    project_book,
    project_research_request,
    reconcile_research_result,
    verify_registered_factor,
)
from quant_system.hermes.d34_job_authority import JobAuthorityError, PostgresJobAuthority

_RESEARCH_INPUT_FIELDS = frozenset(
    {
        "operation_id",
        "material_digest",
        "command_id",
        "platform_session_id",
        "hermes_session_id",
        "hermes_run_id",
        "note",
        "formula",
        "universe",
    }
)
_RESEARCH_INPUT_MAX_BYTES = 32_768


def _emit(payload: object, *, code: int = 0) -> int:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    return code


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise AssistantRemoteError("research_input_duplicate_key")
        value[key] = item
    return value


def _reject_nonfinite(_value: str) -> object:
    raise AssistantRemoteError("research_input_nonfinite")


def _read_research_input() -> dict[str, object]:
    raw = sys.stdin.read(_RESEARCH_INPUT_MAX_BYTES + 1)
    if not raw or len(raw.encode("utf-8")) > _RESEARCH_INPUT_MAX_BYTES:
        raise AssistantRemoteError("research_input_invalid")
    try:
        payload = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
        )
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise AssistantRemoteError("research_input_invalid") from exc
    if not isinstance(payload, dict) or set(payload) != _RESEARCH_INPUT_FIELDS:
        raise AssistantRemoteError("research_input_fields_invalid")
    string_fields = _RESEARCH_INPUT_FIELDS - {"universe"}
    if any(type(payload[field]) is not str for field in string_fields):
        raise AssistantRemoteError("research_input_types_invalid")
    universe = payload["universe"]
    if (
        type(universe) is not list
        or not universe
        or any(type(symbol) is not str for symbol in universe)
    ):
        raise AssistantRemoteError("research_input_types_invalid")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="assistant-remote")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("research", help="enqueue one stable stdin chat research operation")

    request = sub.add_parser("request", help="read one chat research operation")
    request.add_argument("--operation-id", required=True)

    sub.add_parser("book", help="read the current candidate book")

    reconcile_result = sub.add_parser(
        "reconcile-result",
        help="project one exact terminal research result",
    )
    reconcile_result.add_argument("--job-id", required=True)

    verify_registered = sub.add_parser(
        "verify-from-registered",
        help="verify one registered factor into the candidate book without hanging",
    )
    verify_registered.add_argument("--factor-id", required=True)
    verify_registered.add_argument("--universe", action="append", required=True)

    hang = sub.add_parser("hang", help="hang a verified digest-bound candidate")
    hang.add_argument("--candidate-id", required=True)
    hang.add_argument("--expected-source-digest", required=True)

    args = parser.parse_args(argv)
    settings = load_settings()
    try:
        if args.command == "book":
            return _emit(project_book(settings))
        if args.command == "research":
            payload = _read_research_input()
            return _emit(
                intake_research_operation(
                    settings,
                    jobs=PostgresJobAuthority(settings),
                    operation_id=str(payload["operation_id"]),
                    material_digest=str(payload["material_digest"]),
                    command_id=str(payload["command_id"]),
                    platform_session_id=str(payload["platform_session_id"]),
                    hermes_session_id=str(payload["hermes_session_id"]),
                    hermes_run_id=str(payload["hermes_run_id"]),
                    note=str(payload["note"]),
                    formula=str(payload["formula"]),
                    universe=list(payload["universe"]),  # type: ignore[arg-type]
                )
            )
        if args.command == "request":
            projection = project_research_request(
                settings,
                operation_id=args.operation_id,
            )
            if projection is None:
                raise AssistantRemoteError("research_operation_not_found")
            return _emit(projection)
        if args.command == "reconcile-result":
            projection = reconcile_research_result(settings, job_id=args.job_id)
            if projection is None:
                raise AssistantRemoteError("research_result_not_found")
            return _emit(projection)
        if args.command == "verify-from-registered":
            return _emit(
                verify_registered_factor(
                    settings,
                    factor_id=args.factor_id,
                    universe=args.universe,
                )
            )
        if args.command == "hang":
            return _emit(
                hang_candidate(
                    settings,
                    candidate_id=args.candidate_id,
                    expected_source_digest=args.expected_source_digest,
                )
            )
    except AssistantRemoteError as exc:
        return _emit({"ok": False, "code": exc.code}, code=2)
    except (JobAuthorityError, ValueError) as exc:
        return _emit(
            {
                "ok": False,
                "code": str(getattr(exc, "code", type(exc).__name__)),
            },
            code=2,
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
