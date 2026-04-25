from __future__ import annotations

import pandas as pd

from quant_system.backtest.models import TargetWeight


class ScoreSignalStrategy:
    """Converts a Phase 2 score table into target weights.

    This class intentionally does not know about prices, cash, orders, or broker
    state. It only states desired portfolio weights for a timestamp.
    """

    def __init__(
        self,
        signal_frame: pd.DataFrame,
        *,
        top_n: int = 3,
        target_gross_exposure: float = 1.0,
        long_only: bool = True,
    ) -> None:
        if top_n <= 0:
            raise ValueError("top_n must be greater than zero")
        if target_gross_exposure < 0:
            raise ValueError("target_gross_exposure must be non-negative")
        self.top_n = top_n
        self.target_gross_exposure = target_gross_exposure
        self.long_only = long_only
        self.signal_frame = self._prepare_signals(signal_frame)

    def target_weights(self, timestamp: pd.Timestamp) -> list[TargetWeight] | None:
        ts = pd.Timestamp(timestamp)
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")

        rows = self.signal_frame[self.signal_frame["tradeable_ts"] == ts].copy()
        if rows.empty:
            return None
        if self.long_only:
            rows = rows[rows["score"] > 0]
        if rows.empty:
            return []

        selected = rows.sort_values(["score", "symbol"], ascending=[False, True]).head(
            self.top_n
        )
        weight = self.target_gross_exposure / len(selected)
        return [
            TargetWeight(
                timestamp=ts,
                symbol=row.symbol,
                target_weight=weight,
                reason=f"score={row.score:.6f}",
            )
            for row in selected.itertuples(index=False)
        ]

    def _prepare_signals(self, signal_frame: pd.DataFrame) -> pd.DataFrame:
        required = {"symbol", "tradeable_ts", "score"}
        missing = required.difference(signal_frame.columns)
        if missing:
            raise ValueError(f"missing required signal columns: {', '.join(sorted(missing))}")

        frame = signal_frame.copy()
        frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
        frame["tradeable_ts"] = pd.to_datetime(frame["tradeable_ts"], utc=True)
        frame["score"] = pd.to_numeric(frame["score"], errors="coerce")
        return frame.dropna(subset=["score"]).sort_values(
            ["tradeable_ts", "symbol"],
            ignore_index=True,
        )
