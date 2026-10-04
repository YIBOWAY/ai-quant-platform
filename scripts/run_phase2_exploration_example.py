#!/usr/bin/env python3
"""Real saved-Futu engineering replay to frozen, unsubmitted intake material."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from quant_system.research.behavior_review import run_research_exploration
from quant_system.research.exploration_admission import prepare_exploration_candidate

SYMBOLS = ["AAPL", "MSFT", "NVDA", "SPY"]
EXPRESSION = "$close/Ref($close,5)-1"
SOURCE = """
def compute(ohlcv, context):
    close = ohlcv.close.where(ohlcv.available_at <= ohlcv.timestamp)
    score = close / close.groupby(ohlcv.symbol).shift(5) - 1
    return ohlcv[['symbol','timestamp']].assign(score=score.where(ohlcv.eligible & close.notna()))
"""


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prices-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--sessions", type=int, default=32)
    args = parser.parse_args()
    if not 30 <= args.sessions <= 64:
        parser.error("real engineering sample requires 30..64 sessions")
    output = args.output_dir.resolve()
    if output.is_relative_to(args.prices_root.resolve()):
        parser.error("output must not be written into the source price directory")
    output.mkdir(parents=True, exist_ok=False)
    frames, evidence = [], []
    try:
        for symbol in SYMBOLS:
            path, meta_path = (
                args.prices_root / f"{symbol}.parquet",
                args.prices_root / f"{symbol}.metadata.json",
            )
            metadata = json.loads(meta_path.read_text())
            if metadata.get("sha256") != sha(path) or metadata.get("status") != "available":
                raise ValueError("source_price_metadata_digest_mismatch")
            frame = pd.read_parquet(path)
            if (
                set(frame.symbol) != {symbol}
                or set(frame.provider) != {"futu"}
                or set(frame.price_adjustment) != {"qfq"}
                or set(frame.interval) != {"1d"}
            ):
                raise ValueError("real_daily_futu_qfq_required")
            frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
            if frame.duplicated(["symbol", "timestamp"]).any():
                raise ValueError("duplicate_price_rows")
            evidence.append(
                {
                    "symbol": symbol,
                    "path": str(path.resolve()),
                    "sha256": sha(path),
                    "metadata_sha256": sha(meta_path),
                    "knowledge_ts_min": str(frame.knowledge_ts.min()),
                    "knowledge_ts_max": str(frame.knowledge_ts.max()),
                }
            )
            frames.append(frame)
        common = sorted(set.intersection(*(set(frame.timestamp) for frame in frames)))
        if len(common) < args.sessions:
            raise ValueError("insufficient_common_real_sessions")
        selected = common[-args.sessions :]
        bars = pd.concat(
            [frame[frame.timestamp.isin(selected)] for frame in frames], ignore_index=True
        )
        bars = bars[["symbol", "timestamp", "open", "high", "low", "close", "volume"]]
        if bars.isna().any().any():
            raise ValueError("missing_real_market_values")
        # These are daily session labels, not claimed historical publish times.
        # Today's adjusted snapshot is deliberately NOT presented as a PIT vintage.
        bars["available_at"] = bars.timestamp
        bars["eligible"] = True
        provenance = {
            "source": "futu",
            "adjustment": "qfq",
            "scope": "retrospective_engineering_example",
            "universe_mode": "explicit_static_four_symbols",
            "symbols": SYMBOLS,
            "sessions": len(selected),
            "start": str(selected[0]),
            "end": str(selected[-1]),
            "availability_semantics": (
                "historical session-bar-order assumption; not publication-time evidence"
            ),
            "historical_pit_verified": False,
            "corporate_action_vintage_verified": False,
            "files": evidence,
        }
        with tempfile.TemporaryDirectory(prefix="phase2-real-exploration-") as temporary:
            run_dir = Path(temporary) / "run"
            result = run_research_exploration(
                SOURCE, bars, {}, expression=EXPRESSION, output_dir=run_dir
            )
            shutil.copytree(run_dir, output / "run")
        if result["status"] != "research_candidate":
            raise ValueError("real_exploration_not_verified")
        material = {
            "source_urls": [
                "https://openapi.futunn.com/futu-api-doc/en/quote/request-history-kline.html"
            ],
            "source_title": "Local 5-session momentum engineering replay on saved Futu daily bars",
            "published_at": None,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "hypothesis": (
                "A locally specified five-session close momentum formula used to verify "
                "the code-to-intake path; not an external paper or investment claim."
            ),
            "adaptation_note": (
                "The URL describes the data interface only. The formula is locally specified. "
                "Saved QFQ data were collected later than these sessions; historical publication "
                "times and adjustment vintages are not proven. This static four-symbol sample "
                "does not establish broad-universe quality, economic effectiveness, DSR "
                "or capital eligibility."
            ),
        }
        candidate = prepare_exploration_candidate(
            output / "run",
            source_material=material,
            ordered_symbols=SYMBOLS,
            data_provenance=provenance,
        )
        for name, value in [
            ("price-provenance.json", provenance),
            ("frozen-candidate.json", candidate),
        ]:
            with (output / name).open("x") as handle:
                json.dump(
                    value, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
                )
        (output / "script-snapshot.py").write_bytes(Path(__file__).read_bytes())
        print(
            json.dumps(
                {
                    "status": candidate["status"],
                    "candidate_digest": candidate["candidate_digest"],
                    "symbols": SYMBOLS,
                    "sessions": len(selected),
                    "queue_submitted": False,
                    "capital_authorized": False,
                }
            ),
            flush=True,
        )
        return 0
    except Exception as exc:
        with (output / "failure.json").open("x") as handle:
            json.dump(
                {"status": "not_evaluated", "error_type": type(exc).__name__, "reason": str(exc)},
                handle,
            )
        print(json.dumps({"status": "not_evaluated", "reason": str(exc)}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
