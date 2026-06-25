from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import wait as wait_for_futures
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_system.api.schemas.backtest import BacktestRunRequest
from quant_system.api.schemas.common import (
    RunStatus,
    make_run_id,
    resolve_run_dir,
    write_json_atomic,
)
from quant_system.backtest.pipeline import BacktestCancelledError
from quant_system.backtest.pipeline import run_backtest as execute_backtest
from quant_system.config.settings import Settings
from quant_system.data.provider_factory import DataProviderUnavailableError
from quant_system.storage.runs_repository import index_run, persist_run

log = logging.getLogger(__name__)

_ACTIVE_STATUSES = {
    RunStatus.QUEUED.value,
    RunStatus.RUNNING.value,
    RunStatus.CANCELLING.value,
}
_TERMINAL_STATUSES = {
    RunStatus.COMPLETED.value,
    RunStatus.FAILED.value,
    RunStatus.CANCELLED.value,
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def backtest_job_poll_url(run_id: str) -> str:
    return f"/api/backtests/jobs/{run_id}"


def backtest_job_result_url(metadata: dict[str, Any]) -> str | None:
    if metadata.get("status") == RunStatus.COMPLETED.value:
        return f"/api/backtests/{metadata['run_id']}"
    return None


def backtest_job_response(metadata: dict[str, Any]) -> dict[str, Any]:
    run_id = str(metadata["run_id"])
    return {
        "run_id": run_id,
        "kind": metadata.get("kind", "backtest"),
        "status": metadata["status"],
        "created_at": metadata.get("created_at"),
        "updated_at": metadata.get("updated_at"),
        "poll_url": metadata.get("poll_url") or backtest_job_poll_url(run_id),
        "result_url": backtest_job_result_url(metadata),
        "error": metadata.get("error"),
    }


def backtest_failure_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, (KeyError, ValueError)):
        code = "invalid_backtest_request"
    elif isinstance(exc, DataProviderUnavailableError):
        code = "provider_unavailable"
    else:
        code = "backtest_job_failed"
    return {"code": code, "message": str(exc)}


