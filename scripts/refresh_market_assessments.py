"""Refresh both real market assessments through the same API used by the website."""

from __future__ import annotations

import json
import time

import httpx

from quant_system.api.safety.local_session import CSRF_COOKIE_NAME, CSRF_HEADER_NAME


def refresh_all(client: httpx.Client, *, deadline_seconds: float = 600) -> list[dict]:
    client.get("/api/auth/owner/session").raise_for_status()
    csrf = client.cookies.get(CSRF_COOKIE_NAME)
    if not csrf:
        raise RuntimeError("market_assessment_owner_session_unavailable")
    pending = set()
    for scope in ("us", "asia"):
        response = client.post(
            "/api/market-assessment/refresh",
            json={"scope": scope, "include_ai": True},
            headers={CSRF_HEADER_NAME: csrf},
        )
        response.raise_for_status()
        pending.add(scope)
    deadline = time.monotonic() + deadline_seconds
    results = []
    while pending:
        for scope in sorted(pending):
            response = client.get("/api/market-assessment", params={"scope": scope})
            response.raise_for_status()
            document = response.json()
            if document["status"] == "updating":
                continue
            analysis = document.get("ai_analysis")
            results.append(
                {
                    "scope": scope,
                    "status": document["status"],
                    "as_of": document["as_of"],
                    "coverage": document["coverage"],
                    "model": analysis.get("model") if analysis else None,
                    "reasoning_effort": analysis.get("reasoning_effort") if analysis else None,
                    "ai_ready": bool(
                        analysis
                        and not document["ai_error"]
                        and analysis.get("input_digest") == document["input_digest"]
                    ),
                    "error": document["ai_error"],
                }
            )
            pending.remove(scope)
        if pending:
            if time.monotonic() >= deadline:
                raise TimeoutError("market_assessment_update_still_running")
            time.sleep(3)
    return results


def main() -> int:
    try:
        with httpx.Client(
            base_url="http://127.0.0.1:8765",
            headers={"Origin": "http://127.0.0.1:3001"},
            timeout=15,
        ) as client:
            results = refresh_all(client)
        print(json.dumps({"market_assessments": results}, ensure_ascii=False))
        return (
            0
            if all(item["ai_ready"] and item["status"] in {"ready", "partial"} for item in results)
            else 1
        )
    except (httpx.HTTPError, ValueError, KeyError, RuntimeError, TimeoutError) as exc:
        print(json.dumps({"market_assessment_refresh_error": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
