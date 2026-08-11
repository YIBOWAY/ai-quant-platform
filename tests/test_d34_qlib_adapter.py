from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_system.d34.qlib_adapter import build_qlib_provider


def test_adapter_derives_content_bound_qlib_provider_from_snapshot(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    parquet = snapshot_dir / "ohlcv.parquet"
    pd.DataFrame(
        [
            {
                "symbol": "SPY",
                "timestamp": pd.Timestamp("2026-01-02", tz="UTC"),
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
                "volume": 1000.0,
            },
            {
                "symbol": "QQQ",
                "timestamp": pd.Timestamp("2026-01-02", tz="UTC"),
                "open": 200.0,
                "high": 202.0,
                "low": 199.0,
                "close": 201.0,
                "volume": 2000.0,
            },
        ]
    ).to_parquet(parquet, index=False)
    qlib_repo = tmp_path / "qlib"
    (qlib_repo / "scripts").mkdir(parents=True)
    (qlib_repo / "scripts" / "dump_bin.py").write_text("# pinned tool\n")
    calls: list[list[str]] = []
    dumped_sources: list[str] = []

    def run(command: list[str]) -> None:
        calls.append(command)
        dump_source = Path(command[command.index("--data_path") + 1])
        dumped_sources.extend(sorted(path.name for path in dump_source.glob("*.parquet")))
        provider_uri = Path(command[command.index("--qlib_dir") + 1])
        (provider_uri / "calendars").mkdir(parents=True)
        (provider_uri / "calendars" / "day.txt").write_text("2026-01-02\n")
        (provider_uri / "instruments").mkdir()
        (provider_uri / "instruments" / "all.txt").write_text(
            "QQQ\t2026-01-02\t2026-01-02\nSPY\t2026-01-02\t2026-01-02\n"
        )
        (provider_uri / "features" / "spy").mkdir(parents=True)
        (provider_uri / "features" / "spy" / "close.day.bin").write_bytes(b"qlib")

    receipt = build_qlib_provider(
        snapshot_id="snapshot-0123456789abcdef0123456789abcdef",
        snapshot_digest="a" * 64,
        snapshot_parquet=parquet,
        qlib_repo=qlib_repo,
        qlib_commit="da920b7f954f48ab1bb64117c976710de198373e",
        output_root=tmp_path / "derived",
        python_executable="python3.11",
        run=run,
    )

    assert receipt.contract == "hqa.qlib_provider/v1"
    assert receipt.snapshot_digest == "a" * 64
    assert receipt.qlib_commit == "da920b7f954f48ab1bb64117c976710de198373e"
    assert receipt.provider_uri.is_dir()
    assert len(receipt.provider_digest) == 64
    assert receipt.future_calendar_boundary == "2026-01-03"
    assert len(receipt.receipt_digest) == 64
    assert len(calls) == 1
    command = calls[0]
    assert command[:2] == ["python3.11", str(qlib_repo / "scripts" / "dump_bin.py")]
    assert command[2] == "dump_all"
    assert dumped_sources == ["QQQ.parquet", "SPY.parquet"]
    assert command[command.index("--symbol_field_name") + 1] == "symbol"
    assert command[command.index("--date_field_name") + 1] == "date"
    assert command[command.index("--file_suffix") + 1] == ".parquet"
    source = pd.read_parquet(receipt.source_parquet)
    assert source.columns.tolist() == [
        "symbol",
        "date",
        "open",
        "close",
        "high",
        "low",
        "volume",
        "factor",
    ]
    assert source["factor"].tolist() == [1.0, 1.0]
    assert not (receipt.manifest_path.parent / ".dump-source").exists()
    assert (receipt.provider_uri / "calendars" / "day_future.txt").read_text(
        encoding="utf-8"
    ) == "2026-01-02\n2026-01-03\n"
