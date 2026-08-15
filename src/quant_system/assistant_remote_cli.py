"""Owner remote: intake / book / hang from the isolation workspace.

Usage:
  python -m quant_system.assistant_remote_cli intake --note TEXT --formula TEXT --universe SPY --universe QQQ
  python -m quant_system.assistant_remote_cli book
  python -m quant_system.assistant_remote_cli hang --candidate-id ID
"""

from __future__ import annotations

import argparse
import json
import sys

from quant_system.config.settings import load_settings
from quant_system.execution.assistant_remote import (
    AssistantRemoteError,
    hang_candidate,
    intake_material,
    reconcile_remote_book,
)


def _emit(payload: object, *, code: int = 0) -> int:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="assistant-remote")
    sub = parser.add_subparsers(dest="command", required=True)

    intake = sub.add_parser("intake", help="fail-closed paper/material intake")
    intake.add_argument("--note", required=True)
    intake.add_argument("--formula", default="")
    intake.add_argument("--universe", action="append", default=[])

    sub.add_parser("book", help="reconcile + admit accepted artifacts")

    hang = sub.add_parser("hang", help="hang a verified digest-bound candidate")
    hang.add_argument("--candidate-id", required=True)

    args = parser.parse_args(argv)
    settings = load_settings()
    try:
        if args.command == "intake":
            return _emit(
                intake_material(
                    settings,
                    note=args.note,
                    formula=args.formula or None,
                    universe=args.universe or None,
                )
            )
        if args.command == "book":
            return _emit(reconcile_remote_book(settings))
        if args.command == "hang":
            return _emit(hang_candidate(settings, candidate_id=args.candidate_id))
    except AssistantRemoteError as exc:
        return _emit({"ok": False, "code": exc.code}, code=2)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
