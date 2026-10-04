"""Explicit new research-only Futu panel; never touches frozen strategy inputs.

Uses the existing read-only provider and preserves each full symbol series in
its own source-tagged file. No provider fallback, account, model or paper calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from quant_system.data.providers.futu import FutuMarketDataProvider, FutuProviderError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--start", default="2014-11-01")
    parser.add_argument("--end", required=True)
    parser.add_argument("--max-symbols", type=int, default=500)
    parser.add_argument("--reserve-quota", type=int, default=120)
    parser.add_argument("--symbols", nargs="*")
    args = parser.parse_args()
    plan_bytes = args.fetch_plan.read_bytes()
    plan = json.loads(plan_bytes)
    requested = args.symbols or [
        r["symbol"] for r in plan["requests"] if r["reason"] == "missing_file"
    ]
    symbols = list(dict.fromkeys(requested))[: args.max_symbols]
    args.out.mkdir(parents=True, exist_ok=True)
    todo = [s for s in symbols if not (args.out / f"{s}.parquet").exists()]
    import futu

    context = futu.OpenQuoteContext(host="127.0.0.1", port=11111)
    try:
        code, quota = context.get_history_kl_quota(get_detail=True)
        if code != futu.RET_OK:
            raise RuntimeError("quota_probe_failed")
        used, remaining, details = quota
        known = {str(d.get("code")) for d in details}
        need = sum(f"US.{s}" not in known for s in todo)
        if remaining - need < args.reserve_quota:
            raise RuntimeError(f"quota_reserve_breached:need={need},remaining={remaining}")
        metadata = {}
        for offset in range(0, len(todo), 100):
            batch = [f"US.{s}" for s in todo[offset : offset + 100]]
            status, info = context.get_stock_basicinfo(market=futu.Market.US, code_list=batch)
            if status != futu.RET_OK:
                raise RuntimeError("security_metadata_query_failed")
            for row in info.to_dict("records"):
                metadata[str(row.get("code"))] = {
                    k: row.get(k)
                    for k in (
                        "code",
                        "name",
                        "stock_id",
                        "stock_type",
                        "exchange_type",
                        "listing_date",
                        "delisting",
                    )
                }
    finally:
        context.close()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    preflight = {
        "source": "futu",
        "adjustment": "qfq",
        "start": args.start,
        "end": args.end,
        "used_quota": used,
        "remaining_quota": remaining,
        "new_symbol_budget": need,
        "reserve_quota": args.reserve_quota,
        "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "requested": symbols,
        "todo": todo,
    }
    (args.out / f"preflight-{stamp}.json").write_text(json.dumps(preflight, indent=2) + "\n")
    provider = FutuMarketDataProvider()
    results = []
    for i, symbol in enumerate(todo):
        started = time.monotonic()
        item = {
            "symbol": symbol,
            "source": "futu",
            "adjustment": "futu_qfq",
            "metadata": metadata.get(f"US.{symbol}"),
        }
        try:
            info = item["metadata"] or {}
            if not info.get("stock_id") or info.get("delisting") is True:
                item.update(status="unavailable", reason="security_identity_unconfirmed")
            else:
                frame = provider.fetch_ohlcv([symbol], start=args.start, end=args.end)
                if frame.empty or frame["timestamp"].duplicated().any():
                    raise ValueError("empty_or_duplicate_bars")
                path = args.out / f"{symbol}.parquet"
                frame.to_parquet(path, index=False)
                item.update(
                    status="available",
                    rows=len(frame),
                    path=str(path.resolve()),
                    first=str(frame.timestamp.min()),
                    last=str(frame.timestamp.max()),
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                )
        except FutuProviderError as exc:
            item.update(status="unavailable", reason=exc.code)
        except ValueError as exc:
            item.update(status="invalid", reason=str(exc))
        item["seconds"] = round(time.monotonic() - started, 3)
        (args.out / f"{symbol}.metadata.json").write_text(
            json.dumps(item, indent=2, default=str) + "\n"
        )
        results.append(item)
        print(
            json.dumps(
                {
                    "index": i + 1,
                    "total": len(todo),
                    **{k: item.get(k) for k in ("symbol", "status", "rows", "reason", "seconds")},
                }
            ),
            flush=True,
        )
        if (
            item.get("reason") in {"provider_unavailable", "provider_timeout", "rate_limited"}
            and len(results) >= 3
            and all(r.get("reason") == item["reason"] for r in results[-3:])
        ):
            break
        time.sleep(0.55)
    (args.out / f"collection-{stamp}.json").write_text(
        json.dumps({"preflight": preflight, "results": results}, indent=2, default=str) + "\n"
    )


if __name__ == "__main__":
    main()
