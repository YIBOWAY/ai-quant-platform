#!/usr/bin/env python
"""Tiingo EOD backfill, version-controlled successor to the 09-20 artifact probe.

Re-implementation of the lost T1.3 probe script, rebuilt to the contract in
`docs/receipts/2026-09-16-t13-tiingo-probe.md` (§七 判例 8) and the Phase 1
closeout口径.

Contract
--------
* token ONLY from env var ``QS_TIINGO_API_TOKEN`` (never argv, never disk).
* two read-only endpoints:
    GET /tiingo/daily/<sym>                    -> meta JSON (skippable --no-meta)
    GET /tiingo/daily/<sym>/prices?startDate=&format=csv -> full-history CSV
* output ``<SYM>.parquet`` with the 13 columns
  date, close, high, low, open, volume, adjClose, adjHigh, adjLow, adjOpen,
  adjVolume, divCash, splitFactor   (raw + adj OHLCV + divCash + splitFactor)
* ``--max-requests N`` budget gate; existing parquet is skipped (resume);
  HTTP 429 stops immediately (``Retry-After`` is absent upstream — the hourly
  retry is the caller's job); 401/403 stops immediately (bad token -> zero batch).
* request pace >= 2s (default 2.1s).
* the Authorization header is never written to disk or into any log/summary;
  any response body that would echo it is redacted defensively.

Read-only: no writes outside the panel directory.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

BASE = "https://api.tiingo.com/tiingo/daily"
CSV_COLUMNS = [
    "date",
    "close",
    "high",
    "low",
    "open",
    "volume",
    "adjClose",
    "adjHigh",
    "adjLow",
    "adjOpen",
    "adjVolume",
    "divCash",
    "splitFactor",
]
PRICE_COLUMNS = [c for c in CSV_COLUMNS if c != "date"]


class Stop(Exception):
    """Raised to abort the run (429 / auth / budget)."""


class SymbolError(Exception):
    """Explicit not-found evidence (HTTP 404 or documented ticker-not-found body).

    Recorded and skipped; it must NOT abort the whole backfill (the T1.3 probe
    found SIVB meta=404 and FRC prices-empty as normal per-symbol outcomes)."""


class TransientError(Exception):
    """Retryable per-symbol failure (network/SSL/timeout, HTTP 5xx).

    Deliberately distinct from SymbolError: a transient failure must never
    write a terminal ``<SYM>.absent`` tombstone. A single SSL EOF in batch b14
    retired 13 symbols as "terminal" that way, discovered 2026-09-20."""


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def redact(text: str, token: str) -> str:
    if token and token in text:
        text = text.replace(token, "<REDACTED>")
    return text


def fetch(url: str, token: str, timeout: float = 30.0):
    """GET url with the Tiingo token in the Authorization header only.

    Only explicit not-found is terminal for a symbol. Auth, quota and unknown
    request errors stop this batch; network/server/timeouts stay retryable.
    """
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Token {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "qs-tiingo-backfill/1.0")
    bare = url.split("?")[0]
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        code = exc.code
        try:
            body = exc.read()
        except Exception:  # pragma: no cover - defensive
            body = b""
        if code == 429:
            raise Stop(f"HTTP 429 rate-limited on {bare}") from None
        if code in (401, 403):
            raise Stop(f"HTTP {code} authorization rejected — token invalid/expired") from None
        if code == 408 or code >= 500:
            raise TransientError(f"HTTP {code} server-side on {bare}") from None
        message = f"HTTP {code} on {bare}: {redact(body[:200].decode('utf-8', 'replace'), token)}"
        if code == 404:
            raise SymbolError(message) from None
        raise Stop(message) from None
    except urllib.error.URLError as exc:
        raise TransientError(f"network error on {bare}: {redact(str(exc.reason), token)}") from None
    except TimeoutError:
        raise TransientError(f"timeout on {bare}") from None


class Fetcher:
    def __init__(self, token: str, sleep: float, max_requests: int):
        self.token = token
        self.sleep = sleep
        self.max_requests = max_requests
        self.used = 0
        self._last = 0.0
        self.last_body = b""
        self.log: list[dict] = []

    def _pace(self):
        now = time.monotonic()
        wait = self.sleep - (now - self._last)
        if self._last and wait > 0:
            time.sleep(wait)

    def _gate(self, label: str):
        if self.max_requests is not None and self.used >= self.max_requests:
            raise Stop(f"request budget exhausted ({self.used}/{self.max_requests}) before {label}")

    def get(self, url: str, label: str) -> bytes:
        self._gate(label)
        self._pace()
        try:
            status, body = fetch(url, self.token)
        finally:
            # count every attempt: a 404 / 429 / Error-body response still spent quota
            self.used += 1
            self._last = time.monotonic()
        self.last_body = body
        self.log.append(
            {
                "label": label,
                "url": url.split("?")[0],
                "status": status,
                "bytes": len(body),
                "request_index": self.used,
            }
        )
        # Tiingo signals free-tier exhaustion as HTTP 200 with an
        # "Error: You have run over your hourly request allocation" body, NOT a
        # 429, and "Ticker 'X' not found" for unknown symbols. Both arrive as
        # HTTP 200, so the status code alone is not a usable gate.
        if body[:6] == b"Error:":
            msg = redact(body[:200].decode("utf-8", "replace"), self.token)
            if "hourly request allocation" in msg or "upgrade" in msg:
                raise Stop(
                    f"Tiingo hourly request allocation exhausted (HTTP 200 error body): {msg}"
                )
            if re.fullmatch(
                r"Error:\s*(?:Ticker|Symbol)\s+['\"]?[A-Za-z0-9._-]+['\"]?\s+not found\.?",
                msg,
                re.IGNORECASE,
            ):
                raise SymbolError(msg)
            raise Stop(f"unclassified upstream error (not symbol absence): {msg}")
        return body

    def meta(self, sym: str) -> dict:
        body = self.get(f"{BASE}/{urllib.parse.quote(sym)}", f"meta:{sym}")
        return json.loads(body.decode("utf-8"))

    def prices(self, sym: str, start: str = "") -> pd.DataFrame:
        # NB: Tiingo rejects an empty startDate ("Start date format was not
        # correct"), and OMITTING startDate returns a single row only — the
        # full history needs an explicit early date (CLI default 1900-01-01).
        params = {"format": "csv"}
        if start:
            params["startDate"] = start
        q = urllib.parse.urlencode(params)
        body = self.get(f"{BASE}/{urllib.parse.quote(sym)}/prices?{q}", f"prices:{sym}")
        # Empty CSV says only that this request returned no rows. A short
        # maintenance/error response is not evidence of an absent security.
        if not body.strip():
            return pd.DataFrame(columns=CSV_COLUMNS)
        if len(body.strip()) < 20:
            raise ValueError("unexpected_short_body")
        df = pd.read_csv(pd.io.common.BytesIO(body))
        return df


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Map the Tiingo CSV onto the canonical 13 columns, drop the trailing
    empty line Tiingo sometimes emits, coerce dtypes."""
    df = df.rename(columns={c: c for c in df.columns})
    missing = [c for c in CSV_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns {missing}")
    df = df[CSV_COLUMNS].copy()
    df = df.dropna(how="all")
    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_localize(None)
    for c in PRICE_COLUMNS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    return df


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--symbols", nargs="*", default=[], help="symbols (bare tickers, not wire codes)"
    )
    ap.add_argument("--symbols-file", help="file with one symbol per line")
    ap.add_argument("--universe", help="universe_tiingo.json; uses universe_need_tiingo order")
    ap.add_argument("--limit", type=int, help="take only the first N from the universe")
    ap.add_argument("--out", required=True, help="explicit output panel directory")
    ap.add_argument(
        "--no-meta", action="store_true", help="skip the meta request (1 request/symbol)"
    )
    ap.add_argument(
        "--meta-only",
        action="store_true",
        help="fetch meta only (for symbols whose parquet already exists); "
        "does not touch prices — used to run the identity gate in its own window",
    )
    ap.add_argument(
        "--max-requests", type=int, default=None, help="hard request budget for this run"
    )
    ap.add_argument("--sleep", type=float, default=2.1, help="min seconds between requests (>=2)")
    ap.add_argument(
        "--start-date",
        default="1900-01-01",
        help="startDate= (default 1900-01-01 = the full history Tiingo holds; "
        "Tiingo returns a single row if startDate is omitted/empty)",
    )
    ap.add_argument("--tag", default="run", help="label for the fetch summary")
    args = ap.parse_args(argv)

    token = os.environ.get("QS_TIINGO_API_TOKEN", "").strip()
    if not token:
        print("FATAL: QS_TIINGO_API_TOKEN not set in the environment", file=sys.stderr)
        return 2
    if args.sleep < 2.0:
        print("FATAL: --sleep must be >= 2.0s (hourly quota discipline)", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    meta_dir = out / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)

    symbols: list[str] = list(args.symbols)
    if args.symbols_file:
        symbols += [
            ln.strip()
            for ln in Path(args.symbols_file).read_text().splitlines()
            if ln.strip() and not ln.startswith("#")
        ]
    if args.universe:
        uni = json.loads(Path(args.universe).read_text())
        listed = list(uni["universe_need_tiingo"])
        if args.limit:
            listed = listed[: args.limit]
        symbols += listed
    if not symbols:
        print("FATAL: no symbols given", file=sys.stderr)
        return 2

    fetcher = Fetcher(token, args.sleep, args.max_requests)
    records: list[dict] = []
    streak_path = out / "empty_streak.json"
    try:
        empty_streak: dict[str, int] = json.loads(streak_path.read_text())
    except Exception:
        empty_streak = {}
    stopped: str | None = None

    try:
        for sym in symbols:
            pq = out / f"{sym}.parquet"
            meta_pq = meta_dir / f"{sym}.json"
            rec = {"symbol": sym, "outcome": None, "requests": 0}
            if args.meta_only:
                if meta_pq.exists() and meta_pq.stat().st_size > 0:
                    rec["outcome"] = "skipped_existing"
                    records.append(rec)
                    continue
                try:
                    m = fetcher.meta(sym)
                    safe = {k: v for k, v in m.items() if k.lower() != "authorization"}
                    meta_pq.write_text(
                        json.dumps(safe, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                    )
                    rec["outcome"] = "meta_ok"
                except TransientError as exc:
                    rec["outcome"] = "meta_transient"
                    rec["error"] = redact(str(exc), token)
                except SymbolError as exc:
                    rec["outcome"] = "meta_absent"
                    rec["error"] = redact(str(exc), token)
                rec["requests"] = fetcher.used
                records.append(rec)
                print(f"{sym:8} {rec['outcome']:>16} req={fetcher.used}", flush=True)
                continue
            tomb = pq.with_suffix(".absent")
            if pq.exists() and pq.stat().st_size > 0:
                rec["outcome"] = "skipped_existing"
                records.append(rec)
                continue
            if tomb.exists():
                # terminal upstream verdict from a previous run (ticker not
                # found): do not spend quota re-probing it every window
                rec["outcome"] = "skipped_absent"
                records.append(rec)
                continue
            try:
                if not args.no_meta:
                    try:
                        m = fetcher.meta(sym)
                        safe = {k: v for k, v in m.items() if k.lower() != "authorization"}
                        meta_pq.write_text(
                            json.dumps(safe, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                        )
                        rec["meta"] = "ok"
                    except TransientError as exc:
                        rec["meta"] = "transient"
                        rec["meta_error"] = redact(str(exc), token)
                    except SymbolError as exc:
                        # a 404 meta is normal (SIVB): the price series may still
                        # come back via a silent alias — keep going.
                        rec["meta"] = "absent"
                        rec["meta_error"] = redact(str(exc), token)
                try:
                    df = normalise(fetcher.prices(sym, args.start_date))
                except TransientError as exc:
                    # Retryable: no tombstone, no file. A terminal verdict on a
                    # network blip is how 13 symbols got falsely retired in b14.
                    rec["outcome"] = "transient_error"
                    rec["error"] = redact(str(exc), token)
                    rec["requests"] = fetcher.used
                    records.append(rec)
                    print(
                        f"{sym:8} {rec['outcome']:>16} req={fetcher.used} {rec['error'][:60]}",
                        flush=True,
                    )
                    continue
                except SymbolError as exc:
                    rec["outcome"] = "absent"
                    rec["error"] = redact(str(exc), token)
                    tomb = pq.with_suffix(".absent")
                    tomb.write_text(rec["error"] + "\n", encoding="utf-8")
                    rec["requests"] = fetcher.used
                    records.append(rec)
                    print(
                        f"{sym:8} {rec['outcome']:>16} req={fetcher.used} {rec['error'][:60]}",
                        flush=True,
                    )
                    continue
                rec["rows"] = int(len(df))
                if len(df):
                    df.to_parquet(pq, index=False)
                    rec["outcome"] = "ok"
                    empty_streak.pop(sym, None)
                else:
                    # Repeated empties require identity/coverage review, not
                    # permanent absence. Keep the count, never a zero-row file
                    # or tombstone. Each run still has an explicit quota budget.
                    n = empty_streak.get(sym, 0) + 1
                    empty_streak[sym] = n
                    if n >= 2:
                        rec["outcome"] = "empty_needs_review"
                    else:
                        rec["outcome"] = "empty"
            except ValueError as exc:
                rec["outcome"] = "schema_error"
                raw = fetcher.last_body[:200].decode("utf-8", "replace").replace("\n", "\\n")
                rec["error"] = f"{redact(str(exc), token)} | body={redact(raw, token)}"
            rec["requests"] = fetcher.used
            records.append(rec)
            print(
                f"{sym:8} {rec['outcome']:>16} rows={rec.get('rows', '-')} req={fetcher.used}",
                flush=True,
            )
    except Stop as exc:
        stopped = redact(str(exc), token)
        print(f"STOP: {stopped}", flush=True)

    summary = {
        "tag": args.tag,
        "ran_at": utcnow(),
        "no_meta": args.no_meta,
        "meta_only": args.meta_only,
        "max_requests": args.max_requests,
        "sleep": args.sleep,
        "start_date": args.start_date,
        "requests_used": fetcher.used,
        "stopped": stopped,
        "n_symbols_requested": len(symbols),
        "n_ok": sum(1 for r in records if r["outcome"] == "ok"),
        "n_meta_ok": sum(1 for r in records if r["outcome"] == "meta_ok"),
        "n_skipped_existing": sum(1 for r in records if r["outcome"] == "skipped_existing"),
        "n_failed": sum(
            1 for r in records if r["outcome"] not in ("ok", "skipped_existing", "meta_ok")
        ),
        "records": records,
        "requests": fetcher.log,
    }
    (out / f"fetch_summary_{args.tag}.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    streak_path.write_text(
        json.dumps(empty_streak, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "tag",
                    "requests_used",
                    "n_ok",
                    "n_skipped_existing",
                    "n_failed",
                    "stopped",
                )
            },
            indent=2,
        )
    )
    return 0 if stopped is None else 1


if __name__ == "__main__":
    sys.exit(main())
