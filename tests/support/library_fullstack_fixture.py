from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _settings(data_root: Path):
    os.environ["QS_DATA_DIR"] = str(data_root)
    os.environ["QS_PAPER_ACCOUNT_DB_MODE"] = "file"
    from quant_system.config.settings import reload_settings

    return reload_settings()


def seed(data_root: Path) -> None:
    from quant_system.execution.account_repository_factory import (
        build_paper_account_repository,
    )
    from quant_system.execution.assistant_remote import project_book
    from tests.test_assistant_remote import _record_strong_hang_candidate

    settings = _settings(data_root)
    repository = build_paper_account_repository(
        data_root / "api_runs",
        settings=settings,
    )
    repository.reset(initial_cash=1_000_000.0)
    _record_strong_hang_candidate(
        settings,
        data_root,
        candidate_id="candidate-library-fullstack",
    )
    candidate = project_book(settings)["candidates"][0]
    print(
        json.dumps(
            {
                "candidate_id": candidate["candidate_id"],
                "source_digest": candidate["source_digest"],
            },
            sort_keys=True,
        )
    )


def inspect(data_root: Path) -> None:
    from quant_system.execution.account_repository_factory import (
        build_paper_account_repository,
    )
    from quant_system.execution.paper_strategy_sleeve_storage import (
        PaperStrategySleeveStorage,
    )

    settings = _settings(data_root)
    account = build_paper_account_repository(
        data_root / "api_runs",
        settings=settings,
    ).load()
    sleeves = PaperStrategySleeveStorage(data_root / "api_runs").list_sleeves()
    allocations = [
        entry
        for entry in (account.ledger if account is not None else [])
        if entry.kind == "sleeve_cash_allocated"
    ]
    print(
        json.dumps(
            {
                "sleeve_count": len(sleeves),
                "allocation_count": len(allocations),
                "allocated_cash": (
                    sleeves[0].initial_allocated_cash if len(sleeves) == 1 else None
                ),
            },
            sort_keys=True,
        )
    )


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"seed", "inspect"}:
        return 2
    data_root = Path(sys.argv[2]).resolve()
    if sys.argv[1] == "seed":
        seed(data_root)
    else:
        inspect(data_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
