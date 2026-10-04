#!/usr/bin/env python3
"""Re-evaluate the fixed saved 500-engine population; no backtest or ledger writes."""

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from quant_system.research.admission_consumer_checks import run_full_control


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--random-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--peer-snapshot", type=Path, required=True)
    parser.add_argument("--control-version", default="futu24-original-20260920")
    parser.add_argument("--register-consumer", action="store_true")
    parser.add_argument(
        "--probe-one", action="store_true", help="Diagnostic cost estimate; never qualifies."
    )
    args = parser.parse_args()
    output = args.output.resolve()
    if any(
        output.is_relative_to(path.resolve()) or path.resolve().is_relative_to(output)
        for path in (args.random_root, args.data_root)
    ):
        raise ValueError("output_must_be_separate_from_inputs")
    output.mkdir(parents=True, exist_ok=False)
    evidence = {
        "random_root": str(args.random_root),
        "data_root": str(args.data_root),
        "peer_snapshot_path": str(args.peer_snapshot),
        "control_version": args.control_version,
    }
    try:
        result = run_full_control(
            evidence,
            output=output,
            probe_one=args.probe_one,
        )
    except Exception as exc:
        with (output / "failure.json").open("x") as handle:
            json.dump(
                {"status": "not_evaluated", "reason": str(exc), "capital_authorized": False}, handle
            )
        raise
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "n_controls",
                    "statistically_evaluable",
                    "not_evaluated",
                    "gate_passes",
                    "false_pass_rate",
                    "clopper_pearson_upper",
                    "calibration_passed",
                    "failures",
                )
            },
            sort_keys=True,
        )
    )
    if args.register_consumer:
        if args.probe_one:
            raise ValueError("probe_cannot_register_qualification")
        from quant_system.research.admission_qualifier import (
            register_qualification,
            verify_registered_qualification,
        )
        from quant_system.research.admission_v2 import SCOPE, code_identity

        settings = SimpleNamespace(data=SimpleNamespace(data_dir=output / "qualification-store"))
        registered = register_qualification(
            settings, kind="consumer", scope=SCOPE, evidence=evidence
        )
        descriptor = registered["descriptor"]
        verified = verify_registered_qualification(
            settings,
            kind="consumer",
            scope=SCOPE,
            code_digest=code_identity()["digest"],
            input_digest=None,
            descriptor=descriptor,
        )
        with (output / "consumer-qualification.json").open("x") as handle:
            json.dump({"descriptor": descriptor, "verification": verified}, handle, sort_keys=True)
        print(
            json.dumps(
                {
                    "consumer_registration_status": verified["status"],
                    "reason": verified.get("reason"),
                }
            )
        )


if __name__ == "__main__":
    main()
