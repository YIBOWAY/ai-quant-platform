from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from quant_system.config.settings import Settings
from quant_system.execution.account import DEFAULT_INITIAL_CASH, PaperAccount
from quant_system.execution.account_repository import PaperAccountBootstrapRequired
from quant_system.execution.account_storage import PaperAccountStorage
from quant_system.execution.d34_execution_context import (
    resolve_d34_execution_policy_context,
)
from quant_system.execution.paper_execution_policy import (
    PaperExecutionBatch,
    PaperExecutionDecision,
    PaperExecutionPolicy,
)
from quant_system.execution.paper_strategy_execution_service import (
    PaperStrategyExecutionError,
    PaperStrategyExecutionService,
)
from quant_system.execution.paper_strategy_signal_service import (
    PaperStrategySignalService,
)
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.paper_strategy_sleeves import (
    PaperStrategySleeveService,
    StrategyExecutionPlan,
    StrategyExecutionStatus,
    StrategySignal,
    StrategySleeve,
)
from quant_system.execution.price_source import PaperPriceSource, PricedQuote


@dataclass(frozen=True)
class PaperStrategyOperationResult:
    processed_count: int
    filled_count: int
    blocked_count: int
    recovered_count: int
    executions: list[StrategyExecutionPlan] = field(default_factory=list)
    account: PaperAccount | None = None


@dataclass(frozen=True)
class PaperStrategySignalBatchResult:
    signal_date: str
    generated_count: int
    skipped_count: int
    signals: list[StrategySignal] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_date": self.signal_date,
            "generated_count": self.generated_count,
            "skipped_count": self.skipped_count,
            "signals": [signal.model_dump(mode="json") for signal in self.signals],
        }


@dataclass(frozen=True)
class _AccountReconcileResult:
    account: PaperAccount | None
    reconciled_sleeves: list[StrategySleeve] = field(default_factory=list)
    recovered: list[StrategyExecutionPlan] = field(default_factory=list)


@dataclass(frozen=True)
class PaperStrategyOpsStatus:
    target_date: str
    sleeve_count: int
    pending_sleeve_count: int
    running_sleeve_count: int
    pending_execution_count: int
    pending_due_count: int
    filled_count: int
    blocked_count: int
    recovery_required_count: int
    pending_journal_count: int
    corrupt_journal_count: int

    def to_dict(self) -> dict[str, int | str]:
        return {
            "target_date": self.target_date,
            "sleeve_count": self.sleeve_count,
            "pending_sleeve_count": self.pending_sleeve_count,
            "running_sleeve_count": self.running_sleeve_count,
            "pending_execution_count": self.pending_execution_count,
            "pending_due_count": self.pending_due_count,
            "filled_count": self.filled_count,
            "blocked_count": self.blocked_count,
            "recovery_required_count": self.recovery_required_count,
            "pending_journal_count": self.pending_journal_count,
            "corrupt_journal_count": self.corrupt_journal_count,
        }


@dataclass(frozen=True)
class PaperStrategyRecoveryResult:
    reconciled_sleeve_count: int
    discarded_sleeve_count: int
    recovered_execution_count: int
    remaining_pending_sleeve_count: int
    remaining_pending_journal_count: int
    corrupt_journal_count: int

    def to_dict(self) -> dict[str, int]:
        return {
            "reconciled_sleeve_count": self.reconciled_sleeve_count,
            "discarded_sleeve_count": self.discarded_sleeve_count,
            "recovered_execution_count": self.recovered_execution_count,
            "remaining_pending_sleeve_count": (self.remaining_pending_sleeve_count),
            "remaining_pending_journal_count": (self.remaining_pending_journal_count),
            "corrupt_journal_count": self.corrupt_journal_count,
        }


