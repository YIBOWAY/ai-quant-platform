"""Sealed synthetic tests only; no test observations enter the real catalog."""

from __future__ import annotations

import importlib.util
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from quant_system.research import qlib_evaluation as evaluation


def fixture_data(days=900):
    calendar = pd.bdate_range("2020-01-01", periods=days)
    rng = np.random.default_rng(48)
    records = []
    for symbol in ("AAA", "BBB", "CCC", "QQQ"):
        values = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, days)))
        for day, price in zip(calendar, values, strict=True):
            records.append(
                {
                    "timestamp": day,
                    "symbol": symbol,
                    "open": price,
                    "close": price,
                    "high": price * 1.01,
                    "low": price * 0.99,
                    "volume": 100_000,
                    "interval": "1d",
                    "provider": "futu",
                    "price_adjustment": "qfq",
                }
            )
    prices = pd.DataFrame(records)
    index = pd.MultiIndex.from_product(
        [calendar, ["AAA", "BBB", "CCC", "QQQ"]], names=["datetime", "instrument"]
    )
    features = pd.DataFrame(
        rng.normal(size=(len(index), 4)),
        index=index,
        columns=["momentum", "volatility", "liquidity", "candidate"],
    )
    return prices, features


def portfolio_stub(prices, prediction, calendar):
    return {
        "metrics": {"sharpe": float(prediction.mean()), "max_drawdown": 0.1},
        "benchmark_metrics": {},
        "curve": [],
        "source": "sealed_test_only",
    }


def test_label_aligned_portfolio_ends_at_last_open_not_last_close():
    prices, features = fixture_data(days=4)
    calendar = pd.DatetimeIndex(sorted(prices.timestamp.unique()))
    prediction = features.loc[pd.IndexSlice[calendar[:2], :], "momentum"]
    original = evaluation._portfolio(prices, prediction, calendar)
    altered = prices.copy()
    altered.loc[altered.timestamp == calendar[-1], "close"] *= 1.5
    changed = evaluation._portfolio(altered, prediction, calendar)
    assert original["metrics"] == changed["metrics"]
    assert original["benchmark_metrics"] == changed["benchmark_metrics"]
    assert original["curve"] == changed["curve"]
    assert original["costs"] == changed["costs"]


