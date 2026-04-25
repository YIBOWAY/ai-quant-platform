import pandas as pd

from quant_system.experiments.models import WalkForwardConfig
from quant_system.experiments.walk_forward import build_walk_forward_splits


def test_walk_forward_splits_have_explicit_train_and_validation_boundaries() -> None:
    timestamps = pd.date_range("2024-01-02", periods=12, freq="B", tz="UTC")
    config = WalkForwardConfig(
        enabled=True,
        train_bars=5,
        validation_bars=3,
        step_bars=3,
    )

    splits = build_walk_forward_splits(timestamps, config)

    assert len(splits) == 2
    first = splits[0]
    assert first.fold_id == "fold-001"
    assert first.train_start == timestamps[0]
    assert first.train_end == timestamps[4]
    assert first.validation_start == timestamps[5]
    assert first.validation_end == timestamps[7]
    assert first.train_end < first.validation_start
    assert first.validation_start <= first.validation_end
