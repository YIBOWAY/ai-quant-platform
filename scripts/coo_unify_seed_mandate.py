"""Seed ONE active isolation Mandate in quantplatform_coo (Step 4 lever).

Explicit owner action for the isolation preview only. It authorizes the
dispatch-research remote on :8876 to enqueue real D-34 jobs. Fail-closed:
refuses to run unless QS_DATABASE_URL points at the quantplatform_coo
database, and refuses when an active mandate already exists.

Usage (from the coo-unify platform worktree):
    QS_DATABASE_URL=postgresql://.../quantplatform_coo \
        python scripts/coo_unify_seed_mandate.py
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from quant_system.config.settings import reload_settings  # noqa: E402
from quant_system.hermes.command_ledger import ROOT_USER_ID  # noqa: E402
from quant_system.hermes.d34_mandate_authority import (  # noqa: E402
    CreateMandateCommand,
    PostgresMandateAuthority,
)

# 扩宇宙 envelope: the plan's own red line says pretty backtests on four ETFs
# are not a cross-sectional conclusion. First research job runs against a
# 20-name liquid US universe instead.
EXPANDED_UNIVERSE = (
    "SPY", "QQQ", "IWM", "DIA",
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META",
    "TSLA", "AVGO", "AMD", "NFLX", "JPM",
    "XOM", "UNH", "V", "COST", "LLY",
)

WORKSPACE_ID = "default"


def main() -> int:
    database_url = os.environ.get("QS_DATABASE_URL", "")
    if "quantplatform_coo" not in database_url:
        print(
            "refusing: QS_DATABASE_URL must point at quantplatform_coo "
            "(isolation database only)",
            file=sys.stderr,
        )
        return 78
    settings = reload_settings()
    authority = PostgresMandateAuthority(settings)
    existing = authority.get_active(workspace_id=WORKSPACE_ID)
    if existing is not None:
        print("refusing: an active mandate already exists for this workspace")
        return 78
    mandate = authority.create(
        CreateMandateCommand(
            owner_user_id=ROOT_USER_ID,
            workspace_id=WORKSPACE_ID,
            duration_days=14,
            universe=EXPANDED_UNIVERSE,
            hypotheses_per_cycle=1,
            max_iterations=2,
            max_experiments_per_iteration=2,
            # The plan allows at most one concurrent research job.
            max_concurrent_jobs=1,
            llm_budget_usd=Decimal("25"),
            llm_warning_fraction=Decimal("0.8"),
            paper_execution_allowed=True,
        )
    )
    public = mandate.to_public_dict() if hasattr(mandate, "to_public_dict") else mandate
    print(f"mandate_id={public['mandate_id']}")
    print(f"policy_digest={public['policy_digest']}")
    print(f"universe_size={len(public['universe'])}")
    print(f"expires_at={public['expires_at']}")
    print("isolation_mandate_seeded=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
