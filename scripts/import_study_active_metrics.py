"""Audit/import already-computed active metrics bound to saved study results.

Explicit import verifies metrics by local recomputation from the saved curve;
it never runs a strategy, fetches prices, or changes the source report.
--data-dir is the backend's actual configured data directory. GET never computes.
"""

import argparse
import json
from pathlib import Path

from quant_system.config.settings import DataSettings, Settings
from quant_system.research.study_active_evidence import (
    evidence_digest,
    import_study_active_evidence,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--expect-digest")
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args(argv)
    if args.audit:
        result = {
            "status": "inspected",
            "evidence_digest": evidence_digest(args.evidence_root),
            "writes": False,
            "statistics_recomputed": False,
        }
    else:
        if not args.expect_digest or not args.data_dir:
            parser.error("import requires --expect-digest and --data-dir")
        result = import_study_active_evidence(
            Settings(data=DataSettings(data_dir=args.data_dir)),
            args.evidence_root,
            expected_evidence_digest=args.expect_digest,
        )
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