@unittest.skipUnless(
    importlib.util.find_spec("qlib") and importlib.util.find_spec("sklearn"),
    "requires the Qlib evaluation image",
)
class QlibEvaluationTests(unittest.TestCase):
    def evaluate(self, prices, features, **kwargs):
        with patch.object(evaluation, "_portfolio", side_effect=portfolio_stub):
            return evaluation.evaluate_qlib_study(prices, features, **kwargs)

    def test_real_qlib_folds_labels_and_paired_samples(self):
        prices, features = fixture_data()
        # Missing candidate rows must also disappear from its baseline model.
        features.loc[features.index[::17], "candidate"] = np.nan
        result = self.evaluate(prices, features, candidate_ids=["candidate", "momentum"])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["methodology"]["model"], "ridge")
        self.assertEqual(len(result["folds"]), 3)
        dates = pd.DatetimeIndex(sorted(prices.timestamp.unique()))
        for fold in result["folds"]:
            train, valid, test = [fold["segments"][key] for key in ("train", "valid", "test")]
            self.assertEqual(train["n_dates"], 504)
            self.assertEqual(valid["n_dates"], 126)
            self.assertLess(
                dates.get_loc(pd.Timestamp(train["end"])) + 2,
                dates.get_loc(pd.Timestamp(valid["start"])),
            )
            self.assertLess(
                dates.get_loc(pd.Timestamp(valid["end"])) + 2,
                dates.get_loc(pd.Timestamp(test["start"])),
            )
            self.assertLessEqual(pd.Timestamp(test["end"]), dates[-3])
        rows = pd.DataFrame(result["predictions"])
        paired = rows[(rows.comparison_id == "candidate") & (rows.partition == "test")]
        self.assertTrue(paired[["baseline", "augmented", "label"]].notna().all().all())
        self.assertFalse(paired.duplicated(["datetime", "instrument"]).any())
        one = paired.iloc[0]
        day_idx = dates.get_loc(pd.Timestamp(one.datetime))
        opens = prices[prices.symbol == one.instrument].set_index("timestamp")["open"]
        self.assertAlmostEqual(
            one.label, opens.loc[dates[day_idx + 2]] / opens.loc[dates[day_idx + 1]] - 1
        )
        momentum = result["comparisons"][1]
        self.assertEqual(momentum["baseline_features"], ["volatility", "liquidity"])
        self.assertEqual(momentum["augmented_features"], ["volatility", "liquidity", "momentum"])

    def test_calendar_ending_exactly_at_next_fold_start(self):
        # Eager RollingGen.generate consumes an extra task with a None start.
        prices, features = fixture_data(days=634 + 126 * 2)
        result = self.evaluate(prices, features, candidate_ids=[])
        self.assertEqual(len(result["folds"]), 2)
        last_label_day = sorted(prices.timestamp.unique())[-3]
        self.assertEqual(
            result["folds"][-1]["segments"]["test"]["end"], evaluation._date(last_label_day)
        )

    def test_test_data_does_not_fit_normalizer_or_model(self):
        prices, features = fixture_data(days=680)
        original = self.evaluate(prices, features, candidate_ids=["candidate"])
        first_test = pd.Timestamp(original["folds"][0]["segments"]["test"]["start"])
        altered = features.copy()
        altered.loc[pd.IndexSlice[first_test:, :], :] += 100
        changed = self.evaluate(prices, altered, candidate_ids=["candidate"])
        for side in ("baseline_model", "augmented_model"):
            self.assertEqual(
                original["comparisons"][0]["folds"][0][side],
                changed["comparisons"][0]["folds"][0][side],
            )

    def test_selection_history_is_not_renamed_oos(self):
        prices, features = fixture_data(days=680)
        last = prices.timestamp.max()
        historical = self.evaluate(prices, features, selection_end=last, candidate_ids=[])
        self.assertEqual(historical["evaluation_scope"], "historical_reanalysis")
        forward = self.evaluate(prices, features, selection_end="2019-01-01", candidate_ids=[])
        self.assertEqual(forward["evaluation_scope"], "post_selection_reanalysis")
        self.assertFalse(forward["methodology"]["unseen_holdout_verified"])
        split = historical["folds"][0]["segments"]["test"]["start"]
        mixed = self.evaluate(prices, features, selection_end=split, candidate_ids=[])
        self.assertEqual(mixed["evaluation_scope"], "mixed")
        unknown = self.evaluate(prices, features, candidate_ids=[])
        self.assertEqual(unknown["evaluation_scope"], "rolling_model_oos_with_selection_caveat")

    def test_missing_candidate_cannot_invent_results(self):
        prices, features = fixture_data(days=680)
        features["candidate"] = np.nan
        result = self.evaluate(prices, features, candidate_ids=["candidate"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["comparisons"][0]["status"], "unavailable")
        self.assertEqual(result["comparisons"][0]["augmented_metrics"], {})

    def test_missing_price_does_not_skip_to_later_label(self):
        prices, features = fixture_data(days=680)
        dates = sorted(prices.timestamp.unique())
        prices = prices[~((prices.symbol == "AAA") & (prices.timestamp == dates[400]))]
        _, _, labels, _ = evaluation._inputs(prices, features)
        self.assertNotIn((dates[398], "AAA"), labels.index)
        self.assertNotIn((dates[399], "AAA"), labels.index)
        self.assertIn((dates[400], "AAA"), labels.index)

    def test_missing_prediction_day_is_not_bridged_into_daily_portfolio(self):
        prices, features = fixture_data(days=680)
        dates = sorted(prices.timestamp.unique())
        features.loc[pd.IndexSlice[dates[640], :], "candidate"] = np.nan
        with patch.object(evaluation, "_portfolio", side_effect=portfolio_stub) as portfolio:
            result = evaluation.evaluate_qlib_study(prices, features, candidate_ids=["candidate"])
        comparison = result["comparisons"][0]
        self.assertEqual(portfolio.call_count, 1)  # Only the unaffected global baseline.
        self.assertEqual(comparison["reason"], "non_contiguous_test_predictions")
        self.assertEqual(comparison["baseline"]["curve"], [])
        self.assertEqual(
            comparison["baseline"]["prediction_coverage"]["missing_dates"],
            [evaluation._date(dates[640])],
        )

    def test_duplicate_column_is_explicit_not_incremental_information(self):
        prices, features = fixture_data(days=680)
        features["candidate"] = features["momentum"]
        result = self.evaluate(prices, features, candidate_ids=["candidate"])
        comparison = result["comparisons"][0]
        self.assertEqual(comparison["duplicate_of"], "momentum")
        self.assertIn("不提供新增信号信息", comparison["note"])
        self.assertTrue(comparison["augmented_metrics"])

    def test_cutoff_partitions_expose_only_computed_signal_statistics(self):
        prices, features = fixture_data(days=680)
        dates = sorted(prices.timestamp.unique())
        result = self.evaluate(
            prices, features, selection_end=dates[650], candidate_ids=["candidate"]
        )
        partitions = result["comparisons"][0]["partitions"]
        self.assertEqual(partitions["historical"]["end"], evaluation._date(dates[650]))
        self.assertEqual(
            partitions["post_selection_reanalysis"]["start"], evaluation._date(dates[651])
        )
        self.assertEqual(partitions["post_selection_reanalysis"]["n_dates"], 27)
        self.assertTrue(partitions["post_selection_reanalysis"]["baseline_signal_metrics"]["daily"])
        self.assertEqual(
            partitions["post_selection_reanalysis"]["portfolio_status"], "not_computed"
        )
        self.assertNotIn("metrics", partitions["post_selection_reanalysis"])
        historical = self.evaluate(prices, features, selection_end=dates[-1], candidate_ids=[])
        future = historical["baseline"]["partitions"]["post_selection_reanalysis"]
        self.assertEqual(future["n_dates"], 0)
        self.assertIsNone(future["start"])

    def test_insufficient_history_and_sample_prices(self):
        prices, features = fixture_data(days=30)
        result = self.evaluate(prices, features, candidate_ids=[])
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["predictions"], [])
        prices["provider"] = "sample"
        with self.assertRaisesRegex(ValueError, "real_futu"):
            self.evaluate(prices, features, candidate_ids=[])

    def test_public_entry_uses_reference_portfolio_after_signal_day(self):
        prices, features = fixture_data(days=665)
        result = evaluation.evaluate_qlib_study(prices, features, candidate_ids=[])
        self.assertEqual(result["status"], "ready")
        first_signal = pd.Timestamp(result["folds"][0]["segments"]["test"]["start"])
        self.assertGreater(pd.Timestamp(result["baseline"]["curve"][0]["date"]), first_signal)
        self.assertGreater(result["baseline"]["costs"]["total"], 0)
        self.assertTrue(result["baseline"]["benchmark_metrics"])


if __name__ == "__main__":
    unittest.main()
