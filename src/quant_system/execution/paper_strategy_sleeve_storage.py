from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quant_system.execution.paper_strategy_sleeves import (
    SleeveLot,
    StrategyConfig,
    StrategyExecutionPlan,
    StrategySignal,
    StrategySleeve,
    StrategySleeveMode,
)

log = logging.getLogger(__name__)


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

    @property
    def lock_path(self) -> Path:
        return self.root_dir / "paper_strategy_sleeves.lock"

    @contextmanager
    def mutation_lock(
        self,
        *,
        timeout_seconds: float = 30.0,
        poll_seconds: float = 0.05,
    ) -> Iterator[None]:
        """Serialize sleeve metadata mutations across local processes."""
        self.root_dir.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()

            deadline = time.monotonic() + timeout_seconds
            while True:
                try:
                    self._lock_file(handle)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            f"timed out waiting for strategy sleeve lock {self.lock_path}"
                        ) from None
                    time.sleep(poll_seconds)
            try:
                yield
            finally:
                self._unlock_file(handle)

    @staticmethod
    def _lock_file(handle) -> None:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock_file(handle) -> None:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

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

    def pending_sleeve_path(self, sleeve_id: str) -> Path:
        return self.sleeve_dir(sleeve_id) / "sleeve.pending.json"

    def sleeve_lots_path(self, sleeve_id: str) -> Path:
        return self.sleeve_dir(sleeve_id) / "lots.parquet"

    def sleeve_signals_path(self, sleeve_id: str) -> Path:
        return self.sleeve_dir(sleeve_id) / "signals.jsonl"

    def sleeve_executions_path(self, sleeve_id: str) -> Path:
        return self.sleeve_dir(sleeve_id) / "executions.jsonl"

    def demoted_path(self, sleeve_id: str) -> Path:
        return self.sleeve_dir(sleeve_id) / "demoted.json"

    def execution_journal_dir(self, sleeve_id: str) -> Path:
        return self.sleeve_dir(sleeve_id) / "execution_journal"

    def execution_journal_pending_path(
        self,
        sleeve_id: str,
        execution_id: str,
    ) -> Path:
        return self.execution_journal_dir(sleeve_id) / f"{execution_id}.pending.json"

    def execution_journal_committed_path(
        self,
        sleeve_id: str,
        execution_id: str,
    ) -> Path:
        return self.execution_journal_dir(sleeve_id) / f"{execution_id}.committed.json"

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

    def list_strategy_configs(self) -> list[StrategyConfig]:
        if not self.strategy_configs_dir.exists():
            return []
        configs: list[StrategyConfig] = []
        for metadata_path in sorted(self.strategy_configs_dir.glob("*/metadata.json")):
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            configs.append(
                self.load_strategy_config(
                    str(metadata["strategy_config_id"]),
                    version=int(metadata["latest_version"]),
                )
            )
        return configs

    def save_sleeve(self, sleeve: StrategySleeve) -> Path:
        path = self.sleeve_path(sleeve.sleeve_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(path, sleeve.model_dump(mode="json"))
        return path

    def save_pending_sleeve(self, sleeve: StrategySleeve) -> Path:
        path = self.pending_sleeve_path(sleeve.sleeve_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(path, sleeve.model_dump(mode="json"))
        return path

    def finalize_pending_sleeve(self, sleeve_id: str) -> Path:
        pending_path = self.pending_sleeve_path(sleeve_id)
        final_path = self.sleeve_path(sleeve_id)
        if not pending_path.exists():
            if final_path.exists():
                return final_path
            raise FileNotFoundError(pending_path)
        if final_path.exists():
            pending_payload = json.loads(pending_path.read_text(encoding="utf-8"))
            final_payload = json.loads(final_path.read_text(encoding="utf-8"))
            if pending_payload != final_payload:
                raise FileExistsError(f"strategy sleeve already exists: {final_path}")
            pending_path.unlink(missing_ok=True)
            return final_path
        self._atomic_replace(pending_path, final_path)
        return final_path

    def discard_pending_sleeve(self, sleeve_id: str) -> None:
        self.pending_sleeve_path(sleeve_id).unlink(missing_ok=True)

    def load_sleeve(self, sleeve_id: str) -> StrategySleeve:
        path = self.sleeve_path(sleeve_id)
        return StrategySleeve.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def list_sleeves(self) -> list[StrategySleeve]:
        if not self.sleeves_dir.exists():
            return []
        sleeves = []
        for sleeve_path in sorted(self.sleeves_dir.glob("*/sleeve.json")):
            sleeves.append(
                StrategySleeve.model_validate(
                    json.loads(sleeve_path.read_text(encoding="utf-8"))
                )
            )
        return sleeves

    def list_pending_sleeves(self) -> list[StrategySleeve]:
        if not self.sleeves_dir.exists():
            return []
        return [
            StrategySleeve.model_validate(json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(self.sleeves_dir.glob("*/sleeve.pending.json"))
        ]

    def load_demoted_state(self, sleeve_id: str) -> dict[str, Any] | None:
        path = self.demoted_path(sleeve_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("demoted state must be a JSON object")
        return payload

    def save_demoted_state(self, sleeve_id: str, payload: dict[str, Any]) -> Path:
        path = self.demoted_path(sleeve_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(path, payload)
        return path

    def count_pending_sleeve_files(self) -> int:
        """Count pending sleeve files without parsing or reconciling them."""
        if not self.sleeves_dir.exists():
            return 0
        return sum(
            1
            for path in self.sleeves_dir.glob("*/sleeve.pending.json")
            if path.is_file()
        )

    def reconcile_pending_sleeves(self, account) -> list[StrategySleeve]:
        reconciled: list[StrategySleeve] = []
        for sleeve in self.list_pending_sleeves():
            if self.sleeve_path(sleeve.sleeve_id).exists():
                self.discard_pending_sleeve(sleeve.sleeve_id)
                continue
            has_account_allocation = (
                account is not None
                and account.sleeve_cash.get(sleeve.sleeve_id, 0.0) > 0.0
            )
            if sleeve.mode == StrategySleeveMode.ALLOCATED and not has_account_allocation:
                self.discard_pending_sleeve(sleeve.sleeve_id)
                continue
            self.finalize_pending_sleeve(sleeve.sleeve_id)
            reconciled.append(self.load_sleeve(sleeve.sleeve_id))
        return reconciled

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

    def append_execution(self, execution: StrategyExecutionPlan) -> Path:
        executions = self.load_executions(execution.sleeve_id)
        executions.append(execution)
        return self.save_executions(execution.sleeve_id, executions)

    def save_executions(
        self,
        sleeve_id: str,
        executions: list[StrategyExecutionPlan],
    ) -> Path:
        path = self.sleeve_executions_path(sleeve_id)
        lines = [
            json.dumps(item.model_dump(mode="json"), sort_keys=True)
            for item in executions
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f".jsonl.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._atomic_replace(tmp_path, path)
        return path

    def load_executions(self, sleeve_id: str) -> list[StrategyExecutionPlan]:
        path = self.sleeve_executions_path(sleeve_id)
        if not path.exists():
            return []
        executions = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                executions.append(StrategyExecutionPlan.model_validate(json.loads(line)))
        return executions

    def latest_execution_for_signal(
        self,
        sleeve_id: str,
        signal_id: str,
    ) -> StrategyExecutionPlan | None:
        for execution in reversed(self.load_executions(sleeve_id)):
            if execution.signal_id == signal_id:
                return execution
        return None

    def save_execution_journal_pending(
        self,
        *,
        sleeve_id: str,
        execution_id: str,
        payload: dict[str, Any],
    ) -> Path:
        path = self.execution_journal_pending_path(sleeve_id, execution_id)
        self._write_json_atomic(path, payload)
        return path

    def load_pending_execution_journals(self) -> list[dict[str, Any]]:
        if not self.sleeves_dir.exists():
            return []
        journal_records: list[tuple[str, str, dict[str, Any]]] = []
        for path in sorted(self.sleeves_dir.glob("*/execution_journal/*.pending.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                journal_records.append(
                    (str(payload.get("created_at", "")), str(path), payload)
                )
            except (json.JSONDecodeError, OSError) as exc:
                corrupt_path = self._preserve_corrupt_execution_journal(path)
                log.warning(
                    "corrupt paper strategy execution journal preserved: %s -> %s (%s)",
                    path,
                    corrupt_path,
                    exc,
                )
        return [payload for _, _, payload in sorted(journal_records)]

    def count_pending_execution_journal_files(self) -> int:
        """Count pending journal files without parsing, repairing, or renaming them."""
        if not self.sleeves_dir.exists():
            return 0
        return sum(
            1
            for path in self.sleeves_dir.glob(
                "*/execution_journal/*.pending.json"
            )
            if path.is_file()
        )

    def count_corrupt_execution_journal_files(self) -> int:
        """Count execution journals preserved after explicit recovery parsing."""
        if not self.sleeves_dir.exists():
            return 0
        return sum(
            1
            for path in self.sleeves_dir.glob(
                "*/execution_journal/*.corrupt-*.json"
            )
            if path.is_file()
        )

    def commit_execution_journal(self, *, sleeve_id: str, execution_id: str) -> Path:
        pending_path = self.execution_journal_pending_path(sleeve_id, execution_id)
        committed_path = self.execution_journal_committed_path(sleeve_id, execution_id)
        if committed_path.exists():
            pending_path.unlink(missing_ok=True)
            return committed_path
        if not pending_path.exists():
            raise FileNotFoundError(pending_path)
        self._atomic_replace(pending_path, committed_path)
        return committed_path

    @staticmethod
    def _preserve_corrupt_execution_journal(path: Path) -> Path:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
        execution_id = path.name.removesuffix(".pending.json")
        corrupt_path = path.with_name(
            f"{execution_id}.corrupt-{stamp}-{uuid.uuid4().hex[:6]}.json"
        )
        os.replace(path, corrupt_path)
        return corrupt_path

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