class PaperStrategyOpsObserver:
    """Build a best-effort, read-only view without acquiring mutation locks.

    Storage writes are atomic, but counts read across multiple files are not a
    transactionally consistent snapshot when a mutation runs concurrently.
    """

    def __init__(
        self,
        *,
        sleeve_storage: PaperStrategySleeveStorage,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.sleeve_storage = sleeve_storage
        self.today = today

    def observe(
        self,
        *,
        target_date: str | date | None = None,
        execution_window: Literal["next_open"] = "next_open",
    ) -> PaperStrategyOpsStatus:
        if execution_window != "next_open":
            raise ValueError("execution_window must be next_open")
        due_target_date = self._target_date(target_date)
        sleeves = self.sleeve_storage.list_sleeves()
        pending_journal_count = self.sleeve_storage.count_pending_execution_journal_files()
        executions = [
            execution
            for sleeve in sleeves
            for execution in self.sleeve_storage.load_executions(sleeve.sleeve_id)
        ]
        pending_executions = [
            execution
            for execution in executions
            if execution.status == StrategyExecutionStatus.PENDING
        ]
        pending_due = [
            execution
            for execution in pending_executions
            if execution.execution_window == execution_window
            and execution.target_date == due_target_date
        ]
        blocked = [
            execution
            for execution in executions
            if execution.status == StrategyExecutionStatus.BLOCKED
        ]
        filled = [
            execution
            for execution in executions
            if execution.status == StrategyExecutionStatus.FILLED
        ]
        recovery_required = [
            execution for execution in executions if execution.blocked_reason == "recovery_required"
        ]
        return PaperStrategyOpsStatus(
            target_date=due_target_date,
            sleeve_count=len(sleeves),
            pending_sleeve_count=(self.sleeve_storage.count_pending_sleeve_files()),
            running_sleeve_count=sum(1 for sleeve in sleeves if sleeve.status == "running"),
            pending_execution_count=len(pending_executions),
            pending_due_count=len(pending_due),
            filled_count=len(filled),
            blocked_count=len(blocked),
            recovery_required_count=len(recovery_required),
            pending_journal_count=pending_journal_count,
            corrupt_journal_count=(self.sleeve_storage.count_corrupt_execution_journal_files()),
        )

    def _target_date(self, value: str | date | None) -> str:
        if value is None:
            return self.today().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return date.fromisoformat(value).isoformat()


class PaperStrategyOperationsRunner:
    """Single operations seam for strategy-sleeve CLI, API, and schedulers."""

    def __init__(
        self,
        *,
        account_storage: PaperAccountStorage,
        sleeve_storage: PaperStrategySleeveStorage,
        settings: Settings,
        price_source: PaperPriceSource | None = None,
        today: Callable[[], date] = date.today,
        paper_execution_context_provider: Callable[[StrategySleeve], Mapping[str, Any]]
        | None = None,
        paper_policy_decision_recorder: Callable[..., None] | None = None,
    ) -> None:
        self.account_storage = account_storage
        self.sleeve_storage = sleeve_storage
        self.settings = settings
        self.price_source = price_source or PaperPriceSource(settings)
        self.today = today
        self.paper_execution_context_provider = (
            paper_execution_context_provider or self._paper_execution_context
        )
        self.paper_policy_decision_recorder = (
            paper_policy_decision_recorder or self._record_d34_order_policy_decision
        )

    def _record_d34_order_policy_decision(
        self,
        *,
        mandate_id: str,
        workspace_id: str,
        execution_id: str,
        decision: PaperExecutionDecision,
    ) -> None:
        from quant_system.hermes.d34_policy_decision_authority import (  # noqa: PLC0415
            PostgresD34PolicyDecisionAuthority,
        )

        PostgresD34PolicyDecisionAuthority(self.settings).record_order_batch(
            mandate_id=mandate_id,
            workspace_id=workspace_id,
            execution_id=execution_id,
            decision=decision,
        )

    def _paper_execution_context(self, sleeve: StrategySleeve) -> Mapping[str, Any]:
        if str(sleeve.metadata.get("automation_source", "d33")) != "d34":
            return {}
        return resolve_d34_execution_policy_context(
            self.settings,
            workspace_id=str(sleeve.metadata.get("workspace_id", "default")),
        )

    def _current_d34_execution_blocker(self, sleeve: StrategySleeve) -> str | None:
        if str(sleeve.metadata.get("automation_source", "d33")) != "d34":
            return None
        context = self.paper_execution_context_provider(sleeve)
        if context.get("emergency_stop") is True:
            return "automation_emergency_stop_active"
        if context.get("paper_execution_enabled") is not True:
            return "automation_paper_execution_disabled"
        if context.get("mandate_active") is not True:
            return "automation_d34_mandate_inactive"
        if context.get("mandate_paper_execution_allowed") is not True:
            return "automation_d34_mandate_paper_execution_not_allowed"
        return None

    @staticmethod
    def _d34_scoped_frozen_account_authorized(
        sleeve: StrategySleeve,
        context: Mapping[str, Any],
    ) -> bool:
        if (
            sleeve.metadata.get("automation_managed") is not True
            or str(sleeve.metadata.get("automation_source", "")) != "d34"
            or str(sleeve.metadata.get("promotion_scope", "")) != "paper_only"
            or not str(sleeve.metadata.get("artifact_id", ""))
            or not str(sleeve.metadata.get("mandate_id", ""))
            or context.get("emergency_stop") is True
            or context.get("paper_execution_enabled") is not True
            or context.get("mandate_active") is not True
            or context.get("mandate_paper_execution_allowed") is not True
        ):
            return False
        context_mandate_id = context.get("mandate_id")
        return context_mandate_id is None or str(context_mandate_id) == str(
            sleeve.metadata["mandate_id"]
        )

    def _current_automation_execution_blocker(
        self,
        account: PaperAccount,
        sleeve: StrategySleeve,
        plan: StrategyExecutionPlan,
        orders: list[dict[str, Any]],
    ) -> str | None:
        if sleeve.metadata.get("automation_managed") is not True:
            return None
        source = str(sleeve.metadata.get("automation_source", "d33"))
        context = self.paper_execution_context_provider(sleeve) if source == "d34" else {}
        execution_prices = {
            str(order["symbol"]).upper(): float(order["execution_price"])
            for order in orders
        }
        account_prices = {
            symbol: execution_prices.get(symbol, position.avg_cost)
            for symbol, position in account.positions.items()
        }
        aggregate_symbol_values = {
            symbol: position.market_value(account_prices[symbol])
            for symbol, position in account.positions.items()
        }
        lots = self.sleeve_storage.load_sleeve_lots(sleeve.sleeve_id)
        sleeve_equity = sleeve.cash + sum(
            lot.quantity * execution_prices.get(lot.symbol.upper(), lot.avg_cost)
            for lot in lots
        )
        decision = PaperExecutionPolicy().evaluate_batch(
            PaperExecutionBatch(
                source=source,
                workspace_id=str(sleeve.metadata.get("workspace_id", "local-default")),
                account_id=account.account_id,
                sleeve_id=sleeve.sleeve_id,
                orders=orders,
                sleeve_equity=sleeve_equity,
                nav=account.equity(account_prices),
                aggregate_symbol_values=aggregate_symbol_values,
                emergency_stop=context.get("emergency_stop") is True,
                paper_execution_enabled=(
                    context.get("paper_execution_enabled", True) is True
                ),
                mandate_active=context.get("mandate_active") is True,
                mandate_paper_execution_allowed=(
                    context.get("mandate_paper_execution_allowed") is True
                ),
            )
        )
        plan.metadata["paper_execution_policy_decision_at_execution"] = (
            decision.to_dict()
        )
        if source == "d34":
            mandate_id = str(sleeve.metadata.get("mandate_id", ""))
            workspace_id = str(sleeve.metadata.get("workspace_id", "default"))
            try:
                self.paper_policy_decision_recorder(
                    mandate_id=mandate_id,
                    workspace_id=workspace_id,
                    execution_id=plan.execution_id,
                    decision=decision,
                )
            except Exception as exc:  # noqa: BLE001 - durable audit seam
                code = str(getattr(exc, "code", "d34_policy_audit_unavailable"))
                plan.metadata["paper_execution_policy_audit_error"] = code
                return f"automation_{code}"
        return None if decision.allowed else f"automation_{decision.blockers[0]}"

    def generate_signal_once(
        self,
        sleeve_id: str,
        *,
        signal_date: str | date | None = None,
        history_days: int = 180,
    ) -> StrategySignal:
        signal_service = PaperStrategySignalService(
            storage=self.sleeve_storage,
            settings=self.settings,
        )
        with self.account_storage.mutation_lock(), self.sleeve_storage.mutation_lock():
            load_result = self._load_account_after_reconcile(open_if_missing=False)
            account = load_result.account
            if account is None:
                account = PaperAccount.open_new(account_id=self.account_storage.account_id)
            sleeve = self.sleeve_storage.load_sleeve(sleeve_id)
            context = (
                self.paper_execution_context_provider(sleeve)
                if str(sleeve.metadata.get("automation_source", "d33")) == "d34"
                else {}
            )
            config = self.sleeve_storage.load_strategy_config(
                sleeve.strategy_config_id,
                version=sleeve.strategy_config_version,
            )
            return signal_service.generate_daily_signal(
                sleeve=sleeve,
                config=config,
                account=account,
                signal_date=signal_date,
                history_days=history_days,
                allow_frozen_account=self._d34_scoped_frozen_account_authorized(
                    sleeve,
                    context,
                ),
            )

    def generate_due_signals_once(
        self,
        *,
        signal_date: str | date | None = None,
        history_days: int = 180,
        limit: int = 50,
    ) -> PaperStrategySignalBatchResult:
        due_signal_date = self._target_date(signal_date)
        signal_service = PaperStrategySignalService(
            storage=self.sleeve_storage,
            settings=self.settings,
        )
        generated: list[StrategySignal] = []
        skipped_count = 0
        with self.account_storage.mutation_lock(), self.sleeve_storage.mutation_lock():
            load_result = self._load_account_after_reconcile(open_if_missing=False)
            account = load_result.account
            if account is None:
                account = PaperAccount.open_new(account_id=self.account_storage.account_id)
            for sleeve in self.sleeve_storage.list_sleeves():
                if len(generated) >= limit:
                    break
                if sleeve.status == "stopped":
                    skipped_count += 1
                    continue
                existing_for_date = any(
                    signal.signal_date == due_signal_date
                    for signal in self.sleeve_storage.load_signals(sleeve.sleeve_id)
                )
                if existing_for_date:
                    skipped_count += 1
                    continue
                config = self.sleeve_storage.load_strategy_config(
                    sleeve.strategy_config_id,
                    version=sleeve.strategy_config_version,
                )
                generated.append(
                    signal_service.generate_daily_signal(
                        sleeve=sleeve,
                        config=config,
                        account=account,
                        signal_date=due_signal_date,
                        history_days=history_days,
                    )
                )
        return PaperStrategySignalBatchResult(
            signal_date=due_signal_date,
            generated_count=len(generated),
            skipped_count=skipped_count,
            signals=generated,
        )

    def create_execution_once(
        self,
        sleeve_id: str,
        signal_id: str,
        *,
        execution_window: Literal["next_open"] = "next_open",
        target_date: str | date | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> StrategyExecutionPlan:
        sleeve_service = PaperStrategySleeveService(self.sleeve_storage)
        with self.account_storage.mutation_lock(), self.sleeve_storage.mutation_lock():
            load_result = self._load_account_after_reconcile(open_if_missing=False)
            account = load_result.account
            if account is None:
                account = PaperAccount.open_new(account_id=self.account_storage.account_id)
            sleeve = self.sleeve_storage.load_sleeve(sleeve_id)
            signal = self._load_signal(sleeve_id, signal_id)
            plan_metadata = dict(metadata or {})
            allow_frozen_account = False
            if str(sleeve.metadata.get("automation_source", "d33")) == "d34":
                context = self.paper_execution_context_provider(sleeve)
                plan_metadata["paper_execution_policy_context"] = dict(context)
                allow_frozen_account = self._d34_scoped_frozen_account_authorized(
                    sleeve,
                    context,
                )
            return sleeve_service.create_execution_plan(
                account,
                sleeve=sleeve,
                signal=signal,
                execution_window=execution_window,
                target_date=self._target_date(target_date),
                metadata=plan_metadata,
                allow_frozen_account=allow_frozen_account,
            )

    def process_pending_executions_once(
        self,
        *,
        sleeve_id: str | None = None,
        execution_window: Literal["next_open"] = "next_open",
        target_date: str | date | None = None,
        limit: int = 50,
    ) -> PaperStrategyOperationResult:
        execution_service = PaperStrategyExecutionService(
            storage=self.sleeve_storage,
            price_source=self.price_source,
            execution_policy_guard=self._current_automation_execution_blocker,
        )
        processed: list[StrategyExecutionPlan] = []
        filled_count = 0
        blocked_count = 0
        with self.account_storage.mutation_lock(), self.sleeve_storage.mutation_lock():
            load_result = self._load_account_after_reconcile(
                open_if_missing=True,
                execution_service=execution_service,
            )
            account = load_result.account
            if account is None:
                raise RuntimeError("paper account could not be opened")
            recovered = load_result.recovered

            candidates = execution_service.pending_plans(
                sleeve_id=sleeve_id,
                execution_window=execution_window,
                target_date=self._target_date(target_date),
                limit=limit,
            )
            for sleeve, plan in candidates:
                blocker = self._current_d34_execution_blocker(sleeve)
                if blocker is not None:
                    execution_service.block_plan(plan, reason=blocker)
                    processed.append(plan)
                    blocked_count += 1
                    continue
                allow_frozen_account = False
                if (
                    account.kill_switch
                    and str(sleeve.metadata.get("automation_source", "")) == "d34"
                ):
                    allow_frozen_account = self._d34_scoped_frozen_account_authorized(
                        sleeve,
                        self.paper_execution_context_provider(sleeve),
                    )
                try:
                    execution = execution_service.execute_plan(
                        account,
                        sleeve=sleeve,
                        plan=plan,
                        allow_frozen_account=allow_frozen_account,
                    )
                except PaperStrategyExecutionError:
                    execution = plan
                if execution.status == StrategyExecutionStatus.FILLED:
                    filled_count += 1
                elif execution.status == StrategyExecutionStatus.BLOCKED:
                    blocked_count += 1
                processed.append(execution)

            self._save_account_snapshot(account)
            for execution in processed:
                if execution.status == StrategyExecutionStatus.FILLED:
                    execution_service.commit_execution_journal(execution)

            return PaperStrategyOperationResult(
                processed_count=len(processed),
                filled_count=filled_count,
                blocked_count=blocked_count,
                recovered_count=len(recovered),
                executions=processed,
                account=account,
            )

    def ops_status(
        self,
        *,
        target_date: str | date | None = None,
        execution_window: Literal["next_open"] = "next_open",
    ) -> PaperStrategyOpsStatus:
        """Backward-compatible pure observer entry point."""
        return PaperStrategyOpsObserver(
            sleeve_storage=self.sleeve_storage,
            today=self.today,
        ).observe(
            target_date=target_date,
            execution_window=execution_window,
        )

    def recover_pending_once(self) -> PaperStrategyRecoveryResult:
        """Explicitly reconcile crash journals without processing new plans."""
        with self.account_storage.mutation_lock(), self.sleeve_storage.mutation_lock():
            pending_sleeves_before = self.sleeve_storage.count_pending_sleeve_files()
            load_result = self._load_account_after_reconcile(open_if_missing=False)
            pending_sleeves_after = self.sleeve_storage.count_pending_sleeve_files()
            reconciled_sleeve_count = len(load_result.reconciled_sleeves)
            discarded_sleeve_count = max(
                0,
                pending_sleeves_before - pending_sleeves_after - reconciled_sleeve_count,
            )
            return PaperStrategyRecoveryResult(
                reconciled_sleeve_count=reconciled_sleeve_count,
                discarded_sleeve_count=discarded_sleeve_count,
                recovered_execution_count=len(load_result.recovered),
                remaining_pending_sleeve_count=pending_sleeves_after,
                remaining_pending_journal_count=(
                    self.sleeve_storage.count_pending_execution_journal_files()
                ),
                corrupt_journal_count=(self.sleeve_storage.count_corrupt_execution_journal_files()),
            )

    def _load_account_after_reconcile(
        self,
        *,
        open_if_missing: bool,
        execution_service: PaperStrategyExecutionService | None = None,
    ) -> _AccountReconcileResult:
        account = (
            self.account_storage.load_or_open(initial_cash=DEFAULT_INITIAL_CASH)
            if open_if_missing
            else self.account_storage.load()
        )
        if account is None and self.settings.paper_account.db_mode == "canonical":
            raise PaperAccountBootstrapRequired(self.account_storage.account_id)
        reconciled_sleeves = self.sleeve_storage.reconcile_pending_sleeves(account)
        if account is None:
            return _AccountReconcileResult(
                account=None,
                reconciled_sleeves=reconciled_sleeves,
            )
        service = execution_service or PaperStrategyExecutionService(
            storage=self.sleeve_storage,
            price_source=self.price_source,
        )
        recovered = service.reconcile_execution_journals(account, commit=False)
        if recovered:
            self._save_account_snapshot(account)
            for execution in recovered:
                service.commit_execution_journal(execution)
        return _AccountReconcileResult(
            account=account,
            reconciled_sleeves=reconciled_sleeves,
            recovered=recovered,
        )

    def _load_signal(self, sleeve_id: str, signal_id: str) -> StrategySignal:
        for signal in self.sleeve_storage.load_signals(sleeve_id):
            if signal.signal_id == signal_id:
                return signal
        raise FileNotFoundError(f"strategy signal not found: {signal_id}")

    def _save_account_snapshot(self, account: PaperAccount) -> None:
        quotes = self._account_quotes(account)
        self.account_storage.save(
            account,
            prices={symbol: quote.price for symbol, quote in quotes.items()},
            price_metadata={
                symbol: {"kind": quote.price_kind, "as_of": quote.as_of}
                for symbol, quote in quotes.items()
            },
        )

    def _account_quotes(self, account: PaperAccount) -> dict[str, PricedQuote]:
        if not account.positions:
            return {}
        return self.price_source.get_prices(list(account.positions))

    def _target_date(self, value: str | date | None) -> str:
        if value is None:
            return self.today().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return date.fromisoformat(value).isoformat()
