"""Run fixed local admission checks; optionally register the actual result.

Evidence JSON describes input locations only. It cannot supply check results,
commands, scripts, authority or a code digest. No queues, engines, prices,
capital, runtime switch or qualification catalog are modified by this command.
Only --register writes an immutable result into the specified data directory.
"""

import argparse
import json
from pathlib import Path

from quant_system.config.settings import DataSettings, Settings
from quant_system.research.admission_qualifier import (
    SCOPE,
    inspect_data_binding,
    inspect_qualification,
    register_qualification,
)
from quant_system.research.external_intake import strict_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("review", "data", "consumer"), required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--evidence-json", type=Path, required=True)
    parser.add_argument("--register", action="store_true")
    args = parser.parse_args(argv)
    settings = Settings(data=DataSettings(data_dir=args.data_dir.resolve()))
    evidence = strict_json(args.evidence_json.read_text())
    input_digest = None
    try:
        if args.kind == "data":
            input_digest = inspect_data_binding(settings, evidence["validation_path"])[
                "input_digest"
            ]
        operation = register_qualification if args.register else inspect_qualification
        result = operation(
            settings, kind=args.kind, scope=SCOPE, input_digest=input_digest, evidence=evidence
        )
    except (ValueError, OSError, KeyError, TypeError) as exc:
        result = {"status": "not_evaluated", "reason": str(exc), "registered": False}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
