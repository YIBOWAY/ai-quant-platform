from __future__ import annotations

from pathlib import Path

from quant_system.config.settings import Settings
from quant_system.execution.account import DEFAULT_ACCOUNT_ID
from quant_system.execution.account_dual_write_repository import (
    DualWritePaperAccountRepository,
)
from quant_system.execution.account_postgres_repository import (
    PostgresPaperAccountRepository,
)
from quant_system.execution.account_repository import PaperAccountRepository
from quant_system.execution.account_storage import PaperAccountStorage


def build_paper_account_repository(
    api_runs_dir: str | Path,
    *,
    settings: Settings,
    account_id: str = DEFAULT_ACCOUNT_ID,
) -> PaperAccountRepository:
    file_repo = PaperAccountStorage(api_runs_dir, account_id=account_id)
    mode = settings.paper_account.db_mode

    if mode == "mirror":
        postgres_repo = PostgresPaperAccountRepository(
            settings=settings,
            account_id=file_repo.account_id,
            source="api_dual_write",
        )
        return DualWritePaperAccountRepository(
            file_repo=file_repo,
            postgres_repo=postgres_repo,
        )

    if mode == "canonical":
        return PostgresPaperAccountRepository(
            settings=settings,
            account_id=file_repo.account_id,
            source="api_canonical",
        )

    return file_repo
