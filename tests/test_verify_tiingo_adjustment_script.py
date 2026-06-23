"""Guard test for the manual Tiingo adjustment validation script.

The live validation itself is an operator/external gate that needs a real
Tiingo token and network access, so this test only exercises the script's
pure, offline logic and its no-token SKIP path. It never hits the network.
"""

import importlib.util
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "verify_tiingo_adjustment.py"
SCRIPTS_README = REPO_ROOT / "scripts" / "README.md"


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_tiingo_adjustment", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    # Register before exec so dataclass string-annotation resolution can find the
    # module in sys.modules (PEP 563 + @dataclass looks up cls.__module__).
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_script_exists_and_is_indexed() -> None:
    assert SCRIPT_PATH.exists()
    assert "verify_tiingo_adjustment.py" in SCRIPTS_README.read_text(encoding="utf-8")


def test_max_abs_daily_log_return_separates_adjusted_from_split_jump() -> None:
    module = _load_module()
    continuous_adjusted = [100.0, 101.0, 99.5, 100.2]
    assert module.max_abs_daily_log_return(continuous_adjusted) < 0.1
    unadjusted_four_to_one = [400.0, 404.0, 100.5, 101.0]
    assert module.max_abs_daily_log_return(unadjusted_four_to_one) > 1.0


def test_evaluate_adjustment_passes_continuous_adjusted_window() -> None:
    module = _load_module()
    frame = pd.DataFrame(
        {
            "timestamp": ["2020-08-28", "2020-08-31", "2020-09-01"],
            "close": [124.8, 129.0, 134.2],
            "price_adjustment": ["adjusted", "adjusted", "adjusted"],
        }
    )
    assert module.evaluate_adjustment(frame, split_ratio=4.0).ok is True


def test_evaluate_adjustment_rejects_raw_labels() -> None:
    module = _load_module()
    frame = pd.DataFrame(
        {
            "timestamp": ["2020-08-28", "2020-08-31"],
            "close": [124.8, 129.0],
            "price_adjustment": ["raw", "raw"],
        }
    )
    assert module.evaluate_adjustment(frame, split_ratio=4.0).ok is False


def test_evaluate_adjustment_rejects_split_discontinuity() -> None:
    module = _load_module()
    # A ~4x close drop survives -> the series is NOT split-adjusted even if labelled.
    frame = pd.DataFrame(
        {
            "timestamp": ["2020-08-28", "2020-08-31"],
            "close": [499.2, 129.0],
            "price_adjustment": ["adjusted", "adjusted"],
        }
    )
    assert module.evaluate_adjustment(frame, split_ratio=4.0).ok is False


def test_main_skips_without_token(monkeypatch, capsys) -> None:
    module = _load_module()

    class _ApiKeys:
        tiingo_api_token = None

    class _Settings:
        api_keys = _ApiKeys()

    monkeypatch.setattr(module, "reload_settings", lambda: _Settings())
    assert module.main([]) == 0
    assert "SKIP" in capsys.readouterr().out
