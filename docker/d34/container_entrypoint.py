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
    marker = Path(path) / ".hqa-upstream-commit"
    if marker.is_file():
        return marker.read_text(encoding="utf-8").strip()
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
    if observed["rdagent_commit"] != RDAGENT_COMMIT or observed["qlib_commit"] != QLIB_COMMIT:
        raise RuntimeError("pinned upstream commit mismatch")
    return observed


def qlib_smoke() -> dict[str, object]:
    import pandas as pd  # noqa: PLC0415
    import qlib  # noqa: PLC0415
    from qlib.contrib.evaluate import backtest_daily  # noqa: PLC0415
    from qlib.contrib.strategy import TopkDropoutStrategy  # noqa: PLC0415
    from qlib.data import D  # noqa: PLC0415

    with tempfile.TemporaryDirectory(prefix="d34-qlib-smoke-") as raw:
        root = Path(raw)
        csv_dir, provider = root / "csv", root / "provider"
        csv_dir.mkdir()
        # Keep one extra trading day in the provider because Qlib resolves the
        # decision made at ``end_time`` against the next exchange calendar step.
        days = pd.bdate_range("2026-01-05", periods=16)
        for symbol, offset, drift in (("SPY", 100.0, 1.0), ("QQQ", 80.0, 1.4)):
            rows = []
            for index, day in enumerate(days):
                close = offset + index * drift + (index % 3 - 1) * 0.2
                rows.append(
                    {
                        "date": day.date().isoformat(),
                        "symbol": symbol,
                        "open": close - 0.5,
                        "high": close + 1,
                        "low": close - 1,
                        "close": close,
                        "volume": 1_000_000,
                        "factor": 1.0,
                    }
                )
            pd.DataFrame(rows).to_csv(csv_dir / f"{symbol}.csv", index=False)
        subprocess.run(
            [
                sys.executable,
                "/opt/qlib/scripts/dump_bin.py",
                "dump_all",
                "--data_path",
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
        start, end = days[0], days[-2]
        frame = D.features(["SPY", "QQQ"], ["$close"], start_time=start, end_time=end)
        if frame.empty or len(frame) != 30:
            raise RuntimeError("Qlib provider smoke returned incomplete data")
        scores = (
            D.features(
                ["SPY", "QQQ"],
                ["$close/Ref($close,1)-1"],
                start_time=start,
                end_time=end,
            )
            .iloc[:, 0]
            .dropna()
        )
        strategy = TopkDropoutStrategy(
            signal=scores,
            topk=1,
            n_drop=1,
            hold_thresh=0,
            risk_degree=0.99,
            only_tradable=True,
            forbid_all_trade_at_limit=False,
        )
        report, _positions = backtest_daily(
            start_time=start,
            end_time=end,
            strategy=strategy,
            account=100_000.0,
            benchmark="SPY",
            exchange_kwargs={
                "deal_price": "$open",
                "open_cost": 0.0005,
                "close_cost": 0.0005,
                "min_cost": 0,
                "trade_unit": 1,
                "limit_threshold": None,
            },
        )
        if report.empty or not {"return", "cost"}.issubset(report.columns):
            raise RuntimeError("Qlib backtest smoke returned no portfolio report")
        return {
            "contract": "hqa.d34_qlib_smoke/v1",
            "rows": len(frame),
            "backtest_rows": len(report),
            "last_close": float(frame.loc[("SPY", end), "$close"]),
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
            "qlib-adapt",
            "llm-smoke",
            "futu-smoke",
            "docker-smoke",
            "smoke",
            "research",
            "rdagent",
            "qrun",
        ),
    )
    parser.add_argument("args", nargs=argparse.REMAINDER)
    parsed = parser.parse_args()
    if parsed.command in {"rdagent", "qrun"}:
        os.execvp(parsed.command, [parsed.command, *parsed.args])
    if parsed.command == "research":
        research_parser = argparse.ArgumentParser(prog="d34 research")
        research_parser.add_argument("--request", required=True)
        research_parser.add_argument("--output-root", default="/workspace/d34/research-results")
        research_args = research_parser.parse_args(parsed.args)
        from quant_system.d34.rdagent_qlib_runtime import (  # noqa: PLC0415
            run_container_research,
        )

        result = run_container_research(
            request_path=research_args.request,
            output_root=research_args.output_root,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    if parsed.command == "qlib-adapt":
        adapter_parser = argparse.ArgumentParser(prog="d34 qlib-adapt")
        adapter_parser.add_argument("--snapshot-id", required=True)
        adapter_parser.add_argument("--snapshot-digest", required=True)
        adapter_parser.add_argument("--snapshot-parquet", required=True)
        adapter_parser.add_argument("--output-root", required=True)
        adapter_args = adapter_parser.parse_args(parsed.args)
        from quant_system.d34.qlib_adapter import build_qlib_provider  # noqa: PLC0415

        receipt = build_qlib_provider(
            snapshot_id=adapter_args.snapshot_id,
            snapshot_digest=adapter_args.snapshot_digest,
            snapshot_parquet=adapter_args.snapshot_parquet,
            qlib_repo="/opt/qlib",
            qlib_commit=QLIB_COMMIT,
            output_root=adapter_args.output_root,
            python_executable=sys.executable,
        )
        print(
            json.dumps(
                {
                    "contract": receipt.contract,
                    "snapshot_id": receipt.snapshot_id,
                    "snapshot_digest": receipt.snapshot_digest,
                    "qlib_commit": receipt.qlib_commit,
                    "provider_uri": str(receipt.provider_uri),
                    "source_digest": receipt.source_digest,
                    "provider_digest": receipt.provider_digest,
                    "future_calendar_boundary": receipt.future_calendar_boundary,
                    "receipt_digest": receipt.receipt_digest,
                },
                sort_keys=True,
            )
        )
        return 0
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
