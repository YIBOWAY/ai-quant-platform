"""Command-line entry point for Agent v0.2.2 release operations."""

from __future__ import annotations

import argparse
import json
import signal
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from quant_system.ops.backup_restore import verify_backup_restore_in_owned_container
from quant_system.ops.common import (
    ReleaseOperationError,
    canonical_json_bytes,
    ensure_private_directory,
    write_immutable,
)
from quant_system.ops.noneditable_upgrade import verify_noneditable_upgrade
from quant_system.ops.postgres_container import ReleaseOperationInterrupted
from quant_system.ops.postgres_suite import verify_postgres_suite
from quant_system.ops.restart_stack import restart_stack
from quant_system.ops.zero_effect import (
    DEFAULT_ROUTE_CHILD_TIMEOUT_SECONDS,
    run_zero_effect_proof,
)


@contextmanager
def _catchable_termination_guard() -> Iterator[None]:
    """Turn one catchable operator termination into cleanup-safe unwinding."""

    guarded_signals = (signal.SIGINT, signal.SIGTERM)
    previous = {signum: signal.getsignal(signum) for signum in guarded_signals}
    triggered = False

    def _unwind(signum: int, _frame: object) -> None:
        nonlocal triggered
        if triggered:
            return
        triggered = True
        for guarded in guarded_signals:
            signal.signal(guarded, signal.SIG_IGN)
        raise ReleaseOperationInterrupted(signum)

    installed: list[signal.Signals] = []
    try:
        for signum in guarded_signals:
            signal.signal(signum, _unwind)
            installed.append(signum)
        yield
    finally:
        for signum in reversed(installed):
            signal.signal(signum, previous[signum])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m quant_system.ops.release_ops")
    subcommands = parser.add_subparsers(dest="command", required=True)

    def paths(name: str) -> argparse.ArgumentParser:
        child = subcommands.add_parser(name)
        child.add_argument("--repository-root", type=Path, required=True)
        child.add_argument("--output-dir", type=Path, required=True)
        return child

    postgres = paths("postgres-suite")
    postgres.add_argument("--python", type=Path)

    paths("backup-restore")

    upgrade = paths("noneditable-upgrade")
    upgrade.add_argument("--uv-binary")
    upgrade.add_argument(
        "--bootstrap-authority",
        type=Path,
        required=True,
        help=argparse.SUPPRESS,
    )
    upgrade.add_argument(
        "--bootstrap-authority-sha256",
        required=True,
        help=argparse.SUPPRESS,
    )

    zero = paths("zero-effect")
    zero.add_argument("--hqa-root", type=Path, required=True)
    zero.add_argument("--state-dir", type=Path, required=True)
    zero.add_argument(
        "--route-child-timeout-seconds",
        type=float,
        default=DEFAULT_ROUTE_CHILD_TIMEOUT_SECONDS,
        help="monotonic deadline shared by route-child result handoff and acknowledged exit",
    )

    restart = paths("restart-stack")
    restart.add_argument("--timeout-seconds", type=float, default=30)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "postgres-suite":
            with _catchable_termination_guard():
                result = verify_postgres_suite(
                    repository_root=args.repository_root,
                    output_dir=args.output_dir,
                    python=args.python,
                )
        elif args.command == "backup-restore":
            with _catchable_termination_guard():
                result = verify_backup_restore_in_owned_container(
                    output_dir=args.output_dir,
                    repository_root=args.repository_root,
                )
        elif args.command == "noneditable-upgrade":
            result = verify_noneditable_upgrade(
                repository_root=args.repository_root,
                output_dir=args.output_dir,
                bootstrap_authority_path=args.bootstrap_authority,
                bootstrap_authority_sha256=args.bootstrap_authority_sha256,
                uv_binary=args.uv_binary,
            )
        elif args.command == "zero-effect":
            result = run_zero_effect_proof(
                platform_root=args.repository_root,
                hqa_root=args.hqa_root,
                state_dir=args.state_dir,
                route_child_timeout_seconds=args.route_child_timeout_seconds,
            )
            output_dir = ensure_private_directory(args.output_dir)
            write_immutable(
                output_dir / "zero-effect-proof.json",
                canonical_json_bytes(result),
            )
        elif args.command == "restart-stack":
            result = restart_stack(
                repository_root=args.repository_root,
                output_dir=args.output_dir,
                timeout_seconds=args.timeout_seconds,
            )
        else:
            raise ReleaseOperationError("unknown release operation")
    except ReleaseOperationInterrupted as exc:
        print(
            json.dumps(
                {
                    "schema_version": "agent-v0.2.2-release-operation-error.v1",
                    "status": "failed_closed",
                    "command": getattr(args, "command", None),
                    "error": "interrupted_by_signal",
                    "signal": exc.signum,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 78
    except ReleaseOperationError as exc:
        print(
            json.dumps(
                {
                    "schema_version": "agent-v0.2.2-release-operation-error.v1",
                    "status": "failed_closed",
                    "command": getattr(args, "command", None),
                    "error": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 78
    except Exception as exc:  # noqa: BLE001 - CLI must fail closed without sensitive context
        print(
            json.dumps(
                {
                    "schema_version": "agent-v0.2.2-release-operation-error.v1",
                    "status": "failed_closed",
                    "command": getattr(args, "command", None),
                    "error": "unexpected_internal_error",
                    "exception_class": exc.__class__.__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 78
    try:
        rendered = json.dumps(result, ensure_ascii=False, sort_keys=True)
    except Exception as exc:  # noqa: BLE001 - never emit a partial result
        print(
            json.dumps(
                {
                    "schema_version": "agent-v0.2.2-release-operation-error.v1",
                    "status": "failed_closed",
                    "command": getattr(args, "command", None),
                    "error": "result_serialization_failed",
                    "exception_class": exc.__class__.__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 78
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
