"""Explicitly import one completed frozen wide scorecard into the product store.

Requires an independently checked SHA256 of output-digests.json. No provider,
scorecard recomputation, trial registration, strategy or account operation occurs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from quant_system.config.settings import Settings
from quant_system.factors.scorecard_service import import_wide_scorecard


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--expected-output-manifest-sha256", required=True)
    parser.add_argument("--scorecard-store", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = import_wide_scorecard(
            Settings(),
            args.run_dir,
            expected_output_manifest_sha256=args.expected_output_manifest_sha256,
            output_dir=args.scorecard_store,
        )
    except (ValueError, OSError) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
                    "operation_receipt": str(args.scorecard_store / "operation.json"),
                },
                ensure_ascii=False,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "status": result["status"],
                "run": result["run"],
                "objects": len(result["factors"]),
                "admission_authority": False,
                "href": "/zh/research-evaluation?tab=scorecards",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
