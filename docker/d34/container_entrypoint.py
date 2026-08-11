#!/usr/bin/env python3
"""Small observable entrypoint for the pinned D-34 research image."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

RDAGENT_COMMIT = "274e274d5dbb72cc2ea139d1a7c93d73ce9b1198"
QLIB_COMMIT = "da920b7f954f48ab1bb64117c976710de198373e"


def _head(path: str) -> str:
    return subprocess.check_output(
        ["git", "-C", path, "rev-parse", "HEAD"], text=True, timeout=10
    ).strip()


def versions() -> dict[str, object]:
    import qlib  # noqa: PLC0415
    import rdagent  # noqa: F401, PLC0415

    observed = {
        "contract": "hqa.d34_container_versions/v1",
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "rdagent_commit": _head("/opt/rdagent"),
        "qlib_commit": _head("/opt/qlib"),
        "qlib_version": getattr(qlib, "__version__", "unknown"),
    }
    if (
        observed["rdagent_commit"] != RDAGENT_COMMIT
        or observed["qlib_commit"] != QLIB_COMMIT
    ):
        raise RuntimeError("pinned upstream commit mismatch")
    return observed


def qlib_smoke() -> dict[str, object]:
    import pandas as pd  # noqa: PLC0415
    import qlib  # noqa: PLC0415
    from qlib.data import D  # noqa: PLC0415

    with tempfile.TemporaryDirectory(prefix="d34-qlib-smoke-") as raw:
        root = Path(raw)
        csv_dir, provider = root / "csv", root / "provider"
        csv_dir.mkdir()
        rows = []
        for day, close in (("2026-01-05", 100.0), ("2026-01-06", 101.0), ("2026-01-07", 102.0)):
            rows.append(
                {
                    "date": day,
                    "symbol": "SPY",
                    "open": close - 0.5,
                    "high": close + 1,
                    "low": close - 1,
                    "close": close,
                    "volume": 1_000_000,
                    "factor": 1.0,
                }
            )
        pd.DataFrame(rows).to_csv(csv_dir / "SPY.csv", index=False)
        subprocess.run(
            [
                sys.executable,
                "/opt/qlib/scripts/dump_bin.py",
                "dump_all",
                "--csv_path",
                str(csv_dir),
                "--qlib_dir",
                str(provider),
                "--include_fields",
                "open,high,low,close,volume,factor",
                "--symbol_field_name",
                "symbol",
                "--date_field_name",
                "date",
            ],
            check=True,
            timeout=120,
        )
        qlib.init(provider_uri=str(provider), region="us")
        frame = D.features(
            ["SPY"], ["$close"], start_time="2026-01-05", end_time="2026-01-07"
        )
        if frame.empty or len(frame) != 3:
            raise RuntimeError("Qlib provider smoke returned incomplete data")
        return {
            "contract": "hqa.d34_qlib_smoke/v1",
            "rows": len(frame),
            "last_close": float(frame.iloc[-1, 0]),
        }


def llm_smoke() -> dict[str, object]:
    from pydantic import BaseModel  # noqa: PLC0415
    from rdagent.oai.llm_utils import APIBackend  # noqa: PLC0415

    class JsonAnswer(BaseModel):
        ok: bool
        marker: str

    backend = APIBackend()
    response = backend.build_messages_and_create_chat_completion(
        "Return ok=true and marker='d34-smoke'.",
        system_prompt="Respond only with the requested JSON object.",
        response_format=JsonAnswer,
    )
    parsed = JsonAnswer.model_validate_json(response)
    embedding = backend.create_embedding("D-34 embedding smoke")
    if parsed.ok is not True or parsed.marker != "d34-smoke" or not embedding:
        raise RuntimeError("RD-Agent LLM or embedding smoke failed")
    return {
        "contract": "hqa.d34_llm_smoke/v1",
        "json_mode": True,
        "embedding_dimensions": len(embedding),
    }


def futu_smoke() -> dict[str, object]:
    host = os.environ.get("D34_FUTU_HOST", "host.docker.internal")
    port = int(os.environ.get("D34_FUTU_PORT", "11111"))
    with socket.create_connection((host, port), timeout=5):
        pass
    return {
        "contract": "hqa.d34_futu_socket_smoke/v1",
        "host": host,
        "port": port,
        "reachable": True,
    }


def docker_child_smoke() -> dict[str, object]:
    import docker  # noqa: PLC0415

    image = os.environ.get("D34_IMAGE_REF")
    if not image:
        raise RuntimeError("D34_IMAGE_REF is required for child-container smoke")
    client = docker.from_env()
    client.ping()
    output = client.containers.run(
        image,
        ["versions"],
        remove=True,
        network_mode="bridge",
        environment={"D34_CHILD_SMOKE": "1"},
    )
    payload = json.loads(output.decode("utf-8"))
    return {
        "contract": "hqa.d34_docker_child_smoke/v1",
        "child_contract": payload["contract"],
        "ok": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=(
            "versions",
            "qlib-smoke",
            "llm-smoke",
            "futu-smoke",
            "docker-smoke",
            "smoke",
            "rdagent",
            "qrun",
        ),
    )
    parser.add_argument("args", nargs=argparse.REMAINDER)
    parsed = parser.parse_args()
    if parsed.command in {"rdagent", "qrun"}:
        os.execvp(parsed.command, [parsed.command, *parsed.args])
    functions = {
        "versions": versions,
        "qlib-smoke": qlib_smoke,
        "llm-smoke": llm_smoke,
        "futu-smoke": futu_smoke,
        "docker-smoke": docker_child_smoke,
    }
    if parsed.command == "smoke":
        result = {name: function() for name, function in functions.items()}
        result["contract"] = "hqa.d34_container_smoke/v1"
    else:
        result = functions[parsed.command]()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