def execute_backtest_run(
    *,
    request: BacktestRunRequest,
    run_id: str,
    run_dir: Path,
    settings: Settings,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    result = execute_backtest(
        symbols=request.symbols,
        start=request.start,
        end=request.end,
        output_dir=run_dir,
        lookback=request.lookback,
        top_n=request.top_n,
        initial_cash=request.initial_cash,
        commission_bps=request.commission_bps,
        slippage_bps=request.slippage_bps,
        min_order_value=request.min_order_value,
        whole_share_orders=request.whole_share_orders,
        provider=request.provider,
        strategy_id=request.strategy_id,
        universe_id=request.universe_id,
        factor_ids=request.factor_ids,
        weights=request.weights,
        benchmark_symbol=request.benchmark_symbol,
        rebalance_frequency=request.rebalance_frequency,
        max_weight_per_symbol=request.max_weight_per_symbol,
        sector_cap=request.sector_cap,
        sector_map=request.sector_map,
        settings=settings,
        cancel_event=cancel_event,
    )
    return {
        "run_id": run_id,
        "source": result.source,
        "trade_count": result.trade_count,
        "order_count": result.order_count,
        "warnings": result.warnings,
        "timings_ms": result.timings_ms,
        "request": {
            "symbols": result.symbols,
            "start": request.start,
            "end": request.end,
            "provider": request.provider,
            "strategy_id": result.strategy_id,
            "universe_id": result.universe_id,
            "factor_ids": result.factor_ids,
            "weights": result.weights,
            "benchmark_symbol": result.benchmark_symbol,
            "lookback": request.lookback,
            "top_n": request.top_n,
            "initial_cash": request.initial_cash,
            "commission_bps": request.commission_bps,
            "slippage_bps": request.slippage_bps,
            "min_order_value": request.min_order_value,
            "whole_share_orders": request.whole_share_orders,
            "rebalance_frequency": request.rebalance_frequency,
            "max_weight_per_symbol": request.max_weight_per_symbol,
            "sector_cap": request.sector_cap,
            "sector_map": request.sector_map,
        },
        "metrics": {
            "total_return": result.total_return,
            "sharpe": result.sharpe,
            "max_drawdown": result.max_drawdown,
        },
        "attribution": result.attribution,
        "benchmark": {
            "symbol": result.benchmark_symbol,
            "source": result.benchmark_source,
            "metrics": result.benchmark_metrics.model_dump(),
        },
        "paths": {
            "equity_curve": str(result.equity_curve_path),
            "trade_blotter": str(result.trade_blotter_path),
            "orders": str(result.orders_path),
            "positions": str(result.positions_path),
            "attribution": str(result.attribution_path),
            "metrics": str(result.metrics_path),
            "benchmark_curve": str(result.benchmark_curve_path),
            "benchmark_metrics": str(result.benchmark_metrics_path),
            "report": str(result.report_path),
        },
    }


class BacktestJobRunner:
    """Process-local ThreadPool-backed runner for API backtest jobs.

    The filesystem metadata is the source of truth; every state transition uses
    atomic JSON replacement and the optional run index is updated best-effort.
    """

    def __init__(self, *, api_runs_dir: Path, settings: Settings) -> None:
        self._api_runs_dir = Path(api_runs_dir)
        self._settings = settings
        self._executor = ThreadPoolExecutor(
            max_workers=settings.backtest_jobs.max_workers,
            thread_name_prefix="quant-backtest-job",
        )
        self._lock = threading.RLock()
        self._futures: dict[str, Future[None]] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._closed = False

    def submit(self, request: BacktestRunRequest) -> dict[str, Any]:
        run_id = make_run_id("backtest")
        run_dir = self._run_dir(run_id)
        now = utc_now()
        initial_metadata = {
            "run_id": run_id,
            "request": request.model_dump(mode="json"),
            "poll_url": backtest_job_poll_url(run_id),
            "result_url": None,
            "queued_at": now,
            "updated_at": now,
        }
        with self._lock:
            if self._closed:
                raise RuntimeError("backtest job runner is shut down")
            metadata = persist_run(
                run_dir,
                "backtest",
                initial_metadata,
                settings=self._settings,
                status=RunStatus.QUEUED,
            )
            cancel_event = threading.Event()
            self._cancel_events[run_id] = cancel_event
            future = self._executor.submit(self._run_job, request, run_id, cancel_event)
            self._futures[run_id] = future
            future.add_done_callback(lambda done, job_id=run_id: self._forget_future(job_id, done))
            return backtest_job_response(metadata)

    def status(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            return backtest_job_response(self._read_metadata_unlocked(run_id))

    def cancel(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            metadata = self._read_metadata_unlocked(run_id)
            status_value = str(metadata.get("status"))
            now = utc_now()
            future = self._futures.get(run_id)
            cancel_event = self._cancel_events.get(run_id)
            if cancel_event is not None:
                cancel_event.set()
            if status_value == RunStatus.QUEUED.value:
                cancelled_before_start = future.cancel() if future is not None else True
                if cancelled_before_start:
                    metadata.update(
                        {
                            "status": RunStatus.CANCELLED.value,
                            "cancel_requested_at": now,
                            "finished_at": now,
                            "updated_at": now,
                        }
                    )
                else:
                    metadata.update(
                        {
                            "status": RunStatus.CANCELLING.value,
                            "cancel_requested_at": now,
                            "updated_at": now,
                        }
                    )
                return backtest_job_response(self._write_metadata_unlocked(run_id, metadata))
            if status_value == RunStatus.RUNNING.value:
                metadata.update(
                    {
                        "status": RunStatus.CANCELLING.value,
                        "cancel_requested_at": now,
                        "updated_at": now,
                    }
                )
                return backtest_job_response(self._write_metadata_unlocked(run_id, metadata))
            return backtest_job_response(metadata)

    def reconcile_orphaned_jobs(self) -> int:
        root = self._api_runs_dir / "backtests"
        if not root.exists():
            return 0
        recovered = 0
        with self._lock:
            for metadata_path in root.glob("*/metadata.json"):
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    log.warning(
                        "skipping unreadable backtest job metadata %s: %s",
                        metadata_path,
                        exc,
                    )
                    continue
                if metadata.get("status") not in _ACTIVE_STATUSES:
                    continue
                now = utc_now()
                metadata.update(
                    {
                        "status": RunStatus.FAILED.value,
                        "finished_at": now,
                        "updated_at": now,
                        "error": {
                            "code": "job_recovered_after_restart",
                            "message": "Backtest job was interrupted by API restart.",
                        },
                    }
                )
                write_json_atomic(metadata_path, metadata)
                index_run("backtest", metadata, metadata_path.parent, self._settings)
                recovered += 1
        return recovered

    def shutdown(self, *, wait: bool = False, cancel_futures: bool = True) -> None:
        with self._lock:
            self._closed = True
            active = list(self._futures.items())
            for run_id, future in active:
                try:
                    metadata = self._read_metadata_unlocked(run_id)
                except FileNotFoundError:
                    continue
                status_value = str(metadata.get("status"))
                cancel_event = self._cancel_events.get(run_id)
                if cancel_event is not None:
                    cancel_event.set()
                now = utc_now()
                if status_value == RunStatus.QUEUED.value:
                    cancelled_before_start = future.cancel()
                    if cancelled_before_start:
                        metadata.update(
                            {
                                "status": RunStatus.CANCELLED.value,
                                "finished_at": now,
                                "updated_at": now,
                                "error": {
                                    "code": "job_cancelled_on_shutdown",
                                    "message": "Backtest job was cancelled during API shutdown.",
                                },
                            }
                        )
                    else:
                        metadata.update(
                            {
                                "status": RunStatus.CANCELLING.value,
                                "cancel_requested_at": now,
                                "updated_at": now,
                            }
                        )
                    self._write_metadata_unlocked(run_id, metadata)
                elif status_value in {RunStatus.RUNNING.value, RunStatus.CANCELLING.value}:
                    metadata.update(
                        {
                            "status": RunStatus.CANCELLING.value,
                            "cancel_requested_at": metadata.get("cancel_requested_at") or now,
                            "updated_at": now,
                        }
                    )
                    self._write_metadata_unlocked(run_id, metadata)
        unfinished: set[Future[None]] = set()
        if wait and active:
            _, unfinished = wait_for_futures(
                [future for _, future in active],
                timeout=self._settings.backtest_jobs.shutdown_timeout_seconds,
            )
            if unfinished:
                self._mark_shutdown_timeout(active, unfinished)
        with self._lock:
            self._futures.clear()
            self._cancel_events.clear()
        self._executor.shutdown(wait=False, cancel_futures=cancel_futures)

    def _mark_shutdown_timeout(
        self,
        active: list[tuple[str, Future[None]]],
        unfinished: set[Future[None]],
    ) -> None:
        with self._lock:
            now = utc_now()
            for run_id, future in active:
                if future not in unfinished:
                    continue
                try:
                    metadata = self._read_metadata_unlocked(run_id)
                except FileNotFoundError:
                    continue
                if metadata.get("status") not in _ACTIVE_STATUSES:
                    continue
                metadata.update(
                    {
                        "status": RunStatus.CANCELLED.value,
                        "finished_at": now,
                        "updated_at": now,
                        "error": {
                            "code": "job_cancelled_on_shutdown_timeout",
                            "message": "Backtest job did not stop within the API shutdown timeout.",
                        },
                    }
                )
                self._write_metadata_unlocked(run_id, metadata)

    def _run_job(
        self,
        request: BacktestRunRequest,
        run_id: str,
        cancel_event: threading.Event,
    ) -> None:
        started = self._start_job(run_id)
        if started is None:
            self._cancel_if_requested_before_start(run_id)
            return
        run_dir = self._run_dir(run_id)
        try:
            payload = execute_backtest_run(
                request=request,
                run_id=run_id,
                run_dir=run_dir,
                settings=self._settings,
                cancel_event=cancel_event,
            )
        except BacktestCancelledError:
            self._finish_cancelled(run_id)
            return
        except Exception as exc:  # noqa: BLE001 - async failures are job state.
            self._finish_failed(run_id, exc)
            return
        self._finish_completed(run_id, run_dir, payload)

    def _start_job(self, run_id: str) -> dict[str, Any] | None:
        return self._transition(
            run_id,
            from_statuses={RunStatus.QUEUED.value},
            to_status=RunStatus.RUNNING,
            updates={"started_at": utc_now()},
        )

    def _cancel_if_requested_before_start(self, run_id: str) -> None:
        with self._lock:
            try:
                metadata = self._read_metadata_unlocked(run_id)
            except FileNotFoundError:
                return
            if metadata.get("status") in {RunStatus.CANCELLING.value, RunStatus.CANCELLED.value}:
                now = utc_now()
                metadata.update(
                    {
                        "status": RunStatus.CANCELLED.value,
                        "finished_at": metadata.get("finished_at") or now,
                        "updated_at": now,
                    }
                )
                self._write_metadata_unlocked(run_id, metadata)

    def _finish_cancelled(self, run_id: str) -> None:
        with self._lock:
            try:
                metadata = self._read_metadata_unlocked(run_id)
            except FileNotFoundError:
                return
            if metadata.get("status") not in {
                RunStatus.RUNNING.value,
                RunStatus.CANCELLING.value,
                RunStatus.QUEUED.value,
            }:
                return
            now = utc_now()
            metadata.update(
                {
                    "status": RunStatus.CANCELLED.value,
                    "finished_at": now,
                    "updated_at": now,
                }
            )
            self._write_metadata_unlocked(run_id, metadata)

    def _finish_failed(self, run_id: str, exc: Exception) -> None:
        with self._lock:
            try:
                metadata = self._read_metadata_unlocked(run_id)
            except FileNotFoundError:
                return
            if metadata.get("status") not in {
                RunStatus.RUNNING.value,
                RunStatus.CANCELLING.value,
            }:
                return
            now = utc_now()
            metadata.update(
                {
                    "status": RunStatus.FAILED.value,
                    "finished_at": now,
                    "updated_at": now,
                    "error": backtest_failure_error(exc),
                }
            )
            self._write_metadata_unlocked(run_id, metadata)

    def _finish_completed(self, run_id: str, run_dir: Path, payload: dict[str, Any]) -> None:
        with self._lock:
            try:
                metadata = self._read_metadata_unlocked(run_id)
            except FileNotFoundError:
                return
            status_value = str(metadata.get("status"))
            if status_value == RunStatus.CANCELLING.value:
                now = utc_now()
                metadata.update(
                    {
                        "status": RunStatus.CANCELLED.value,
                        "finished_at": now,
                        "updated_at": now,
                    }
                )
                self._write_metadata_unlocked(run_id, metadata)
                return
            if status_value != RunStatus.RUNNING.value:
                return
            now = utc_now()
            payload = {**payload, "finished_at": now, "updated_at": now}
            persist_run(
                run_dir,
                "backtest",
                payload,
                settings=self._settings,
                status=RunStatus.COMPLETED,
            )

    def _transition(
        self,
        run_id: str,
        *,
        from_statuses: set[str],
        to_status: RunStatus,
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            metadata = self._read_metadata_unlocked(run_id)
            if metadata.get("status") not in from_statuses:
                return None
            now = utc_now()
            metadata.update(updates or {})
            metadata["status"] = to_status.value
            metadata["updated_at"] = now
            if to_status.value in _TERMINAL_STATUSES and not metadata.get("finished_at"):
                metadata["finished_at"] = now
            return self._write_metadata_unlocked(run_id, metadata)

    def _forget_future(self, run_id: str, future: Future[None]) -> None:
        with self._lock:
            if self._futures.get(run_id) is future:
                self._futures.pop(run_id, None)
                self._cancel_events.pop(run_id, None)

    def _run_dir(self, run_id: str) -> Path:
        return resolve_run_dir(self._api_runs_dir / "backtests", run_id)

    def _metadata_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "metadata.json"

    def _read_metadata_unlocked(self, run_id: str) -> dict[str, Any]:
        path = self._metadata_path(run_id)
        if not path.exists():
            raise FileNotFoundError(run_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_metadata_unlocked(self, run_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        path = self._metadata_path(run_id)
        write_json_atomic(path, metadata)
        index_run("backtest", metadata, path.parent, self._settings)
        return metadata
