from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.paper_strategy_sleeves import (
    StrategyExecutionPlan,
    StrategySignal,
    StrategySleeve,
)

OBSERVATION_SCHEMA_VERSION = 1
DEFAULT_OBSERVATION_LIMIT = 200
MAX_OBSERVATION_LIMIT = 500


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _object_without_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _strict_json_loads(value: str) -> Any:
    return json.loads(
        value,
        parse_constant=_reject_json_constant,
        object_pairs_hook=_object_without_duplicate_keys,
    )


class PaperStrategyObservationReader:
    """Read bounded strategy-sleeve observations without mutation or recovery."""

    def __init__(
        self,
        storage: PaperStrategySleeveStorage,
        *,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.storage = storage
        self.now = now

    def read(
        self,
        *,
        from_date: str | date | None = None,
        to_date: str | date | None = None,
        signal_id: str | None = None,
        limit: int = DEFAULT_OBSERVATION_LIMIT,
    ) -> dict[str, Any]:
        if limit < 1 or limit > MAX_OBSERVATION_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_OBSERVATION_LIMIT}")
        normalized_from = self._date_text(from_date, name="from_date")
        normalized_to = self._date_text(to_date, name="to_date")
        if (
            normalized_from is not None
            and normalized_to is not None
            and normalized_from > normalized_to
        ):
            raise ValueError("from_date must not be after to_date")
        # Capture the watermark before scanning multiple atomic files. This is
        # conservative: a later write can never be claimed as covered merely
        # because the scan itself took time.
        snapshot_at = self._snapshot_at(self.now())
        query = {
            "from_date": normalized_from,
            "to_date": normalized_to,
            "signal_id": signal_id,
            "limit": limit,
        }
        quality = {
            "pending_sleeve_count": 0,
            "pending_journal_count": 0,
            "corrupt_journal_count": 0,
            "recovery_required_count": 0,
        }
        observations: list[dict[str, Any]] = []
        executions_by_signal: dict[str, list[tuple[StrategySleeve, StrategyExecutionPlan]]] = {}
        execution_records: list[StrategyExecutionPlan] = []
        sleeve_signals: list[tuple[StrategySleeve, StrategySignal]] = []
        committed_journals: list[tuple[str, str, StrategyExecutionPlan]] = []
        try:
            quality["pending_sleeve_count"] = self.storage.count_pending_sleeve_files()
            quality["pending_journal_count"] = self.storage.count_pending_execution_journal_files()
            quality["corrupt_journal_count"] = self.storage.count_corrupt_execution_journal_files()
            self._validate_source_json_files()
            layout_error = self._physical_layout_error()
            if layout_error is not None:
                return self._degraded_payload(
                    snapshot_at=snapshot_at,
                    query=query,
                    quality=quality,
                    error=layout_error,
                )
            (
                committed_journals,
                committed_journal_errors,
            ) = self._read_committed_execution_journals()
            if committed_journal_errors:
                quality["corrupt_journal_count"] += len(committed_journal_errors)
                return self._degraded_payload(
                    snapshot_at=snapshot_at,
                    query=query,
                    quality=quality,
                    error=committed_journal_errors[0],
                )
            sleeves = self.storage.list_sleeves()
            for sleeve in sleeves:
                signals = self.storage.load_signals(sleeve.sleeve_id)
                executions = self.storage.load_executions(sleeve.sleeve_id)
                for signal in signals:
                    self._validate_signal_time_identity(signal)
                for execution in executions:
                    self._validate_execution_time_identity(execution)
                sleeve_signals.extend((sleeve, item) for item in signals)
                for execution in executions:
                    execution_records.append(execution)
                    executions_by_signal.setdefault(execution.signal_id, []).append(
                        (sleeve, execution)
                    )
                    if execution.blocked_reason == "recovery_required":
                        quality["recovery_required_count"] += 1
            json.dumps(
                {
                    "sleeves": [sleeve.model_dump(mode="json") for sleeve in sleeves],
                    "signals": [
                        signal.model_dump(mode="json") for _sleeve, signal in sleeve_signals
                    ],
                    "executions": [
                        execution.model_dump(mode="json") for execution in execution_records
                    ],
                },
                allow_nan=False,
            )
        except (
            json.JSONDecodeError,
            OSError,
            TypeError,
            UnicodeError,
            ValidationError,
            ValueError,
        ):
            return self._degraded_payload(
                snapshot_at=snapshot_at,
                query=query,
                quality=quality,
                error={
                    "code": "strategy_observation_data_unreadable",
                    "message": "strategy observation data is unreadable",
                },
            )

        if any(quality.values()):
            return self._degraded_payload(
                snapshot_at=snapshot_at,
                query=query,
                quality=quality,
                error={
                    "code": "strategy_observation_quality_incomplete",
                    "message": "strategy action coverage has unresolved recovery state",
                },
            )

        seen_execution_ids: set[str] = set()
        executions_by_identity: dict[tuple[str, str], StrategyExecutionPlan] = {}
        for execution in execution_records:
            if execution.execution_id in seen_execution_ids:
                return self._degraded_payload(
                    snapshot_at=snapshot_at,
                    query=query,
                    quality=quality,
                    error={
                        "code": "duplicate_execution_id",
                        "message": "duplicate strategy execution identity detected",
                        "execution_id": execution.execution_id,
                    },
                )
            seen_execution_ids.add(execution.execution_id)
            executions_by_identity[(execution.sleeve_id, execution.execution_id)] = execution

        for sleeve_id, execution_id, journal_execution in committed_journals:
            canonical_execution = executions_by_identity.get((sleeve_id, execution_id))
            if canonical_execution is None:
                quality["corrupt_journal_count"] += 1
                return self._degraded_payload(
                    snapshot_at=snapshot_at,
                    query=query,
                    quality=quality,
                    error={
                        "code": "orphan_committed_execution_journal",
                        "message": (
                            "committed strategy execution journal has no canonical execution"
                        ),
                        "execution_id": execution_id,
                    },
                )
            if canonical_execution != journal_execution:
                quality["corrupt_journal_count"] += 1
                return self._degraded_payload(
                    snapshot_at=snapshot_at,
                    query=query,
                    quality=quality,
                    error={
                        "code": "inconsistent_committed_execution_journal",
                        "message": (
                            "committed strategy execution journal does not match "
                            "the canonical execution"
                        ),
                        "execution_id": execution_id,
                    },
                )

        seen_signal_ids: set[str] = set()
        signals_by_id: dict[str, tuple[StrategySleeve, StrategySignal]] = {}
        for owning_sleeve, signal in sleeve_signals:
            if signal.signal_id in seen_signal_ids:
                return self._degraded_payload(
                    snapshot_at=snapshot_at,
                    query=query,
                    quality=quality,
                    error={
                        "code": "duplicate_signal_id",
                        "message": "duplicate strategy signal identity detected",
                        "signal_id": signal.signal_id,
                    },
                )
            seen_signal_ids.add(signal.signal_id)
            signals_by_id[signal.signal_id] = (owning_sleeve, signal)
            if not self._signal_relationship_is_consistent(owning_sleeve, signal):
                return self._degraded_payload(
                    snapshot_at=snapshot_at,
                    query=query,
                    quality=quality,
                    error={
                        "code": "inconsistent_signal_relationship",
                        "message": "strategy signal identity does not match its sleeve",
                        "signal_id": signal.signal_id,
                    },
                )
        for linked_signal_id in sorted(executions_by_signal):
            if len(executions_by_signal[linked_signal_id]) > 1:
                return self._degraded_payload(
                    snapshot_at=snapshot_at,
                    query=query,
                    quality=quality,
                    error={
                        "code": "multiple_executions_for_signal",
                        "message": "multiple strategy executions reference one signal",
                        "signal_id": linked_signal_id,
                    },
                )
            if linked_signal_id not in seen_signal_ids:
                _owning_sleeve, execution = executions_by_signal[linked_signal_id][0]
                return self._degraded_payload(
                    snapshot_at=snapshot_at,
                    query=query,
                    quality=quality,
                    error={
                        "code": "orphan_execution_signal",
                        "message": "strategy execution references a missing signal",
                        "execution_id": execution.execution_id,
                        "signal_id": linked_signal_id,
                    },
                )
            owning_sleeve, execution = executions_by_signal[linked_signal_id][0]
            _signal_sleeve, signal = signals_by_id[linked_signal_id]
            if not self._execution_relationship_is_consistent(
                owning_sleeve,
                signal,
                execution,
            ):
                return self._degraded_payload(
                    snapshot_at=snapshot_at,
                    query=query,
                    quality=quality,
                    error={
                        "code": "inconsistent_execution_relationship",
                        "message": (
                            "strategy execution identity does not match its signal and sleeve"
                        ),
                        "execution_id": execution.execution_id,
                        "signal_id": linked_signal_id,
                    },
                )

        for sleeve, signal in sleeve_signals:
            if query["from_date"] is not None and signal.signal_date < query["from_date"]:
                continue
            if query["to_date"] is not None and signal.signal_date > query["to_date"]:
                continue
            if signal_id is not None and signal.signal_id != signal_id:
                continue
            observations.append(
                {
                    "sleeve": self._sleeve_view(sleeve),
                    "signal": signal.model_dump(mode="json"),
                    "executions": [
                        self._execution_view(execution)
                        for _owning_sleeve, execution in executions_by_signal.get(
                            signal.signal_id,
                            [],
                        )
                    ],
                }
            )
        observations.sort(
            key=lambda item: (
                item["signal"]["signal_date"],
                self._aware_datetime(item["signal"]["generated_at"]).astimezone(UTC),
                item["signal"]["signal_id"],
            )
        )
        truncated = len(observations) > limit
        observations = observations[:limit]
        return {
            "schema_version": OBSERVATION_SCHEMA_VERSION,
            "snapshot_at": snapshot_at,
            "read_status": "available" if observations else "empty",
            "query": query,
            "returned_count": len(observations),
            "truncated": truncated,
            "ops_quality": quality,
            "observations": observations,
            "errors": [],
        }

    @staticmethod
    def _date_text(value: str | date | None, *, name: str) -> str | None:
        if isinstance(value, date):
            return value.isoformat()
        if value is None:
            return None
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO date in YYYY-MM-DD format") from exc

    @staticmethod
    def _sleeve_view(sleeve: StrategySleeve) -> dict[str, Any]:
        return {
            "sleeve_id": sleeve.sleeve_id,
            "account_id": sleeve.account_id,
            "strategy_config_id": sleeve.strategy_config_id,
            "strategy_config_version": sleeve.strategy_config_version,
            "mode": sleeve.mode,
            "status": sleeve.status,
        }

    @staticmethod
    def _execution_view(execution: StrategyExecutionPlan) -> dict[str, Any]:
        return {
            "execution_id": execution.execution_id,
            "signal_id": execution.signal_id,
            "sleeve_id": execution.sleeve_id,
            "account_id": execution.account_id,
            "strategy_config_id": execution.strategy_config_id,
            "strategy_config_version": execution.strategy_config_version,
            "execution_window": execution.execution_window,
            "target_date": execution.target_date,
            "created_at": execution.created_at,
            "updated_at": execution.updated_at,
            "status": execution.status,
            "blocked_reason": execution.blocked_reason,
        }

    @staticmethod
    def _signal_relationship_is_consistent(
        sleeve: StrategySleeve,
        signal: StrategySignal,
    ) -> bool:
        return (
            signal.sleeve_id == sleeve.sleeve_id
            and signal.strategy_config_id == sleeve.strategy_config_id
            and signal.strategy_config_version == sleeve.strategy_config_version
        )

    @classmethod
    def _execution_relationship_is_consistent(
        cls,
        sleeve: StrategySleeve,
        signal: StrategySignal,
        execution: StrategyExecutionPlan,
    ) -> bool:
        return (
            execution.sleeve_id == sleeve.sleeve_id
            and execution.account_id == sleeve.account_id
            and execution.signal_id == signal.signal_id
            and execution.strategy_config_id == signal.strategy_config_id
            and execution.strategy_config_version == signal.strategy_config_version
            and cls._aware_datetime(execution.created_at)
            >= cls._aware_datetime(signal.generated_at)
            and cls._aware_datetime(execution.updated_at)
            >= cls._aware_datetime(execution.created_at)
        )

    @staticmethod
    def _snapshot_at(value: datetime) -> str:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("snapshot clock must return a timezone-aware datetime")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @classmethod
    def _validate_signal_time_identity(cls, signal: StrategySignal) -> None:
        cls._canonical_date(signal.signal_date)
        cls._aware_datetime(signal.generated_at)
        if signal.data_as_of is not None:
            cls._aware_datetime(signal.data_as_of)

    @classmethod
    def _validate_execution_time_identity(cls, execution: StrategyExecutionPlan) -> None:
        if execution.target_date is not None:
            cls._canonical_date(execution.target_date)
        cls._aware_datetime(execution.created_at)
        cls._aware_datetime(execution.updated_at)

    @staticmethod
    def _aware_datetime(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("strategy observation timestamps must include a timezone")
        return parsed

    @staticmethod
    def _canonical_date(value: str) -> date:
        parsed = date.fromisoformat(value)
        if value != parsed.isoformat():
            raise ValueError("strategy observation dates must use YYYY-MM-DD")
        return parsed

    def _validate_source_json_files(self) -> None:
        if not self.storage.sleeves_dir.exists():
            return
        for path in sorted(self.storage.sleeves_dir.glob("*/sleeve.json")):
            _strict_json_loads(path.read_text(encoding="utf-8"))
        for pattern in ("*/signals.jsonl", "*/executions.jsonl"):
            for path in sorted(self.storage.sleeves_dir.glob(pattern)):
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        _strict_json_loads(line)

    def _physical_layout_error(self) -> dict[str, Any] | None:
        if not self.storage.sleeves_dir.exists():
            return None
        for directory in sorted(self.storage.sleeves_dir.iterdir()):
            if not directory.is_dir():
                continue
            sleeve_path = directory / "sleeve.json"
            has_activity = any(
                path.exists()
                for path in (
                    directory / "signals.jsonl",
                    directory / "executions.jsonl",
                )
            ) or any((directory / "execution_journal").glob("*.committed.json"))
            if not sleeve_path.exists():
                if has_activity:
                    return {
                        "code": "orphan_strategy_activity_files",
                        "message": "strategy activity exists without sleeve metadata",
                    }
                continue
            sleeve = StrategySleeve.model_validate(
                _strict_json_loads(sleeve_path.read_text(encoding="utf-8"))
            )
            if sleeve.sleeve_id != directory.name:
                return {
                    "code": "inconsistent_sleeve_directory_identity",
                    "message": "strategy sleeve identity does not match its directory",
                    "sleeve_id": sleeve.sleeve_id,
                }
        return None

    def _read_committed_execution_journals(
        self,
    ) -> tuple[
        list[tuple[str, str, StrategyExecutionPlan]],
        list[dict[str, Any]],
    ]:
        if not self.storage.sleeves_dir.exists():
            return [], []
        journals: list[tuple[str, str, StrategyExecutionPlan]] = []
        errors: list[dict[str, Any]] = []
        for path in sorted(self.storage.sleeves_dir.glob("*/execution_journal/*.committed.json")):
            try:
                payload = _strict_json_loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("committed execution journal must be an object")
                journals.append(self._committed_journal_identity(path, payload))
            except (OSError, TypeError, UnicodeError, ValueError):
                errors.append(
                    {
                        "code": "committed_execution_journal_unreadable",
                        "message": ("committed strategy execution journal is unreadable"),
                    }
                )
        return journals, errors

    @classmethod
    def _committed_journal_identity(
        cls,
        path: Path,
        payload: dict[str, Any],
    ) -> tuple[str, str, StrategyExecutionPlan]:
        if payload.get("journal_version") != 1 or isinstance(payload.get("journal_version"), bool):
            raise ValueError("unsupported committed execution journal version")
        sleeve_id = payload.get("sleeve_id")
        execution_id = payload.get("execution_id")
        account_id = payload.get("account_id")
        created_at = payload.get("created_at")
        if not all(
            isinstance(value, str) and value
            for value in (sleeve_id, execution_id, account_id, created_at)
        ):
            raise ValueError("committed execution journal identity is invalid")
        cls._aware_datetime(created_at)
        if path.parents[1].name != sleeve_id or path.name != (f"{execution_id}.committed.json"):
            raise ValueError("committed execution journal path identity is invalid")
        journal_execution = StrategyExecutionPlan.model_validate(payload.get("after_execution"))
        cls._validate_execution_time_identity(journal_execution)
        if (
            journal_execution.execution_id != execution_id
            or journal_execution.sleeve_id != sleeve_id
            or journal_execution.account_id != account_id
        ):
            raise ValueError("committed execution journal payload identity is invalid")
        return sleeve_id, execution_id, journal_execution

    @staticmethod
    def _degraded_payload(
        *,
        snapshot_at: str,
        query: dict[str, Any],
        quality: dict[str, int],
        error: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema_version": OBSERVATION_SCHEMA_VERSION,
            "snapshot_at": snapshot_at,
            "read_status": "degraded",
            "query": query,
            "returned_count": 0,
            "truncated": False,
            "ops_quality": quality,
            "observations": [],
            "errors": [error],
        }
