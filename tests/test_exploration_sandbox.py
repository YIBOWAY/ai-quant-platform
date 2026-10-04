from __future__ import annotations

import pandas as pd
import pytest

from quant_system.research.exploration_sandbox import DockerSandbox


def test_real_docker_executes_only_supplied_factor_and_attests_isolation():
    result = DockerSandbox().run(
        "def compute(ohlcv, context):\n"
        ' return ohlcv[["symbol", "timestamp"]].assign(score=ohlcv.close)\n',
        pd.DataFrame([{"symbol": "A", "timestamp": "2024-01-01", "close": 12.0}]),
        {},
    )
    assert result["status"] == "ok", result
    assert result["scores"][0]["score"] == 12.0
    assert result["isolation"]["network_mode"] == "none"
    assert result["isolation"]["readonly_rootfs"] is True
    assert result["isolation"]["input_readonly"] is True
    assert result["isolation"]["memory_bytes"] == 512 * 1024 * 1024


@pytest.mark.parametrize(
    "case_id,operation",
    [
        ("S01_root_write", 'open("/root-write", "w").write("bad")'),
        ("S02_input_write", 'open("/input/request.json", "w").write("bad")'),
        ("S03_network", '__import__("socket").create_connection(("1.1.1.1", 53), timeout=1)'),
        ("S04_host_secret_path", 'open("/Users/sunyibo/.ssh/id_rsa").read()'),
    ],
)
def test_real_container_blocks_unauthorized_effect(case_id, operation):
    source = "def compute(ohlcv, context):\n    " + operation + "\n"
    result = DockerSandbox().run(source, pd.DataFrame([{"symbol": "A"}]), {})
    assert result["status"] == "error", (case_id, result)
    assert result["reason"] == "factor_exception"


def test_real_container_timeout_has_no_host_fallback():
    result = DockerSandbox(timeout_seconds=0.5).run("while True: pass", pd.DataFrame(), {})
    assert result["status"] == "error"
    assert result["reason"] == "timeout"


def test_missing_local_image_is_not_evaluated():
    result = DockerSandbox(image="qs-nonexistent-exploration-image:never").run(
        "", pd.DataFrame(), {}
    )
    assert result["status"] == "not_evaluated"
    assert result["reason"] == "local_image_unavailable"


def test_real_container_memory_exhaustion_is_not_success():
    result = DockerSandbox().run("x = bytearray(1024 * 1024 * 1024)", pd.DataFrame(), {})
    assert result["status"] == "error"
    assert result["reason"] == "container_failed"
