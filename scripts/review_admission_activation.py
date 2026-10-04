"""Close the current-code parallel cohort; activate only after fixed local checks.

This is a bounded audit executor, not a monitor. It never changes policy,
existing job protocols, prices, trials, sleeves or accounts. Unsupported or
incomplete evidence produces a blocked review and no activation state.
"""

import argparse
import json
from pathlib import Path

from quant_system.config.settings import DataSettings, Settings
from quant_system.research.admission_activation import review_and_activate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--historical-inventory", required=True, type=Path)
    parser.add_argument("--review-only", action="store_true")
    parser.add_argument("--window-manifest", type=Path)
    parser.add_argument("--window-manifest-sha256")
    args = parser.parse_args()
    if (args.window_manifest is None) != (args.window_manifest_sha256 is None):
        parser.error("--window-manifest and --window-manifest-sha256 must be supplied together")
    settings = Settings(data=DataSettings(data_dir=args.data_dir.resolve()))
    result = review_and_activate(
        settings, historical_inventory=args.historical_inventory, activate=not args.review_only,
        window_manifest=args.window_manifest,
        window_manifest_sha256=args.window_manifest_sha256,
    )
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    return 0 if result["status"] in {"ready", "activated"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
