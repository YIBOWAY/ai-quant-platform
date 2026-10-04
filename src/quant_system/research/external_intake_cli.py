"""Small JSON-only CLI used by the Grok/local research delivery wrapper."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
from pathlib import Path

from pydantic import ValidationError

from quant_system.config.settings import load_settings
from quant_system.research import external_intake as service

COMPACT_SHOW_PROJECTION = "compact_intake_job/v1"


def _compact_show(result):
    """Project the already verified show result; never infer a successful check."""
    value = {
        key: result.get(key)
        for key in (
            "job_id",
            "proposal_id",
            "payload_sha256",
            "created_at",
            "updated_at",
            "status",
            "outcome",
            "error",
            "comparison_status",
            "increment",
        )
    }
    value["projection"] = COMPACT_SHOW_PROJECTION
    value["results"] = []
    for row in result.get("results") or []:
        diagnostic = row.get("diagnostics") or {}
        value["results"].append(
            {
                **{
                    key: row.get(key)
                    for key in (
                        "variant",
                        "phase",
                        "status",
                        "error",
                        "strategy_id",
                        "definition_digest",
                        "candidate_id",
                        "sleeve_id",
                        "validation_sha256",
                    )
                },
                "validation_run_id": (row.get("validation") or {}).get("run_id"),
                "blockers": (row.get("validation") or {}).get("blockers", []),
                "diagnostics": {
                    key: diagnostic[key]
                    for key in ("status", "binding", "reason")
                    if key in diagnostic
                },
            }
        )
    return value


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError("intake_cli_arguments_invalid")


def _validation_errors(error: ValidationError) -> list[dict]:
    """Expose schema locations, never submitted values or free-form messages."""
    fields = (
        set(service.Proposal.model_fields)
        | set(service.IntakePolicy.model_fields)
        | set(service.StrategySpec.model_fields)
        | set(service.IncrementObjective.model_fields)
    )
    internal_codes = {
        "intake_schema_version_invalid",
        "intake_blank_material",
        "intake_source_url_invalid",
        "intake_source_url_duplicate",
        "intake_timestamp_requires_timezone",
        "intake_baseline_duplicate",
        "intake_baseline_invalid",
    }
    result = []
    for item in error.errors(include_input=False, include_url=False)[:32]:
        error_type = item.get("type", "schema_error")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", error_type):
            error_type = "schema_error"
        candidate = str((item.get("ctx") or {}).get("error", ""))
        result.append(
            {
                "path": [
                    part if type(part) is int or part in fields else "<unknown_field>"
                    for part in item.get("loc", ())
                ],
                "type": error_type,
                "code": candidate if candidate in internal_codes else "intake_schema_" + error_type,
            }
        )
    return result


def main(argv=None, *, stdin=None, stdout=None):
    stream = stdin if stdin is not None else sys.stdin
    output = stdout if stdout is not None else sys.stdout
    action = None
    try:
        parser = _Parser(
            description="External proposal intake under local standing research policy."
        )
        commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
        for name in ("capabilities", "policy", "submit", "list", "sync-report", "run-once"):
            commands.add_parser(name)
        show_parser = commands.add_parser("show")
        show_parser.add_argument("job_id")
        show_parser.add_argument(
            "--compact",
            action="store_true",
            help="Read-only bounded status and archived-receipt diagnostics",
        )
        commands.add_parser("reconcile").add_argument("job_id")
        args = parser.parse_args(argv)
        action = args.command
        with (
            open(os.devnull, "w") as sink,
            contextlib.redirect_stdout(sink),
            contextlib.redirect_stderr(sink),
        ):
            settings = load_settings().model_copy(deep=True)
            if not settings.data.data_dir.is_absolute():
                settings.data.data_dir = (
                    Path(__file__).resolve().parents[3] / settings.data.data_dir
                )
            if action == "submit":
                raw = service.strict_json(stream.read(service.MAX_JSON_BYTES + 1))
                result = service.submit(settings, raw)
            elif action == "capabilities":
                result = service.capabilities(settings)
            elif action == "policy":
                result = {"policy": service.read_policy(settings).model_dump()}
            elif action == "show":
                result = service.show(settings, args.job_id)
                if args.compact:
                    result = _compact_show(result)
            elif action == "reconcile":
                result = service.reconcile(settings, args.job_id)
            elif action == "list":
                result = service.list_jobs(settings)
            elif action == "sync-report":
                result = service.sync_report(settings)
            else:
                result = service.run_once(settings)
        failed = result.get("status") in service._TERMINAL - {"completed"}
        payload = {"contract": service.CONTRACT, "action": action, "ok": not failed, **result}
        code = 1 if failed else 0
    except SystemExit as exc:
        return int(exc.code or 0)
    except KeyboardInterrupt:
        payload = {
            "contract": service.CONTRACT,
            "action": action,
            "ok": False,
            "status": "outcome_unknown",
            "error": "intake_interrupted",
        }
        code = 130
    except Exception as exc:
        error = (
            "intake_schema_invalid"
            if isinstance(exc, ValidationError)
            else "intake_record_not_found"
            if isinstance(exc, FileNotFoundError)
            else service._error(exc)
        )
        payload = {
            "contract": service.CONTRACT,
            "action": action,
            "ok": False,
            "status": "error",
            "error": error,
        }
        if isinstance(exc, ValidationError):
            payload["validation_errors"] = _validation_errors(exc)
        code = 2
    output.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
