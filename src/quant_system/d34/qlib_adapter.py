"""Deterministic adapter from canonical D-34 Parquet to pinned Qlib data."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

QLIB_PROVIDER_CONTRACT = "hqa.qlib_provider/v1"


class QlibAdapterError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class QlibProviderReceipt:
    contract: str
    snapshot_id: str
    snapshot_digest: str
    qlib_commit: str
    provider_uri: Path
    source_parquet: Path
    source_digest: str
    provider_digest: str
    receipt_digest: str
    manifest_path: Path


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        raise QlibAdapterError("qlib_provider_empty", "Qlib conversion produced no files")
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(_file_digest(path)))
    return digest.hexdigest()


def _default_run(command: list[str]) -> None:
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=1800)
    if completed.returncode != 0:
        raise QlibAdapterError(
            "qlib_conversion_failed",
            f"Qlib dump_bin failed with exit code {completed.returncode}",
        )


def _receipt_from_manifest(root: Path, raw: dict[str, object]) -> QlibProviderReceipt:
    return QlibProviderReceipt(
        contract=str(raw["contract"]),
        snapshot_id=str(raw["snapshot_id"]),
        snapshot_digest=str(raw["snapshot_digest"]),
        qlib_commit=str(raw["qlib_commit"]),
        provider_uri=root / "provider",
        source_parquet=root / "source" / "all.parquet",
        source_digest=str(raw["source_digest"]),
        provider_digest=str(raw["provider_digest"]),
        receipt_digest=str(raw["receipt_digest"]),
        manifest_path=root / "receipt.json",
    )


def build_qlib_provider(
    *,
    snapshot_id: str,
    snapshot_digest: str,
    snapshot_parquet: str | Path,
    qlib_repo: str | Path,
    qlib_commit: str,
    output_root: str | Path,
    python_executable: str = "python",
    run: Callable[[list[str]], None] = _default_run,
) -> QlibProviderReceipt:
    """Build Qlib's derived cache without changing the authoritative snapshot."""
    if (
        not snapshot_id.startswith("snapshot-")
        or len(snapshot_digest) != 64
        or any(character not in "0123456789abcdef" for character in snapshot_digest)
        or len(qlib_commit) != 40
        or any(character not in "0123456789abcdef" for character in qlib_commit)
    ):
        raise QlibAdapterError("qlib_adapter_validation", "adapter identity is invalid")
    source_path = Path(snapshot_parquet)
    dump_script = Path(qlib_repo) / "scripts" / "dump_bin.py"
    if not source_path.is_file() or not dump_script.is_file():
        raise QlibAdapterError(
            "qlib_adapter_unavailable", "snapshot or pinned Qlib dump tool is unavailable"
        )
    identity_digest = hashlib.sha256(f"{snapshot_digest}:{qlib_commit}".encode()).hexdigest()
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"qlib-{identity_digest[:32]}"
    if target.exists():
        try:
            existing = json.loads((target / "receipt.json").read_text(encoding="utf-8"))
            receipt = _receipt_from_manifest(target, existing)
        except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
            raise QlibAdapterError(
                "qlib_provider_collision", "existing Qlib provider receipt is unreadable"
            ) from exc
        if (
            receipt.snapshot_digest != snapshot_digest
            or receipt.qlib_commit != qlib_commit
            or _file_digest(receipt.source_parquet) != receipt.source_digest
            or _tree_digest(receipt.provider_uri) != receipt.provider_digest
        ):
            raise QlibAdapterError(
                "qlib_provider_collision", "existing Qlib provider bytes mismatch their receipt"
            )
        return receipt

    temp = Path(tempfile.mkdtemp(prefix=".qlib-", dir=root))
    try:
        source_dir, provider_uri = temp / "source", temp / "provider"
        source_dir.mkdir()
        provider_uri.mkdir()
        frame = pd.read_parquet(source_path)
        required = {"symbol", "timestamp", "open", "close", "high", "low", "volume"}
        if frame.empty or not required.issubset(frame.columns):
            raise QlibAdapterError(
                "qlib_adapter_validation", "snapshot parquet lacks required Qlib fields"
            )
        derived = pd.DataFrame(
            {
                "symbol": frame["symbol"].astype(str).str.upper(),
                "date": pd.to_datetime(frame["timestamp"], utc=True).dt.strftime("%Y-%m-%d"),
                "open": frame["open"],
                "close": frame["close"],
                "high": frame["high"],
                "low": frame["low"],
                "volume": frame["volume"],
                "factor": 1.0,
            }
        )
        source_parquet_path = source_dir / "all.parquet"
        derived.to_parquet(source_parquet_path, index=False)
        command = [
            python_executable,
            str(dump_script),
            "dump_all",
            "--data_path",
            str(source_dir),
            "--qlib_dir",
            str(provider_uri),
            "--include_fields",
            "open,close,high,low,volume,factor",
            "--symbol_field_name",
            "symbol",
            "--date_field_name",
            "date",
            "--file_suffix",
            ".parquet",
        ]
        run(command)
        if (
            not (provider_uri / "calendars" / "day.txt").is_file()
            or not (provider_uri / "instruments" / "all.txt").is_file()
        ):
            raise QlibAdapterError(
                "qlib_provider_invalid", "Qlib provider is missing calendar or instruments"
            )
        source_digest = _file_digest(source_parquet_path)
        provider_digest = _tree_digest(provider_uri)
        receipt_body = {
            "contract": QLIB_PROVIDER_CONTRACT,
            "snapshot_id": snapshot_id,
            "snapshot_digest": snapshot_digest,
            "qlib_commit": qlib_commit,
            "dump_script_digest": _file_digest(dump_script),
            "source_digest": source_digest,
            "provider_digest": provider_digest,
            "source_file": "source/all.parquet",
            "provider_uri": "provider",
        }
        receipt_digest = hashlib.sha256(_canonical_json(receipt_body)).hexdigest()
        manifest = {**receipt_body, "receipt_digest": receipt_digest}
        (temp / "receipt.json").write_bytes(_canonical_json(manifest) + b"\n")
        temp.rename(target)
        return _receipt_from_manifest(target, manifest)
    finally:
        if temp.exists():
            shutil.rmtree(temp)


__all__ = [
    "QLIB_PROVIDER_CONTRACT",
    "QlibAdapterError",
    "QlibProviderReceipt",
    "build_qlib_provider",
]
