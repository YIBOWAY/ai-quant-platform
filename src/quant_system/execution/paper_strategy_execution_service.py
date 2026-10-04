from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from math import isfinite
from types import MappingProxyType
from typing import Any, NamedTuple

import pandas as pd

from quant_system.config.settings import load_settings
from quant_system.execution.account import PaperAccount
from quant_system.execution.models import ExecutionFill, OrderSide
from quant_system.execution.paper_strategy_sleeves import (
    SleeveLot,
    SleeveLotBook,
    StrategyExecutionFill,
    StrategyExecutionOrder,
    StrategyExecutionPlan,
    StrategyExecutionStatus,
    StrategySleeve,
    StrategySleeveMode,
    StrategySleeveStatus,
)
from quant_system.execution.price_source import PricedQuote, PriceUnavailableError

EPSILON = 1e-9

# Transient price-evidence failures: the only blocked reasons a bounded
# in-run retry may clear. Anything else stays an immediate terminal block.
PRICE_EVIDENCE_RETRY_CODES = frozenset(
    {"price_unavailable", "strategy_definition_open_data_unavailable"}
)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class PaperStrategyExecutionError(ValueError):
    """Raised when a pending strategy execution cannot be processed."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


class _ExecutionStep(NamedTuple):
    order: StrategyExecutionOrder
    side: OrderSide
    symbol: str
    quantity: float
    price: float
    gross_value: float
    quote: PricedQuote
    fill_price: float
    commission: float


@dataclass(frozen=True)
class PreparedExecution:
    """Lock-free price evidence handed from prepare to commit.

    ``quotes`` / ``prices`` are deep copies wrapped in ``MappingProxyType`` so
    the preparation result cannot be aliased or mutated in place; the digest is
    recomputed before any mutation (see ``_prepared_digest``).
    """

    account_id: str
    sleeve_id: str
    execution_id: str
    target_date: str | None
    execution_window: str
    signal_id: str
    strategy_config_id: str
    strategy_config_version: int
    is_definition: bool
    quotes: Mapping[str, PricedQuote]
    prices: Mapping[str, float]
    snapshot_steps: tuple[_ExecutionStep, ...] | None
    prepared_at: str
    prepare_digest: str


def _prepared_digest(
    *,
    account_id: str,
    sleeve_id: str,
    execution_id: str,
    target_date: str | None,
    execution_window: str,
    signal_id: str,
    strategy_config_id: str,
    strategy_config_version: int,
    is_definition: bool,
    quotes: Mapping[str, PricedQuote],
    prices: Mapping[str, float],
) -> str:
    """Content digest of the price evidence and its execution binding.

    ``float.hex()`` is used for the price so the encoding is exact and
    platform-independent rather than relying on the float JSON repr.

    ``prices`` is covered alongside ``quotes`` because the definition path
    prices orders from ``prepared.prices`` (``_recompute_definition``); without
    it a tamper that rewrites only ``prices`` would pass the recompute check
    and size orders off the forged prices. ``snapshot_steps`` is deliberately
    not folded in: the snapshot path already asserts it against freshly
    re-derived steps (``prepared_execution_steps_drift``), and including it here
    would mask that dedicated code with the generic integrity code.
    """
    payload = {
        "account_id": account_id,
        "sleeve_id": sleeve_id,
        "execution_id": execution_id,
        "target_date": target_date,
        "execution_window": execution_window,
        "signal_id": signal_id,
        "strategy_config_id": strategy_config_id,
        "strategy_config_version": strategy_config_version,
        "is_definition": is_definition,
        "quotes": [
            [symbol, float(quote.price).hex(), quote.price_kind, quote.as_of, quote.source]
            for symbol, quote in sorted(quotes.items())
        ],
        "prices": [
            [symbol, float(price).hex()] for symbol, price in sorted(prices.items())
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


ExecutionPolicyGuard = Callable[
    [PaperAccount, StrategySleeve, StrategyExecutionPlan, list[dict[str, Any]]],
    str | None,
]


class PaperStrategyExecutionService:
    """Process Paper Strategy Sleeve execution plans against paper prices."""

    def __init__(
        self,
        *,
        storage,
        price_source,
        execution_policy_guard: ExecutionPolicyGuard | None = None,
        commission_bps: float | None = None,
        slippage_bps: float | None = None,
        definition_open_price_source=None,
        price_retry_max_retries: int = 2,
        price_retry_backoff_seconds: float = 30.0,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        if price_retry_max_retries < 0 or price_retry_backoff_seconds < 0:
            raise ValueError("price_retry_bounds_invalid")
        self.storage = storage
        self.price_source = price_source
        self.execution_policy_guard = execution_policy_guard
        self.definition_open_price_source = definition_open_price_source
        self.price_retry_max_retries = price_retry_max_retries
        self.price_retry_backoff_seconds = price_retry_backoff_seconds
        self.sleep_func = sleep_func
        paper_costs = load_settings().paper_account
        self.commission_bps = (
            paper_costs.commission_bps if commission_bps is None else commission_bps
        )
        self.slippage_bps = (
            paper_costs.slippage_bps if slippage_bps is None else slippage_bps
        )

    def execute_plan(
        self,
        account: PaperAccount,
        *,
        sleeve: StrategySleeve,
        plan: StrategyExecutionPlan,
        allow_frozen_account: bool = False,
    ) -> StrategyExecutionPlan:
        """Prepare (lock-free, retried) then commit under the caller's locks.

        Signature, return value, exceptions, persistence order and retry budget
        are unchanged; the bounded price retries and their backoff sleep now run
        outside whatever account/sleeve mutation lock the caller holds.
        """
        try:
            prepared = self.prepare_with_retries(
                sleeve=sleeve,
                plan=plan,
                account_id=account.account_id,
            )
        except PaperStrategyExecutionError as exc:
            if plan.status == StrategyExecutionStatus.PENDING:
                self._block_plan(plan, exc.code)
            raise
        return self.commit_execution(
            account,
            sleeve=sleeve,
            plan=plan,
            prepared=prepared,
            allow_frozen_account=allow_frozen_account,
        )

    def prepare_execution(
        self,
        *,
        sleeve: StrategySleeve,
        plan: StrategyExecutionPlan,
        account_id: str | None = None,
    ) -> PreparedExecution:
        """Single, lock-free price-evidence attempt: network only, no writes.

        No local state is mutated and nothing is persisted. The result is bound
        to the plan's identity and re-verified inside ``commit_execution`` after
        the caller's lock has been re-acquired.

        Account-free structural guards run first, before any price fetch, so an
        ineligible plan terminates immediately with its own code (zero price
        calls, zero backoff sleeps) exactly as it did before the prepare/commit
        split.
        """
        self._validate_structural_context(sleeve=sleeve, plan=plan)
        definition_config = self._definition_config(sleeve, plan)
        if definition_config is not None:
            definition, targets, _signal_metadata = self._definition_binding(
                sleeve=sleeve,
                plan=plan,
                config=definition_config,
            )
            holdings: dict[str, float] = {}
            for lot in self.storage.load_sleeve_lots(sleeve.sleeve_id):
                symbol = lot.symbol.upper()
                holdings[symbol] = holdings.get(symbol, 0.0) + lot.quantity
            if set(holdings) - set(definition.symbols):
                raise PaperStrategyExecutionError(
                    "strategy_definition_position_outside_universe"
                )
            raw_quotes, prices = self._definition_quotes(
                holdings=holdings,
                targets=targets,
                plan=plan,
            )
            is_definition = True
            snapshot_steps: tuple[_ExecutionStep, ...] | None = None
        else:
            raw_quotes = self._load_quotes(plan)
            prices = {symbol: float(quote.price) for symbol, quote in raw_quotes.items()}
            is_definition = False
            snapshot_steps = tuple(self._build_steps(plan, raw_quotes))
        quotes = MappingProxyType(
            {symbol: quote.model_copy(deep=True) for symbol, quote in sorted(raw_quotes.items())}
        )
        frozen_prices = MappingProxyType(
            {symbol: float(price) for symbol, price in sorted(prices.items())}
        )
        prepare_digest = _prepared_digest(
            account_id=plan.account_id,
            sleeve_id=plan.sleeve_id,
            execution_id=plan.execution_id,
            target_date=plan.target_date,
            execution_window=plan.execution_window,
            signal_id=plan.signal_id,
            strategy_config_id=plan.strategy_config_id,
            strategy_config_version=plan.strategy_config_version,
            is_definition=is_definition,
            quotes=quotes,
            prices=frozen_prices,
        )
        return PreparedExecution(
            account_id=plan.account_id,
            sleeve_id=plan.sleeve_id,
            execution_id=plan.execution_id,
            target_date=plan.target_date,
            execution_window=plan.execution_window,
            signal_id=plan.signal_id,
            strategy_config_id=plan.strategy_config_id,
            strategy_config_version=plan.strategy_config_version,
            is_definition=is_definition,
            quotes=quotes,
            prices=frozen_prices,
            snapshot_steps=snapshot_steps,
            prepared_at=_utc_now_iso(),
            prepare_digest=prepare_digest,
        )

    def prepare_with_retries(
        self,
        *,
        sleeve: StrategySleeve,
        plan: StrategyExecutionPlan,
        account_id: str | None = None,
    ) -> PreparedExecution:
        """Bounded price-evidence retries; the backoff sleep runs lock-free."""
        price_retries = 0
        while True:
            try:
                return self.prepare_execution(
                    sleeve=sleeve,
                    plan=plan,
                    account_id=account_id,
                )
            except PaperStrategyExecutionError as exc:
                if (
                    exc.code in PRICE_EVIDENCE_RETRY_CODES
                    and price_retries < self.price_retry_max_retries
                ):
                    # Transient price outage inside the still-open target-date
                    # window: record the attempt, back off briefly, retry once
                    # more. Nothing has mutated yet, so re-running the
                    # price-evidence phase cannot duplicate fills.
                    price_retries += 1
                    self._record_price_retry(plan, attempt=price_retries, code=exc.code)
                    self.sleep_func(self.price_retry_backoff_seconds)
                    continue
                raise

    def commit_execution(
        self,
        account: PaperAccount,
        *,
        sleeve: StrategySleeve,
        plan: StrategyExecutionPlan,
        prepared: PreparedExecution,
        allow_frozen_account: bool = False,
    ) -> StrategyExecutionPlan:
        """Re-validate and commit under the caller's account+sleeve locks.

        The caller MUST hold both mutation locks. There is no network and no
        sleep here: the fresh (lock-protected) account, sleeve and plan are
        re-checked against the prepared price evidence, and every guard runs
        before the first persistent write.
        """
        try:
            self._verify_prepared_binding(plan, prepared)
            self._verify_prepared_digest(prepared)
            self._validate_execution_context(
                account,
                sleeve=sleeve,
                plan=plan,
                allow_frozen_account=allow_frozen_account,
            )
            if prepared.is_definition:
                execution_plan, steps = self._recompute_definition(
                    account,
                    sleeve=sleeve,
                    plan=plan,
                    prepared=prepared,
                )
            else:
                execution_plan = plan
                steps = self._build_steps(plan, prepared.quotes)
                if tuple(steps) != prepared.snapshot_steps:
                    raise PaperStrategyExecutionError("prepared_execution_steps_drift")
            if self.execution_policy_guard is not None:
                blocker = self.execution_policy_guard(
                    account,
                    sleeve,
                    execution_plan,
                    [
                        {
                            "symbol": step.symbol,
                            "notional_delta": (
                                step.gross_value
                                if step.side == OrderSide.BUY
                                else -step.gross_value
                            ),
                            "execution_price": step.price,
                        }
                        for step in steps
                    ],
                )
                if blocker is not None:
                    raise PaperStrategyExecutionError(blocker)
            self._preflight(account, sleeve=sleeve, steps=steps)
        except PaperStrategyExecutionError as exc:
            if plan.status == StrategyExecutionStatus.PENDING:
                self._block_plan(plan, exc.code)
            raise

        if prepared.is_definition and not steps:
            execution_plan.status = StrategyExecutionStatus.SKIPPED
            execution_plan.updated_at = _utc_now_iso()
            execution_plan.metadata["skip_reason"] = "no_rebalance_orders_at_open"
            self._copy_model_state(plan, execution_plan)
            self._replace_execution(plan)
            return plan

        lots = self.storage.load_sleeve_lots(sleeve.sleeve_id)
        account_after = account.model_copy(deep=True)
        sleeve_after = sleeve.model_copy(deep=True)
        plan_after = execution_plan.model_copy(deep=True)
        lot_book = SleeveLotBook([lot.model_copy(deep=True) for lot in lots])
        self._apply_steps(
            account_after,
            sleeve=sleeve_after,
            plan=plan_after,
            lot_book=lot_book,
            steps=steps,
        )
        after_lots = lot_book.lots()
        self.storage.save_execution_journal_pending(
            sleeve_id=sleeve.sleeve_id,
            execution_id=plan.execution_id,
            payload=self._execution_journal_payload(
                before_account=account,
                after_account=account_after,
                before_sleeve=sleeve,
                after_sleeve=sleeve_after,
                before_lots=lots,
                after_lots=after_lots,
                before_execution=plan,
                after_execution=plan_after,
            ),
        )
        self._copy_model_state(account, account_after)
        self._copy_model_state(sleeve, sleeve_after)
        self._copy_model_state(plan, plan_after)
        self.storage.save_sleeve(sleeve)
        self.storage.save_sleeve_lots(sleeve.sleeve_id, after_lots)
        self._replace_execution(plan)
        return plan

    def _verify_prepared_binding(
        self,
        plan: StrategyExecutionPlan,
        prepared: PreparedExecution,
    ) -> None:
        if (
            plan.execution_id != prepared.execution_id
            or plan.sleeve_id != prepared.sleeve_id
            or plan.account_id != prepared.account_id
            or plan.signal_id != prepared.signal_id
            or plan.target_date != prepared.target_date
            or plan.execution_window != prepared.execution_window
            or plan.strategy_config_id != prepared.strategy_config_id
            or plan.strategy_config_version != prepared.strategy_config_version
        ):
            raise PaperStrategyExecutionError("prepared_execution_rebind_mismatch")

    def _verify_prepared_digest(self, prepared: PreparedExecution) -> None:
        recomputed = _prepared_digest(
            account_id=prepared.account_id,
            sleeve_id=prepared.sleeve_id,
            execution_id=prepared.execution_id,
            target_date=prepared.target_date,
            execution_window=prepared.execution_window,
            signal_id=prepared.signal_id,
            strategy_config_id=prepared.strategy_config_id,
            strategy_config_version=prepared.strategy_config_version,
            is_definition=prepared.is_definition,
            quotes=prepared.quotes,
            prices=prepared.prices,
        )
        if recomputed != prepared.prepare_digest:
            raise PaperStrategyExecutionError("prepared_execution_integrity_violation")

    def _recompute_definition(
        self,
        account: PaperAccount,
        *,
        sleeve: StrategySleeve,
        plan: StrategyExecutionPlan,
        prepared: PreparedExecution,
    ) -> tuple[StrategyExecutionPlan, list[_ExecutionStep]]:
        """Re-read config/signals and re-derive orders from fresh holdings/cash.

        Only the (external) prepared prices are reused; every lock-protected
        input is read fresh so a fill decision can never rest on stale state.
        """
        config = self._definition_config(sleeve, plan)
        if config is None:
            raise PaperStrategyExecutionError(
                "strategy_definition_execution_binding_mismatch"
            )
        definition, targets, signal_metadata = self._definition_binding(
            sleeve=sleeve,
            plan=plan,
            config=config,
        )
        holdings: dict[str, float] = {}
        for lot in self.storage.load_sleeve_lots(sleeve.sleeve_id):
            symbol = lot.symbol.upper()
            holdings[symbol] = holdings.get(symbol, 0.0) + lot.quantity
        required = set(holdings) | set(targets)
        if required - set(prepared.prices):
            # New exposure (or a re-bound target) outside the prepared quote
            # set: fail closed with the existing transient-data code so the
            # plan still resolves through the ordinary expiry path.
            raise PaperStrategyExecutionError("strategy_definition_open_data_unavailable")
        prices = {symbol: float(prepared.prices[symbol]) for symbol in required}
        execution_plan = self._definition_orders(
            definition=definition,
            holdings=holdings,
            cash=sleeve.cash,
            targets=targets,
            prices=prices,
            quotes=prepared.quotes,
            signal_metadata=signal_metadata,
            plan=plan,
            account_id=account.account_id,
        )
        steps = (
            []
            if not execution_plan.orders
            else self._build_steps(execution_plan, prepared.quotes)
        )
        return execution_plan, steps

    def _definition_config(self, sleeve: StrategySleeve, plan: StrategyExecutionPlan):
        """Select by versioned config; mutable sleeve metadata cannot downgrade it."""
        try:
            config = self.storage.load_strategy_config(
                plan.strategy_config_id, version=plan.strategy_config_version,
            )
            if config.strategy_definition is None and not sleeve.metadata.get("definition_digest"):
                return None
            if (config.strategy_definition is None
                    or plan.strategy_config_id != sleeve.strategy_config_id
                    or plan.strategy_config_version != sleeve.strategy_config_version):
                raise ValueError("strategy_definition_execution_binding_mismatch")
            return config
        except FileNotFoundError as exc:
            if not sleeve.metadata.get("definition_digest"):
                return None
            raise PaperStrategyExecutionError(
                "strategy_definition_execution_binding_mismatch"
            ) from exc
        except (OSError, ValueError) as exc:
            raise PaperStrategyExecutionError(
                "strategy_definition_execution_binding_mismatch"
            ) from exc

    def _definition_binding(self, *, sleeve, plan, config):
        """Pure re-validation of the digest-bound signal/config binding.

        Read-only and lock-agnostic: no price fetch, no lots read. Re-run on
        every preparation attempt so a re-bound config/signal can never reuse a
        stale decision.
        """
        from quant_system.research.definition_paper import paper_definition
        from quant_system.research.strategy_runtime import next_session

        try:
            definition = paper_definition(config.strategy_definition)
            if (self.commission_bps != definition.commission_bps
                    or self.slippage_bps != definition.slippage_bps):
                raise ValueError("strategy_definition_execution_cost_mismatch")
            signals = [item for item in self.storage.load_signals(sleeve.sleeve_id)
                       if item.signal_id == plan.signal_id]
            if len(signals) != 1:
                raise ValueError("strategy_definition_signal_binding_mismatch")
            signal = signals[0]
            metadata = signal.metadata
            if (sleeve.metadata.get("definition_digest") != definition.content_digest
                    or metadata.get("definition_digest") != definition.content_digest
                    or plan.metadata.get("definition_digest") != definition.content_digest
                    or signal.strategy_config_id != config.strategy_config_id
                    or signal.strategy_config_version != config.version
                    or str(signal.status) != "generated"
                    or signal.execution_blocked_reason is not None
                    or metadata.get("signal_date") != signal.data_as_of
                    or metadata.get("ready") is not True
                    or metadata.get("rebalance_due") is not True
                    or metadata.get("targets") is None
                    or metadata.get("targets") != signal.target_weights
                    or metadata.get("trade_date") != plan.target_date):
                raise ValueError("strategy_definition_signal_binding_mismatch")
            if next_session(metadata["signal_date"]).date().isoformat() != plan.target_date:
                raise ValueError("strategy_definition_execution_session_mismatch")
            targets = metadata["targets"]
            if set(targets) - set(definition.symbols):
                raise ValueError("strategy_definition_target_universe_mismatch")
            return definition, targets, metadata
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise PaperStrategyExecutionError(str(exc)) from exc

    def _definition_quotes(self, *, holdings, targets, plan):
        """The only network step of the definition path: session-open quotes."""
        from quant_system.execution.definition_open_prices import DefinitionOpenPriceSource
        from quant_system.research.strategy_runtime import session_open

        symbols = sorted(set(holdings) | set(targets))
        source = self.definition_open_price_source or DefinitionOpenPriceSource()
        try:
            quotes = source.get_prices(symbols, target_date=plan.target_date)
            prices = {}
            for symbol in symbols:
                quote = quotes.get(symbol)
                if (quote is None or quote.source != "futu" or quote.price_kind != "futu_daily_open"
                        or quote.symbol != symbol
                        or pd.Timestamp(quote.as_of) != session_open(plan.target_date)
                        or not isfinite(quote.price) or quote.price <= 0):
                    raise PriceUnavailableError("strategy_definition_open_evidence_invalid")
                prices[symbol] = quote.price
            return quotes, prices
        except PriceUnavailableError as exc:
            raise PaperStrategyExecutionError(
                "strategy_definition_open_data_unavailable"
            ) from exc
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise PaperStrategyExecutionError(str(exc)) from exc

    def _definition_orders(
        self,
        *,
        definition,
        holdings,
        cash,
        targets,
        prices,
        quotes,
        signal_metadata,
        plan,
        account_id,
    ):
        """Pure order sizing from the definition and the prepared open prices."""
        from quant_system.research.definition_paper import definition_orders

        try:
            orders = definition_orders(
                definition=definition, holdings=holdings, cash=cash,
                targets=targets, prices=prices, account_id=account_id,
            )
            execution_plan = plan.model_copy(deep=True)
            execution_plan.orders = [
                StrategyExecutionOrder.from_proposed_order(item) for item in orders
            ]
            execution_plan.metadata = {
                **plan.metadata, "definition_digest": definition.content_digest,
                "decision_session": signal_metadata.get("signal_date"),
                "trade_date": plan.target_date, "target_weights": targets,
                "sizing_basis": "session_open_equity",
                "execution_quotes": {
                    symbol: quote.model_dump(mode="json") for symbol, quote in quotes.items()
                },
            }
            return execution_plan
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise PaperStrategyExecutionError(str(exc)) from exc

    def reconcile_execution_journals(
        self,
        account: PaperAccount,
        *,
        commit: bool = True,
    ) -> list[StrategyExecutionPlan]:
        recovered: list[StrategyExecutionPlan] = []
        for payload in self.storage.load_pending_execution_journals():
            sleeve_id = str(payload["sleeve_id"])
            execution_id = str(payload["execution_id"])
            before_account = PaperAccount.model_validate(payload["before_account"])
            after_account = PaperAccount.model_validate(payload["after_account"])
            after_sleeve = StrategySleeve.model_validate(payload["after_sleeve"])
            after_lots = [SleeveLot.model_validate(row) for row in payload.get("after_lots", [])]
            after_execution = StrategyExecutionPlan.model_validate(payload["after_execution"])
            can_finalize_state = True
            if self._account_has_execution(account, execution_id):
                pass
            elif self._accounts_match(account, before_account):
                self._copy_model_state(account, after_account)
            else:
                can_finalize_state = False
                after_execution.status = StrategyExecutionStatus.BLOCKED
                after_execution.blocked_reason = "recovery_required"
                after_execution.updated_at = _utc_now_iso()
            if can_finalize_state:
                self.storage.save_sleeve(after_sleeve)
                self.storage.save_sleeve_lots(sleeve_id, after_lots)
            self._replace_execution(after_execution)
            if commit:
                self.storage.commit_execution_journal(
                    sleeve_id=sleeve_id,
                    execution_id=execution_id,
                )
            recovered.append(after_execution)
        return recovered

    def commit_execution_journal(self, plan: StrategyExecutionPlan) -> None:
        self.storage.commit_execution_journal(
            sleeve_id=plan.sleeve_id,
            execution_id=plan.execution_id,
        )

    def block_plan(self, plan: StrategyExecutionPlan, *, reason: str) -> None:
        """Persist a deterministic pre-execution authority rejection."""
        if plan.status != StrategyExecutionStatus.PENDING or not reason:
            raise PaperStrategyExecutionError("execution_block_invalid")
        self._block_plan(plan, reason)

    def mark_missed_window(
        self,
        plan: StrategyExecutionPlan,
        *,
        processing_date: str,
    ) -> bool:
        """Expire a next_open plan whose target date is before the processing date.

        Only never-executed plans transition: PENDING plans (never attempted,
        for example after a powered-off observation night) and plans BLOCKED
        by a transient price-evidence failure. The prior status and blocked
        reason stay on the record via ``blocked_reason`` and
        ``metadata["missed_window"]``; the plan is never filled late and never
        fabricated. Anything else (filled, skipped, cancelled, non-price
        blocks, unreadable or non-next_open targets) is left untouched so an
        unrecognized record fails closed. Returns True when it transitioned.
        """
        if plan.execution_window != "next_open" or plan.target_date is None:
            return False
        try:
            target = date.fromisoformat(plan.target_date)
            due = date.fromisoformat(processing_date)
        except (TypeError, ValueError):
            return False
        if target >= due:
            return False
        if plan.status == StrategyExecutionStatus.PENDING:
            previous_reason = None
        elif (
            plan.status == StrategyExecutionStatus.BLOCKED
            and plan.blocked_reason in PRICE_EVIDENCE_RETRY_CODES
        ):
            previous_reason = plan.blocked_reason
        else:
            return False
        marked_at = _utc_now_iso()
        plan.metadata["missed_window"] = {
            "previous_status": plan.status.value,
            "previous_blocked_reason": previous_reason,
            "target_date": plan.target_date,
            "processing_date": due.isoformat(),
            "marked_at": marked_at,
        }
        plan.status = StrategyExecutionStatus.MISSED_WINDOW
        plan.updated_at = marked_at
        self._replace_execution(plan)
        return True

    def _record_price_retry(
        self,
        plan: StrategyExecutionPlan,
        *,
        attempt: int,
        code: str,
    ) -> None:
        record = plan.metadata.setdefault(
            "price_unavailable_retry",
            {
                "attempts": [],
                "max_retries": self.price_retry_max_retries,
                "backoff_seconds": self.price_retry_backoff_seconds,
            },
        )
        record["attempts"] = [
            *(record.get("attempts") or []),
            {"attempt": attempt, "code": code, "at": _utc_now_iso()},
        ]

    def pending_plans(
        self,
        *,
        sleeve_id: str | None = None,
        execution_window: str = "next_open",
        target_date: str | None = None,
        limit: int = 50,
    ) -> list[tuple[StrategySleeve, StrategyExecutionPlan]]:
        due_target_date = target_date or date.today().isoformat()
        sleeves = (
            [self.storage.load_sleeve(sleeve_id)]
            if sleeve_id is not None
            else self.storage.list_sleeves()
        )
        plans: list[tuple[StrategySleeve, StrategyExecutionPlan]] = []
        for sleeve in sleeves:
            for plan in self.storage.load_executions(sleeve.sleeve_id):
                if plan.status != StrategyExecutionStatus.PENDING:
                    continue
                if plan.execution_window != execution_window:
                    continue
                if plan.target_date != due_target_date:
                    continue
                plans.append((sleeve, plan))
                if len(plans) >= limit:
                    return plans
        return plans

    def _apply_steps(
        self,
        account: PaperAccount,
        *,
        sleeve: StrategySleeve,
        plan: StrategyExecutionPlan,
        lot_book: SleeveLotBook,
        steps: list[_ExecutionStep],
    ) -> None:
        fills: list[StrategyExecutionFill] = []
        source = f"strategy:{sleeve.sleeve_id}"
        for step in self._ordered_steps(steps):
            account_fill = self._account_fill(plan, step)
            if step.side == OrderSide.SELL:
                before_sources = self._position_sources(account, step.symbol)
                lot_book.sell(
                    sleeve_id=sleeve.sleeve_id,
                    symbol=step.symbol,
                    quantity=step.quantity,
                )
                account.apply_fill(
                    account_fill,
                    source=source,
                    price_kind=step.quote.price_kind,
                    kind="sleeve_execution_fill",
                )
                self._set_sleeve_source_after_sell(
                    account,
                    symbol=step.symbol,
                    source=source,
                    before_sources=before_sources,
                    quantity=step.quantity,
                )
                sleeve.cash += step.quantity * step.fill_price - step.commission
            else:
                account.apply_fill(
                    account_fill,
                    source=source,
                    price_kind=step.quote.price_kind,
                    kind="sleeve_execution_fill",
                )
                lot_book.buy(
                    account_id=account.account_id,
                    sleeve_id=sleeve.sleeve_id,
                    symbol=step.symbol,
                    quantity=step.quantity,
                    price=step.price,
                    source=source,
                )
                sleeve.cash -= step.quantity * step.fill_price + step.commission
            fills.append(
                StrategyExecutionFill.create(
                    symbol=step.symbol,
                    side=str(step.side),
                    quantity=step.quantity,
                    price=step.fill_price,
                    price_kind=step.quote.price_kind,
                    gross_value=step.quantity * step.fill_price,
                    metadata={
                        "commission": step.commission,
                        "commission_bps": self.commission_bps,
                        "slippage_bps": self.slippage_bps,
                    },
                )
            )
        sleeve.cash = max(sleeve.cash, 0.0)
        account.sleeve_cash[sleeve.sleeve_id] = sleeve.cash
        sleeve.updated_at = _utc_now_iso()
        plan.fills = fills
        plan.status = StrategyExecutionStatus.FILLED
        plan.updated_at = _utc_now_iso()

    @staticmethod
    def _execution_journal_payload(
        *,
        before_account: PaperAccount,
        after_account: PaperAccount,
        before_sleeve: StrategySleeve,
        after_sleeve: StrategySleeve,
        before_lots: list[SleeveLot],
        after_lots: list[SleeveLot],
        before_execution: StrategyExecutionPlan,
        after_execution: StrategyExecutionPlan,
    ) -> dict[str, Any]:
        return {
            "journal_version": 1,
            "created_at": _utc_now_iso(),
            "account_id": before_account.account_id,
            "sleeve_id": before_sleeve.sleeve_id,
            "execution_id": before_execution.execution_id,
            "before_account": before_account.model_dump(mode="json"),
            "after_account": after_account.model_dump(mode="json"),
            "before_sleeve": before_sleeve.model_dump(mode="json"),
            "after_sleeve": after_sleeve.model_dump(mode="json"),
            "before_lots": [lot.model_dump(mode="json") for lot in before_lots],
            "after_lots": [lot.model_dump(mode="json") for lot in after_lots],
            "before_execution": before_execution.model_dump(mode="json"),
            "after_execution": after_execution.model_dump(mode="json"),
        }

    @staticmethod
    def _copy_model_state(target, source) -> None:
        for field_name in type(source).model_fields:
            setattr(target, field_name, getattr(source, field_name))

    @staticmethod
    def _accounts_match(left: PaperAccount, right: PaperAccount) -> bool:
        return left.model_dump(mode="json") == right.model_dump(mode="json")

    @staticmethod
    def _account_has_execution(account: PaperAccount, execution_id: str) -> bool:
        return any(
            entry.kind == "sleeve_execution_fill" and entry.note == execution_id
            for entry in account.ledger
        )

    @staticmethod
    def _validate_structural_context(
        *,
        sleeve: StrategySleeve,
        plan: StrategyExecutionPlan,
    ) -> None:
        """Account-free structural guards, run before any price fetch.

        These are exactly the ``_validate_execution_context`` checks that do not
        read the account (plan status/window/orders, sleeve mode/status, plan
        vs sleeve id), evaluated on the lock-free prepare side. None of these
        codes is in ``PRICE_EVIDENCE_RETRY_CODES``, so a hit is a terminal block
        that must not be masked by a transient price outage: without this the
        plan would burn the full price-retry budget (3 calls + up to 2x30s
        backoff), record the price code instead of its own structural reason,
        and -- because the price code is retryable -- silently roll forward to
        MISSED_WINDOW the next day rather than staying BLOCKED.

        The account-dependent checks (``account_frozen``,
        ``account_sleeve_mismatch``) deliberately stay in
        ``_validate_execution_context`` inside ``commit_execution``: the
        account is only authoritative once loaded under the lock, and deciding
        them on a stale lock-free read could emit a code that contradicts the
        authoritative state. ``_validate_execution_context`` is kept verbatim
        (same checks, same order) so the commit-side codes are unchanged.
        """
        if plan.status != StrategyExecutionStatus.PENDING:
            raise PaperStrategyExecutionError("execution_not_pending")
        if plan.execution_window != "next_open":
            raise PaperStrategyExecutionError("unsupported_execution_window")
        if sleeve.mode != StrategySleeveMode.ALLOCATED:
            raise PaperStrategyExecutionError("signal_only_no_execution")
        if sleeve.status == StrategySleeveStatus.PAUSED:
            raise PaperStrategyExecutionError("sleeve_paused")
        if sleeve.status == StrategySleeveStatus.STOPPED:
            raise PaperStrategyExecutionError("sleeve_stopped")
        if plan.sleeve_id != sleeve.sleeve_id:
            raise PaperStrategyExecutionError("execution_sleeve_mismatch")
        if not plan.orders and not (
            plan.metadata.get("rebalance_required") is True
            and plan.metadata.get("definition_digest")
        ):
            raise PaperStrategyExecutionError("no_executable_orders")

    def _validate_execution_context(
        self,
        account: PaperAccount,
        *,
        sleeve: StrategySleeve,
        plan: StrategyExecutionPlan,
        allow_frozen_account: bool = False,
    ) -> None:
        if plan.status != StrategyExecutionStatus.PENDING:
            raise PaperStrategyExecutionError("execution_not_pending")
        if plan.execution_window != "next_open":
            raise PaperStrategyExecutionError("unsupported_execution_window")
        if sleeve.mode != StrategySleeveMode.ALLOCATED:
            raise PaperStrategyExecutionError("signal_only_no_execution")
        if sleeve.status == StrategySleeveStatus.PAUSED:
            raise PaperStrategyExecutionError("sleeve_paused")
        if sleeve.status == StrategySleeveStatus.STOPPED:
            raise PaperStrategyExecutionError("sleeve_stopped")
        if account.kill_switch and not allow_frozen_account:
            raise PaperStrategyExecutionError("account_frozen")
        if sleeve.account_id != account.account_id or plan.account_id != account.account_id:
            raise PaperStrategyExecutionError("account_sleeve_mismatch")
        if plan.sleeve_id != sleeve.sleeve_id:
            raise PaperStrategyExecutionError("execution_sleeve_mismatch")
        if not plan.orders and not (
            plan.metadata.get("rebalance_required") is True
            and plan.metadata.get("definition_digest")
        ):
            raise PaperStrategyExecutionError("no_executable_orders")

    def _load_quotes(self, plan: StrategyExecutionPlan) -> dict[str, PricedQuote]:
        symbols = sorted({order.symbol.upper() for order in plan.orders})
        try:
            quotes = self.price_source.get_prices(symbols)
        except PriceUnavailableError as exc:
            raise PaperStrategyExecutionError("price_unavailable") from exc
        missing = [symbol for symbol in symbols if symbol not in quotes]
        if missing:
            raise PaperStrategyExecutionError("price_unavailable")
        for symbol, quote in quotes.items():
            price = float(quote.price)
            if not isfinite(price) or price <= 0:
                raise PaperStrategyExecutionError("price_unavailable")
            quotes[symbol] = quote.model_copy(update={"symbol": symbol.upper(), "price": price})
        return quotes

    def _build_steps(
        self,
        plan: StrategyExecutionPlan,
        quotes: dict[str, PricedQuote],
    ) -> list[_ExecutionStep]:
        steps = []
        for order in plan.orders:
            symbol = order.symbol.upper()
            try:
                side = OrderSide(order.side)
            except ValueError as exc:
                raise PaperStrategyExecutionError("invalid_order_side") from exc
            quote = quotes[symbol]
            quantity = self._execution_quantity(order, side=side, price=quote.price)
            if not isfinite(quantity):
                raise PaperStrategyExecutionError("invalid_order_quantity")
            if quantity <= EPSILON:
                continue
            gross_value = quantity * quote.price
            if not isfinite(gross_value):
                raise PaperStrategyExecutionError("invalid_order_value")
            slip = self.slippage_bps / 10_000
            fill_price = quote.price * (1 + slip if side == OrderSide.BUY else 1 - slip)
            fill_gross = quantity * fill_price
            commission = fill_gross * self.commission_bps / 10_000
            steps.append(
                _ExecutionStep(
                    order=order,
                    side=side,
                    symbol=symbol,
                    quantity=quantity,
                    price=quote.price,
                    gross_value=gross_value,
                    quote=quote,
                    fill_price=fill_price,
                    commission=commission,
                )
            )
        if not steps:
            raise PaperStrategyExecutionError("no_executable_orders")
        return steps

    @staticmethod
    def _execution_quantity(
        order: StrategyExecutionOrder,
        *,
        side: OrderSide,
        price: float,
    ) -> float:
        if side == OrderSide.SELL and order.estimated_quantity is not None:
            return abs(order.estimated_quantity)
        if order.notional_delta is not None:
            return abs(order.notional_delta) / price
        if order.estimated_quantity is not None:
            return abs(order.estimated_quantity)
        return 0.0

    def _preflight(
        self,
        account: PaperAccount,
        *,
        sleeve: StrategySleeve,
        steps: list[_ExecutionStep],
    ) -> None:
        lots = self.storage.load_sleeve_lots(sleeve.sleeve_id)
        lot_book = SleeveLotBook([lot.model_copy(deep=True) for lot in lots])
        sleeve_cash = sleeve.cash
        source = f"strategy:{sleeve.sleeve_id}"
        for step in self._ordered_steps(steps):
            if step.side == OrderSide.SELL:
                if self._account_source_quantity(account, step.symbol, source) < (
                    step.quantity - EPSILON
                ):
                    raise PaperStrategyExecutionError("insufficient_account_source_quantity")
                try:
                    lot_book.sell(
                        sleeve_id=sleeve.sleeve_id,
                        symbol=step.symbol,
                        quantity=step.quantity,
                    )
                except ValueError as exc:
                    raise PaperStrategyExecutionError("insufficient_sleeve_lot_quantity") from exc
                sleeve_cash += step.gross_value
            elif step.gross_value > sleeve_cash + EPSILON:
                raise PaperStrategyExecutionError("insufficient_sleeve_cash")
            else:
                sleeve_cash -= step.gross_value

    @staticmethod
    def _ordered_steps(steps: list[_ExecutionStep]) -> list[_ExecutionStep]:
        return sorted(steps, key=lambda step: 0 if step.side == OrderSide.SELL else 1)

    @staticmethod
    def _account_fill(plan: StrategyExecutionPlan, step: _ExecutionStep) -> ExecutionFill:
        return ExecutionFill(
            fill_id=f"fill-{plan.execution_id}-{step.symbol}-{step.side}",
            order_id=plan.execution_id,
            timestamp=pd.Timestamp(step.quote.as_of),
            symbol=step.symbol,
            side=step.side,
            quantity=step.quantity,
            fill_price=step.fill_price,
            gross_value=step.quantity * step.fill_price,
            commission=step.commission,
        )

    @staticmethod
    def _position_sources(account: PaperAccount, symbol: str) -> dict[str, float]:
        position = account.positions.get(symbol.upper())
        if position is None:
            return {}
        return dict(position.source_quantity)

    @staticmethod
    def _account_source_quantity(
        account: PaperAccount,
        symbol: str,
        source: str,
    ) -> float:
        position = account.positions.get(symbol.upper())
        if position is None:
            return 0.0
        return position.source_quantity.get(source, 0.0)

    @staticmethod
    def _set_sleeve_source_after_sell(
        account: PaperAccount,
        *,
        symbol: str,
        source: str,
        before_sources: dict[str, float],
        quantity: float,
    ) -> None:
        position = account.positions.get(symbol.upper())
        if position is None:
            return
        updated = dict(before_sources)
        updated[source] = updated.get(source, 0.0) - quantity
        position.source_quantity = {
            item_source: item_quantity
            for item_source, item_quantity in updated.items()
            if item_quantity > EPSILON
        }

    def _block_plan(self, plan: StrategyExecutionPlan, reason: str) -> None:
        plan.status = StrategyExecutionStatus.BLOCKED
        plan.blocked_reason = reason
        plan.updated_at = _utc_now_iso()
        self._replace_execution(plan)

    def _replace_execution(self, plan: StrategyExecutionPlan) -> None:
        executions = self.storage.load_executions(plan.sleeve_id)
        replaced = False
        for index, existing in enumerate(executions):
            if existing.execution_id == plan.execution_id:
                executions[index] = plan
                replaced = True
                break
        if not replaced:
            executions.append(plan)
        self.storage.save_executions(plan.sleeve_id, executions)
