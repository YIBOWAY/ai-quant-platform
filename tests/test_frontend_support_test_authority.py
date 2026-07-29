import json
from pathlib import Path


def test_frontend_package_exposes_the_exact_node_support_suite() -> None:
    package = json.loads(
        Path("src/frontend/package.json").read_text(encoding="utf-8")
    )

    assert package["scripts"]["test"] == "vitest run"
    assert package["scripts"]["test:support"] == (
        "node --test "
        "tests/support/hermes-fixture-api.test.mjs "
        "tests/support/hermes-e2e-run-root.test.mjs"
    )
