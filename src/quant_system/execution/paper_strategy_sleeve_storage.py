from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from quant_system.execution.paper_strategy_sleeves import (
    SleeveLot,
    StrategyConfig,
    StrategySignal,
    StrategySleeve,
)


class PaperStrategySleeveStorage:
    """Local source-of-truth storage for Paper Strategy Sleeves MVP-1."""

    def __init__(self, base_dir: str | Path) -> None:
        self.root_dir = Path(base_dir) / "paper_strategy_sleeves"

    @property
    def strategy_configs_dir(self) -> Path:
        return self.root_dir / "strategy_configs"

    @property
    def sleeves_dir(self) -> Path:
        return self.root_dir / "sleeves"

    def strategy_config_dir(self, strategy_config_id: str) -> Path:
        return self.strategy_configs_dir / strategy_config_id

    def strategy_config_path(self, strategy_config_id: str, version: int) -> Path:
        return self.strategy_config_dir(strategy_config_id) / f"config.v{version}.json"

    def strategy_config_metadata_path(self, strategy_config_id: str) -> Path:
        return self.strategy_config_dir(strategy_config_id) / "metadata.json"

    def sleeve_dir(self, sleeve_id: str) -> Path:
        return self.sleeves_dir / sleeve_id

    def sleeve_path(self, sleeve_id: str) -> Path:
        return self.sleeve_dir(sleeve_id) / "sleeve.json"

    def sleeve_lots_path(self, sleeve_id: str) -> Path:
        return self.sleeve_dir(sleeve_id) / "lots.parquet"

    def sleeve_signals_path(self, sleeve_id: str) -> Path:
        return self.sleeve_dir(sleeve_id) / "signals.jsonl"

    def save_strategy_config(self, config: StrategyConfig) -> Path:
        config_dir = self.strategy_config_dir(config.strategy_config_id)
        config_dir.mkdir(parents=True, exist_ok=True)
        path = self.strategy_config_path(config.strategy_config_id, config.version)
        payload = config.model_dump(mode="json")
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != payload:
                raise FileExistsError(
                    f"strategy config version already exists: {path}"
                )
        else:
            self._write_json_atomic(path, payload)
        self._write_strategy_config_metadata(config)
        return path

    def load_strategy_config(
        self,
        strategy_config_id: str,
        *,
        version: int | None = None,
    ) -> StrategyConfig:
        if version is None:
            metadata_path = self.strategy_config_metadata_path(strategy_config_id)
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            version = int(metadata["latest_version"])
        path = self.strategy_config_path(strategy_config_id, version)
        return StrategyConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def save_sleeve(self, sleeve: StrategySleeve) -> Path:
        path = self.sleeve_path(sleeve.sleeve_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(path, sleeve.model_dump(mode="json"))
        return path

    def load_sleeve(self, sleeve_id: str) -> StrategySleeve:
        path = self.sleeve_path(sleeve_id)
        return StrategySleeve.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def save_sleeve_lots(self, sleeve_id: str, lots: list[SleeveLot]) -> Path:
        path = self.sleeve_lots_path(sleeve_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [lot.model_dump(mode="json") for lot in lots]
        frame = pd.DataFrame(
            rows,
            columns=[
                "lot_id",
                "account_id",
                "sleeve_id",
                "symbol",
                "quantity",
                "avg_cost",
                "opened_at",
                "updated_at",
                "source",
            ],
        )
        tmp_path = path.with_suffix(f".parquet.{uuid.uuid4().hex}.tmp")
        frame.to_parquet(tmp_path, index=False)
        self._atomic_replace(tmp_path, path)
        return path

    def load_sleeve_lots(self, sleeve_id: str) -> list[SleeveLot]:
        path = self.sleeve_lots_path(sleeve_id)
        if not path.exists():
            return []
        frame = pd.read_parquet(path)
        return [
            SleeveLot.model_validate(row)
            for row in frame.to_dict(orient="records")
        ]

    def append_signal(self, signal: StrategySignal) -> Path:
        path = self.sleeve_signals_path(signal.sleeve_id)
        signals = self.load_signals(signal.sleeve_id)
        signals.append(signal)
        lines = [
            json.dumps(item.model_dump(mode="json"), sort_keys=True)
            for item in signals
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f".jsonl.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._atomic_replace(tmp_path, path)
        return path

    def load_signals(self, sleeve_id: str) -> list[StrategySignal]:
        path = self.sleeve_signals_path(sleeve_id)
        if not path.exists():
            return []
        signals = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                signals.append(StrategySignal.model_validate(json.loads(line)))
        return signals

    def _write_strategy_config_metadata(self, config: StrategyConfig) -> None:
        metadata_path = self.strategy_config_metadata_path(config.strategy_config_id)
        metadata = self._read_json_if_exists(metadata_path)
        versions = set(metadata.get("versions", []))
        versions.add(config.version)
        payload = {
            "strategy_config_id": config.strategy_config_id,
            "latest_version": max(versions),
            "versions": sorted(versions),
            "name": config.name,
            "archived": config.archived,
            "updated_at": config.updated_at,
        }
        self._write_json_atomic(metadata_path, payload)

    @staticmethod
    def _read_json_if_exists(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    @classmethod
    def _write_json_atomic(cls, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        cls._atomic_replace(tmp_path, path)

    @staticmethod
    def _atomic_replace(src: Path, dst: Path) -> None:
        os.replace(src, dst)
