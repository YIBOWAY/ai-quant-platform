from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Literal

import pandas as pd
from pydantic import BaseModel, Field

REQUIRED_FACTOR_INPUT_COLUMNS: tuple[str, ...] = (
    "symbol",
    "timestamp",
    "close",
    "volume",
)

FACTOR_RESULT_COLUMNS: tuple[str, ...] = (
    "symbol",
    "signal_ts",
    "tradeable_ts",
    "factor_id",
    "factor_version",
    "factor_name",
    "lookback",
    "value",
)


class FactorMetadata(BaseModel):
    factor_id: str
    factor_name: str
    factor_version: str
    lookback: int = Field(gt=0)
    direction: Literal["higher_is_better", "lower_is_better", "neutral"]
    description: str


class BaseFactor(ABC):
    """Base class for point-in-time factors.

    The factor value at ``signal_ts`` may use the bar ending at that timestamp.
    It becomes actionable only at ``tradeable_ts``, which is the next available
    timestamp for the same symbol. This keeps research signals separate from
    future execution assumptions.
    """

    factor_id: ClassVar[str]
    factor_name: ClassVar[str]
    factor_version: ClassVar[str] = "0.1.0"
    default_lookback: ClassVar[int]
    direction: ClassVar[Literal["higher_is_better", "lower_is_better", "neutral"]]
    description: ClassVar[str]

    def __init__(self, *, lookback: int | None = None) -> None:
        selected_lookback = self.default_lookback if lookback is None else lookback
        if selected_lookback <= 0:
            raise ValueError("lookback must be greater than zero")
        self.lookback = selected_lookback

    @property
    def metadata(self) -> FactorMetadata:
        return FactorMetadata(
            factor_id=self.factor_id,
            factor_name=self.factor_name,
            factor_version=self.factor_version,
            lookback=self.lookback,
            direction=self.direction,
            description=self.description,
        )

    def compute(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        frame = self._prepare_input(ohlcv)
        values = self._compute_values(frame)
        if not values.index.equals(frame.index):
            raise ValueError("factor value index must align to the input frame")

        result = pd.DataFrame(
            {
                "symbol": frame["symbol"],
                "signal_ts": frame["timestamp"],
                "tradeable_ts": frame.groupby("symbol", sort=False)["timestamp"].shift(-1),
                "factor_id": self.factor_id,
                "factor_version": self.factor_version,
                "factor_name": self.factor_name,
                "lookback": self.lookback,
                "value": values,
            }
        )
        result = result.dropna(subset=["value", "tradeable_ts"]).reset_index(drop=True)
        return result.loc[:, list(FACTOR_RESULT_COLUMNS)]

    def _prepare_input(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        missing = [
            column for column in REQUIRED_FACTOR_INPUT_COLUMNS if column not in ohlcv.columns
        ]
        if missing:
            raise ValueError(f"missing required factor input columns: {', '.join(missing)}")

        frame = ohlcv.copy()
        frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
        return frame.sort_values(["symbol", "timestamp"], ignore_index=True)

    @abstractmethod
    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:
        """Return a value series aligned with ``frame``."""
