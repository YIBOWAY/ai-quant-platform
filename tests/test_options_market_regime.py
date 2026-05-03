from __future__ import annotations

import pandas as pd

from quant_system.options.market_regime import compute_vix_regime, seller_regime_penalty


def test_vix_regime_classifies_normal_market() -> None:
    dates = pd.date_range("2025-01-01", periods=260, freq="B")
    vix = pd.Series(14.0, index=dates)
    vix3m = pd.Series(16.0, index=dates)

    regime = compute_vix_regime(vix, vix3m, signal_date=dates[-1])

    assert regime.volatility_regime == "Normal"
    assert regime.w_vix == 1.0
    assert regime.vix_density == 0.0


def test_vix_regime_classifies_panic_when_density_and_inversion_trigger() -> None:
    dates = pd.date_range("2025-01-01", periods=260, freq="B")
    vix = pd.Series([15.0] * 230 + [32.0] * 30, index=dates)
    vix3m = pd.Series([18.0] * 230 + [28.0] * 30, index=dates)

    regime = compute_vix_regime(vix, vix3m, signal_date=dates[-1])

    assert regime.volatility_regime == "Panic"
    assert regime.w_vix == 0.35
    assert regime.term_ratio is not None and regime.term_ratio > 1.0


def test_seller_regime_penalty_is_harsher_for_sell_put_in_panic() -> None:
    assert seller_regime_penalty("sell_put", "Panic") < seller_regime_penalty(
        "covered_call",
        "Panic",
    )
    assert seller_regime_penalty("sell_put", "Normal") == 0.0
