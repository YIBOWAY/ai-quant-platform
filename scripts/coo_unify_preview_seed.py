"""Seed one hung paper sleeve fill for the isolated coo-unify preview.

Writes only under QS_DATA_DIR. Does not touch live api_runs or quantplatform.

The fill uses a fake 179 print (price_kind=preview_seed) on 2024-03-21.
Later Futu mark-to-market is not strategy P&L and is not daily observation.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC
from pathlib import Path

import pandas as pd

from quant_system.config.settings import reload_settings
from quant_system.execution.assistant_remote import record_verified_candidate
from quant_system.execution.account import PaperAccount
from quant_system.execution.account_storage import PaperAccountStorage
from quant_system.execution.paper_strategy_operations import PaperStrategyOperationsRunner
from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage
from quant_system.execution.paper_strategy_sleeves import (
    PaperStrategySleeveService,
    StrategyConfig,
    StrategySleeveMode,
)
from quant_system.execution.price_source import PricedQuote


class _FakeOHLCVProvider:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def fetch_ohlcv(self, symbols, *, start, end, interval="1d"):
        wanted = {symbol.upper() for symbol in symbols}
        return self.frame[self.frame["symbol"].isin(wanted)].copy()


class _FakePriceSource:
    def __init__(self, prices: dict[str, float]) -> None:
        self.prices = {symbol.upper(): price for symbol, price in prices.items()}

    def get_prices(self, symbols: list[str], **_kwargs) -> dict[str, PricedQuote]:
        return {
            symbol.upper(): PricedQuote(
                symbol=symbol.upper(),
                price=self.prices[symbol.upper()],
                price_kind="preview_seed",
                as_of="2026-08-13T13:30:00Z",
                source="coo_unify_preview",
            )
            for symbol in symbols
            if symbol.upper() in self.prices
        }


def _ohlcv_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = pd.date_range("2024-01-01", periods=80, freq="D", tz=UTC)
    for index, timestamp in enumerate(dates):
        rows.append(
            {
                "symbol": "AAPL",
                "timestamp": timestamp,
                "open": 100.0 + index,
                "high": 101.0 + index,
                "low": 99.0 + index,
                "close": 100.0 + index,
                "volume": 1_000_000 + index,
            }
        )
        rows.append(
            {
                "symbol": "MSFT",
                "timestamp": timestamp,
                "open": 200.0 - (index * 0.25),
                "high": 201.0 - (index * 0.25),
                "low": 199.0 - (index * 0.25),
                "close": 200.0 - (index * 0.25),
                "volume": 900_000 + index,
            }
        )
    return pd.DataFrame(rows)


def seed(data_dir: Path) -> dict[str, object]:
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["QS_DATA_DIR"] = str(data_dir)
    settings = reload_settings()
    api_runs_dir = data_dir / "api_runs"
    api_runs_dir.mkdir(parents=True, exist_ok=True)
    account_storage = PaperAccountStorage(api_runs_dir)
    sleeve_storage = PaperStrategySleeveStorage(api_runs_dir)
    fixture_source = (
        b"from __future__ import annotations\n"
        b"import pandas as pd\n"
        b"from quant_system.factors.base import BaseFactor\n\n"
        b"class GeneratedFactor(BaseFactor):\n"
        b'    factor_id = "d34_oracle"\n'
        b'    factor_name = "D34 Oracle"\n'
        b"    default_lookback = 2\n"
        b'    direction = "higher_is_better"\n'
        b'    description = "Isolation digest-bound fixture."\n\n'
        b"    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:\n"
        b'        return frame.groupby("symbol", sort=False)["close"].pct_change(\n'
        b"            self.lookback, fill_method=None\n"
        b"        )\n\n"
        b"D34_FACTOR = GeneratedFactor\n"
    )
    fixture_path = data_dir / "assistant_remote" / "fixture_d34_oracle.py"
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_bytes(fixture_source)
    record_verified_candidate(
        settings,
        candidate_id="candidate-preview-digest",
        objective="隔离预览：digest 已绑定、尚未挂上。这不是每天观察。",
        source="preview_seed",
        source_digest=hashlib.sha256(fixture_source).hexdigest(),
        source_path=str(fixture_path),
        factor_id="d34_oracle",
        universe=["SPY", "QQQ"],
    )
    if account_storage.load() is not None and sleeve_storage.list_sleeves():
        account = account_storage.load()
        sleeves = sleeve_storage.list_sleeves()
        return {
            "seeded": False,
            "reason": "preview_already_seeded",
            "account_id": account.account_id if account else None,
            "sleeve_ids": [sleeve.sleeve_id for sleeve in sleeves],
            "verified_candidate_id": "candidate-preview-digest",
        }

    provider = _FakeOHLCVProvider(_ohlcv_frame())
    from quant_system.execution import paper_strategy_signal_service as signal_mod

    signal_mod.build_ohlcv_provider = lambda settings, *, requested=None: (provider, "futu")
    account = PaperAccount.open_new(initial_cash=1_000_000)
    account.kill_switch = True
    config = StrategyConfig.create(
        name="试运行观察演示",
        description="isolation preview hung sleeve",
        strategy_id="cross_sectional_top_n",
        universe_id="custom",
        symbols=["AAPL", "MSFT"],
        factor_ids=["momentum"],
        weights={"momentum": 1.0},
        lookback=5,
        top_n=1,
        rebalance_frequency="daily",
        max_weight_per_symbol=0.99,
        min_order_value=100.0,
        data_provider="futu",
        execution_timing="next_open",
        metadata={"source": "coo_unify_preview"},
    )
    sleeve_storage.save_strategy_config(config)
    sleeve = PaperStrategySleeveService(sleeve_storage).create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=10_000,
        metadata={
            "automation_managed": True,
            "automation_source": "d34",
            "artifact_id": "preview-artifact-hung",
            "mandate_id": "preview-mandate-expired",
            "promotion_scope": "paper_only",
            "workspace_id": "default",
            "preview_label": "hung_observation_demo",
        },
    )
    sleeve_storage.save_sleeve(sleeve)
    account_storage.save(account)
    runner = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        price_source=_FakePriceSource({"AAPL": 179.0}),
        paper_execution_context_provider=lambda _sleeve: {
            "paper_execution_enabled": False,
            "emergency_stop": False,
            "mandate_active": False,
            "mandate_paper_execution_allowed": False,
        },
    )
    signal = runner.generate_signal_once(
        sleeve.sleeve_id,
        signal_date="2024-03-20",
        history_days=90,
    )
    runner.create_execution_once(
        sleeve.sleeve_id,
        signal.signal_id,
        target_date="2024-03-21",
    )
    result = runner.process_pending_executions_once(
        sleeve_id=sleeve.sleeve_id,
        target_date="2024-03-21",
    )
    if result.filled_count != 1 or result.account is None:
        raise RuntimeError(
            f"preview seed did not fill: filled={result.filled_count} "
            f"blocked={result.blocked_count}"
        )
    position = result.account.positions["AAPL"]
    return {
        "seeded": True,
        "account_id": result.account.account_id,
        "kill_switch": result.account.kill_switch,
        "sleeve_id": sleeve.sleeve_id,
        "filled_count": result.filled_count,
        "aapl_quantity": position.quantity,
        "aapl_avg_cost": position.avg_cost,
        "cash": result.account.cash,
    }


if __name__ == "__main__":
    import json
    import sys

    target = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ["QS_DATA_DIR"])
    print(json.dumps(seed(target), indent=2, sort_keys=True))
