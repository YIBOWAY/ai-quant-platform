from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


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
        )
        return DualWritePaperAccountRepository(
            file_repo=file_repo,
            postgres_repo=postgres_repo,
        )
    if mode == "canonical":
        logger.warning(
            "paper account canonical db_mode is reserved for Slice 6; "
            "using file repository in this Slice 5 build"
        )
    return file_repo
