import json
from pathlib import Path


def test_frontend_package_exposes_a_distinct_gate5_support_suite() -> None:
    package = json.loads(
        Path("src/frontend/package.json").read_text(encoding="utf-8")
    )

    assert package["scripts"]["test:gate5-support"] == (
        "node --test "
        "tests/support/hermes-fixture-api.test.mjs "
        "tests/support/hermes-e2e-run-root.test.mjs "
        "scripts/run-hermes-gate5.test.mjs"
    )
