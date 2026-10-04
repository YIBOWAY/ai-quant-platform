#!/usr/bin/env python3
"""Bounded SEC raw-file/PIT research pilot; no formal data, factors or backtests.

Default: AAPL/NVDA submissions + companyfacts, one request each. Optional
--source-run fetches exactly two declared history files; neither mode retries.
A real declared User-Agent is read from an owner-only local
file; its content and hash are never included in receipts. Each run uses a new
output directory, freezes its request plan before requesting, and keeps partial
responses when any request fails. No package installation or service changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from quant_system.research import sec_pit

SYMBOLS = (("AAPL", "0000320193"), ("NVDA", "0001045810"))
MAX_BYTES = 40 * 1024 * 1024


def _now():
    return datetime.now(UTC).isoformat()


def _sha(body):
    return hashlib.sha256(body).hexdigest()


def _write(path: Path, body: bytes):
    with path.open("xb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def _json(path: Path, document):
    _write(path, json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False).encode())


def read_user_agent(path: Path) -> str:
    """Check private ownership without logging content, exceptions or its digest."""
    if path.is_symlink():
        raise ValueError("user_agent_file_invalid")
    info = path.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_size > 512):
        raise ValueError("user_agent_file_invalid")
    value = path.read_text().strip()
    if (not value or len(value) > 256 or "\n" in value or "\r" in value
            or not re.search(r"[^\s@]+@[^\s@]+\.[^\s@]+", value)
            or not value.isascii()):
        raise ValueError("user_agent_identity_missing")
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch(url: str, user_agent: str) -> tuple[bytes, dict]:
    request = Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    with build_opener(NoRedirect()).open(request, timeout=30) as response:
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError("response_too_large")
        return body, {"http_status": response.status,
                      "content_type": response.headers.get("Content-Type"),
                      "last_modified": response.headers.get("Last-Modified"),
                      "server_date": response.headers.get("Date")}


def run(output: Path, user_agent: str, *, fetcher=fetch, pause=time.sleep) -> dict:
    if output.exists() or output.is_symlink():
        raise ValueError("output_must_be_new")
    output.mkdir(mode=0o700, parents=True)
    source_paths = [Path(__file__).resolve(), Path(sec_pit.__file__).resolve()]
    sources_before = {str(path): _sha(path.read_bytes()) for path in source_paths}
    requests = []
    for symbol, cik in SYMBOLS:
        for kind, url in (
            ("submissions", f"https://data.sec.gov/submissions/CIK{cik}.json"),
            ("companyfacts", f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"),
        ):
            requests.append({"symbol": symbol, "cik": cik, "kind": kind, "url": url})
    plan = {
        "schema": "sec_pit_pilot_plan/v1", "created_at": _now(), "requests": requests,
        "concepts": sec_pit.CONCEPTS, "max_requests": 4, "retries": 0,
        "max_response_bytes": MAX_BYTES, "timeout_seconds": 30, "interval_seconds": 0.3,
        "historical_submissions_pagination": False,
        "cutoffs": ["2024-01-01T00:00:00Z", "2025-01-01T00:00:00Z", "snapshot_fetched_at"],
        "source_sha256": sources_before, "user_agent_configured": bool(user_agent),
        "authority": "current_plan_section_8_A6_and_owner_SEC_identity",
        "formal_writes": False, "security_mapping_inferred": False,
        "market_backtests": False, "osap_replication": False,
    }
    _json(output / "request-plan.json", plan)
    plan_sha = _sha((output / "request-plan.json").read_bytes())
    receipts, payloads = [], {}
    failure = None
    for spec in requests:
        receipt = {**spec, "started_at": _now(), "status": "failed"}
        try:
            body, metadata = fetcher(spec["url"], user_agent)
            target = output / f"{spec['symbol']}-{spec['kind']}.json"
            _write(target, body)
            receipt.update(metadata, bytes=len(body), sha256=_sha(body), path=target.name)
            if metadata["http_status"] != 200:
                raise ValueError("unexpected_http_status")
            document = json.loads(body)
            if int(document["cik"]) != int(spec["cik"]):
                raise ValueError("response_cik_mismatch")
            if spec["kind"] == "submissions" and spec["symbol"] not in document.get("tickers", []):
                raise ValueError("current_ticker_cik_mismatch")
            receipt["status"] = "captured"
            payloads[(spec["symbol"], spec["kind"])] = document
        except HTTPError as exc:
            failure = "http_error"
            receipt.update(error_code=failure, http_status=exc.code)
        except (URLError, TimeoutError, OSError):
            failure = "network_error"
            receipt["error_code"] = failure
        except (ValueError, KeyError, TypeError):
            failure = "response_validation_failed"
            receipt["error_code"] = failure
        receipt["completed_at"] = _now()
        receipts.append(receipt)
        _json(output / f"request-{len(receipts):02d}.json", receipt)
        if failure:
            break
        if len(receipts) < len(requests):
            pause(0.3)
    summaries = []
    for symbol, _ in SYMBOLS:
        if (symbol, "submissions") not in payloads or (symbol, "companyfacts") not in payloads:
            continue
        try:
            snapshot = sec_pit.normalize_snapshot(payloads[symbol, "companyfacts"],
                                                 payloads[symbol, "submissions"], fetched_at=_now())
            _json(output / f"{symbol}-versions.json", snapshot)
            queries = []
            for i, cutoff in enumerate(plan["cutoffs"]):
                result = sec_pit.as_of(snapshot, snapshot["fetched_at"]
                                       if cutoff == "snapshot_fetched_at" else cutoff)
                _json(output / f"{symbol}-asof-{i}.json", result)
                queries.append({"cutoff": result["cutoff"], "selected": len(result["selected"]),
                                "blocked_periods": len(result["blocked"]),
                                "unknown_acceptance": result["unavailable_count"]})
            summaries.append({"symbol": symbol, "records": len(snapshot["records"]),
                              "issues": snapshot["issues"],
                              "missing_concepts": snapshot["missing_concepts"], "queries": queries,
                              "pit_backtest_ready": False})
        except (ValueError, KeyError, TypeError):
            failure = "normalization_failed"
            summaries.append({"symbol": symbol, "status": failure})
    sources_after = {str(path): _sha(path.read_bytes()) for path in source_paths}
    if sources_after != sources_before:
        failure = "source_changed_during_run"
    artifacts = {path.name: _sha(path.read_bytes()) for path in sorted(output.iterdir())
                 if path.is_file()}
    report = {
        "schema": "sec_pit_pilot_receipt/v1", "completed_at": _now(),
        "status": "failed" if failure else "captured_and_normalized",
        "error_code": failure, "request_plan_sha256": plan_sha, "requests": receipts,
        "attempted_requests": len(receipts), "unattempted_requests": 4 - len(receipts),
        "summaries": summaries, "source_unchanged": sources_before == sources_after,
        "artifact_sha256": artifacts, "user_agent_configured": bool(user_agent),
        "historical_security_mapping_verified": False, "pit_backtest_ready": False,
        "provider_limitations": (
            "Current SEC snapshots, unmatched historical accessions retained; "
            "no historical API vintage proof"
        ),
        "backtests": 0, "formal_writes": 0, "funding_actions": 0,
    }
    _json(output / "receipt.json", report)
    return report


def run_history(output: Path, source_run: Path, user_agent: str, *, fetcher=fetch,
                pause=time.sleep) -> dict:
    """Fetch only the two exact historical files listed by a closed four-request pilot."""
    if output.exists() or output.is_symlink():
        raise ValueError("output_must_be_new")
    old_receipt = source_run / "receipt.json"
    old = json.loads(old_receipt.read_bytes())
    if old["status"] != "captured_and_normalized" or old["attempted_requests"] != 4:
        raise ValueError("source_run_incomplete")
    inputs = {str(old_receipt.resolve()): _sha(old_receipt.read_bytes())}
    for name, digest in old["artifact_sha256"].items():
        if Path(name).name != name:
            raise ValueError("source_artifact_path_invalid")
        path = source_run / name
        if path.is_symlink() or _sha(path.read_bytes()) != digest:
            raise ValueError("source_artifact_changed")
        inputs[str(path.resolve())] = digest
    payloads, requests = {}, []
    for symbol, cik in SYMBOLS:
        for kind in ("submissions", "companyfacts"):
            document = json.loads((source_run / f"{symbol}-{kind}.json").read_bytes())
            if int(document["cik"]) != int(cik):
                raise ValueError("source_cik_mismatch")
            payloads[symbol, kind] = document
        files = payloads[symbol, "submissions"]["filings"]["files"]
        if len(files) != 1:
            raise ValueError("history_request_population_changed")
        name = files[0]["name"]
        if not re.fullmatch(rf"CIK{cik}-submissions-\d+\.json", name):
            raise ValueError("history_filename_invalid")
        requests.append({"symbol": symbol, "cik": cik, "name": name,
                         "url": f"https://data.sec.gov/submissions/{name}",
                         "source_listing": files[0]})
    source_paths = [Path(__file__).resolve(), Path(sec_pit.__file__).resolve()]
    sources = {str(path): _sha(path.read_bytes()) for path in source_paths}
    output.mkdir(mode=0o700, parents=True)
    plan = {"schema": "sec_pit_history_pilot_plan/v1", "created_at": _now(),
            "requests": requests, "max_requests": 2, "retries": 0,
            "original_input_sha256": inputs, "source_sha256": sources,
            "max_response_bytes": MAX_BYTES, "timeout_seconds": 30,
            "interval_seconds": 0.3, "user_agent_configured": bool(user_agent),
            "cutoffs": ["2024-01-01T00:00:00Z", "2025-01-01T00:00:00Z",
                        "snapshot_fetched_at"],
            "purpose": "Acceptance metadata for existing 2959 fact observations only",
            "formal_writes": False, "market_backtests": False,
            "additional_company_or_concept_requests": False}
    _json(output / "request-plan.json", plan)
    receipts, history, summaries = [], {}, []
    failure = None
    for spec in requests:
        receipt = {**spec, "started_at": _now(), "status": "failed"}
        try:
            body, metadata = fetcher(spec["url"], user_agent)
            target = output / spec["name"]
            _write(target, body)
            receipt.update(metadata, bytes=len(body), sha256=_sha(body), path=target.name)
            if metadata["http_status"] != 200:
                raise ValueError("unexpected_http_status")
            document = json.loads(body)
            if (not isinstance(document, dict)
                    or not isinstance(document.get("accessionNumber"), list)):
                raise ValueError("historical_submissions_invalid")
            history[spec["symbol"]] = [{"name": spec["name"], "data": document}]
            receipt["status"] = "captured"
        except HTTPError as exc:
            failure = "http_error"
            receipt.update(error_code=failure, http_status=exc.code)
        except (URLError, TimeoutError, OSError):
            failure = "network_error"
            receipt["error_code"] = failure
        except (ValueError, KeyError, TypeError):
            failure = "response_validation_failed"
            receipt["error_code"] = failure
        receipt["completed_at"] = _now()
        receipts.append(receipt)
        _json(output / f"request-{len(receipts):02d}.json", receipt)
        if failure:
            break
        if len(receipts) < len(requests):
            pause(0.3)
    for symbol, _ in SYMBOLS:
        if symbol not in history:
            continue
        try:
            snapshot = sec_pit.normalize_snapshot(
                payloads[symbol, "companyfacts"], payloads[symbol, "submissions"],
                fetched_at=_now(), submission_history=history[symbol])
            _json(output / f"{symbol}-versions.json", snapshot)
            queries = []
            for i, cutoff in enumerate(plan["cutoffs"]):
                result = sec_pit.as_of(snapshot, snapshot["fetched_at"]
                                       if cutoff == "snapshot_fetched_at" else cutoff)
                _json(output / f"{symbol}-asof-{i}.json", result)
                queries.append({"cutoff": result["cutoff"], "selected": len(result["selected"]),
                                "blocked_periods": len(result["blocked"]),
                                "unknown_acceptance": result["unavailable_count"]})
            summaries.append({"symbol": symbol, "records": len(snapshot["records"]),
                              "issues": snapshot["issues"],
                              "unfetched_submission_files": snapshot["unfetched_submission_files"],
                              "missing_concepts": snapshot["missing_concepts"], "queries": queries,
                              "pit_backtest_ready": False})
        except (ValueError, KeyError, TypeError):
            failure = "normalization_failed"
            summaries.append({"symbol": symbol, "status": failure})
    source_unchanged = all(_sha(Path(path).read_bytes()) == sha for path, sha in sources.items())
    input_unchanged = all(_sha(Path(path).read_bytes()) == sha for path, sha in inputs.items())
    if not source_unchanged or not input_unchanged:
        failure = "source_or_input_changed"
    report = {"schema": "sec_pit_history_pilot_receipt/v1", "completed_at": _now(),
              "status": "failed" if failure else "captured_and_normalized", "error_code": failure,
              "request_plan_sha256": _sha((output / "request-plan.json").read_bytes()),
              "requests": receipts, "attempted_requests": len(receipts),
              "unattempted_requests": 2 - len(receipts), "summaries": summaries,
              "source_unchanged": source_unchanged, "original_input_unchanged": input_unchanged,
              "artifact_sha256": {p.name: _sha(p.read_bytes()) for p in sorted(output.iterdir())
                                  if p.is_file()},
              "user_agent_configured": bool(user_agent), "pit_backtest_ready": False,
              "historical_api_vintage_observed": False, "backtests": 0,
              "formal_writes": 0, "funding_actions": 0}
    _json(output / "receipt.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--user-agent-file", type=Path, required=True)
    parser.add_argument("--source-run", type=Path,
                        help="Fetch only the exact two declared historical submission files")
    args = parser.parse_args()
    try:
        identity = read_user_agent(args.user_agent_file)
        result = (run_history(args.output, args.source_run, identity) if args.source_run
                  else run(args.output, identity))
    except (ValueError, OSError):
        print(json.dumps({"status": "failed", "error_code": "pilot_preflight_failed"}))
        return 1
    print(json.dumps({"status": result["status"],
                      "attempted_requests": result["attempted_requests"],
                      "output": str(args.output), "pit_backtest_ready": False}))
    return 0 if result["status"] == "captured_and_normalized" else 1


if __name__ == "__main__":
    sys.exit(main())
