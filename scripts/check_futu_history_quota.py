"""Read-only probe of the Futu OpenD history-kline quota plus an append ledger.

This is a Phase 1 data-readiness precondition for the alpha-reset plan (T1.2):
before spending history-kline quota, record how much is left. The script only
calls the read-only ``get_history_kl_quota`` RPC. It never requests bars, never
touches the platform data caches, and never reuses the provider retry wrapper,
so a probe never stacks an extra sleep on top of the provider's 30.5s
rate-limit backoff.

It connects to a local OpenD exactly like ``scripts/verify_futu_connection.py``
(synchronous ``OpenQuoteContext(host=..., port=...)`` closed in a ``finally``).

Usage::

    python scripts/check_futu_history_quota.py
    python scripts/check_futu_history_quota.py --record
    python scripts/check_futu_history_quota.py --check-floor 1000

The success and failure paths both print exactly one JSON line on stdout.
Warnings and the ``--check-floor`` breach notice go to stderr. Tokens, keys,
and any connection detail other than ``host`` are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

SOURCE = "check_futu_history_quota.py"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 11111
DEFAULT_DATA_DIR = "/Users/sunyibo/programs/ai-quant-platform/data"
LEDGER_FILENAME = "futu_quota_ledger.jsonl"
DETAIL_LIMIT = 20

# Defence in depth: even though nothing here should carry credentials, strip any
# key=value / key: value pair that looks like a secret before printing.
_SECRET_PATTERN = re.compile(
    r"(?i)("
    r"token|secret|password|passwd|pass|api[_ -]?key|access[_ -]?key|private[_ -]?key"
    r")\s*[=:]\s*\S+"
)


class QuotaProbeError(Exception):
    """Structured failure raised while probing the quota."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _redact(text: str) -> str:
    """Replace anything that looks like a credential assignment with ``***``."""

    return _SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=***", text)


def _now() -> datetime:
    return datetime.now().astimezone()


def _load_sdk() -> SimpleNamespace:
    """Import the Futu SDK lazily so tests can inject a fake without OpenD."""

    import futu

    return SimpleNamespace(OpenQuoteContext=futu.OpenQuoteContext, RET_OK=futu.RET_OK)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Futu OpenD history-kline quota probe. Prints one JSON line; "
            "never requests bars and never mutates the platform data caches."
        )
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="OpenD host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="OpenD port")
    parser.add_argument(
        "--record",
        action="store_true",
        help="Append the result plus its source and detail summary to the ledger",
    )
    parser.add_argument(
        "--check-floor",
        type=int,
        default=None,
        metavar="N",
        help="Print a WARNING and exit 2 when remain_quota is below N",
    )
    return parser.parse_args(argv)


def _data_dir(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    raw = str(env.get("QS_DATA_DIR", "")).strip()
    return Path(raw) if raw else Path(DEFAULT_DATA_DIR)


def _ledger_path(environ: Mapping[str, str] | None = None) -> Path:
    return _data_dir(environ) / LEDGER_FILENAME


def _normalize_details(detail_list: Any) -> list[dict[str, Any]]:
    if not isinstance(detail_list, (list, tuple)):
        return []
    details: list[dict[str, Any]] = []
    for item in detail_list:
        if not isinstance(item, dict):
            continue
        details.append(
            {
                "code": item.get("code"),
                "name": item.get("name"),
                "request_time": item.get("request_time"),
            }
        )
    return details


def _query_quota(
    sdk: SimpleNamespace, host: str, port: int
) -> tuple[int, int, list[dict[str, Any]]]:
    """Return ``(used_quota, remain_quota, details)`` from a read-only quota call."""

    quote_ctx = sdk.OpenQuoteContext(host=host, port=port)
    try:
        ret_code, payload = quote_ctx.get_history_kl_quota(get_detail=True)
    finally:
        close = getattr(quote_ctx, "close", None)
        if callable(close):
            close()

    if ret_code != sdk.RET_OK:
        raise QuotaProbeError("quota_query_failed", _redact(str(payload)))

    if isinstance(payload, str):
        raise QuotaProbeError(
            "quota_payload_unexpected", "quota payload is an error string, not a tuple"
        )
    try:
        used_quota, remain_quota, detail_list = payload
    except (TypeError, ValueError) as exc:
        raise QuotaProbeError(
            "quota_payload_unexpected", "quota payload is not a 3-tuple"
        ) from exc

    if not isinstance(used_quota, int) or not isinstance(remain_quota, int):
        raise QuotaProbeError(
            "quota_payload_unexpected", "quota payload is not (int, int, list)"
        )
    return used_quota, remain_quota, _normalize_details(detail_list)


def _result_line(
    used_quota: int, remain_quota: int, detail_count: int, *, now: datetime | None = None
) -> dict[str, Any]:
    moment = now if now is not None else _now()
    return {
        "as_of": moment.isoformat(),
        "used_quota": used_quota,
        "remain_quota": remain_quota,
        "detail_count": detail_count,
    }


def _record_line(line: Mapping[str, Any], details: list[dict[str, Any]]) -> dict[str, Any]:
    record = dict(line)
    record["source"] = SOURCE
    if details:
        record["detail_summary"] = details[:DETAIL_LIMIT]
        record["detail_truncated"] = len(details) > DETAIL_LIMIT
    return record


def _append_record(path: Path, record: Mapping[str, Any]) -> None:
    """Atomically-ish append one durable line (append, flush, fsync)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(record, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(serialized + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _emit(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def _emit_error(code: str, message: str, host: str) -> None:
    _emit({"as_of": _now().isoformat(), "error": code, "message": _redact(message), "host": host})


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)

    try:
        sdk = _load_sdk()
    except Exception as exc:  # noqa: BLE001 - surface every import failure structurally
        _emit_error("sdk_unavailable", f"{type(exc).__name__}: {exc}", args.host)
        return 1

    try:
        used_quota, remain_quota, details = _query_quota(sdk, args.host, args.port)
    except QuotaProbeError as exc:
        _emit_error(exc.code, exc.message, args.host)
        return 1
    except Exception as exc:  # noqa: BLE001 - connection failures stay structured
        _emit_error("connection_failed", f"{type(exc).__name__}: {exc}", args.host)
        return 1

    line = _result_line(used_quota, remain_quota, len(details))
    _emit(line)

    if args.record:
        try:
            _append_record(_ledger_path(), _record_line(line, details))
        except OSError as exc:
            print(
                f"WARNING ledger_append_failed: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 1

    if args.check_floor is not None and remain_quota < args.check_floor:
        print(
            "WARNING history_kline_quota_below_floor "
            f"remain_quota={remain_quota} floor={args.check_floor}",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
