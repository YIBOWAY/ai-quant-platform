from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from quant_system.experiments.models import WalkForwardConfig, WalkForwardSplit


def build_walk_forward_splits(
    timestamps: Iterable[pd.Timestamp],
    config: WalkForwardConfig,
) -> list[WalkForwardSplit]:
    if not config.enabled:
        return []

    values = pd.Series(pd.to_datetime(list(timestamps), utc=True)).drop_duplicates()
    values = values.sort_values(ignore_index=True)
    splits: list[WalkForwardSplit] = []
    start_index = 0
    fold_index = 1
    window_size = config.train_bars + config.validation_bars
    while start_index + window_size <= len(values):
        train_start = values.iloc[start_index]
        train_end = values.iloc[start_index + config.train_bars - 1]
        validation_start = values.iloc[start_index + config.train_bars]
        validation_end = values.iloc[start_index + window_size - 1]
        splits.append(
            WalkForwardSplit(
                fold_id=f"fold-{fold_index:03d}",
                train_start=train_start,
                train_end=train_end,
                validation_start=validation_start,
                validation_end=validation_end,
            )
        )
        fold_index += 1
        start_index += config.step_bars
    return splits
