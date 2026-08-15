"""Mirror the isolation file paper account into quantplatform_coo only."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from quant_system.config.settings import reload_settings
from quant_system.execution.account_backfill import backfill_account_file
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.storage.database import get_database

_ISOLATION_DATABASE = "quantplatform_coo"


def _postgres_database_name(url: str) -> str:
    return urlparse(url).path.lstrip("/").split("/")[0]


def main() -> int:
    settings = reload_settings()
    resolved = ""
    if settings.database.url is not None:
        resolved = settings.database.url.get_secret_value()
    if _postgres_database_name(resolved) != _ISOLATION_DATABASE:
        print(
            "refusing: resolved database name must be exactly quantplatform_coo",
            file=sys.stderr,
        )
        return 78
    account_path = (
        Path(settings.data.data_dir)
        / "api_runs"
        / "paper_account"
        / "default"
        / "account.json"
    )
    if not account_path.is_file():
        print("refusing: isolation file paper account is missing", file=sys.stderr)
        return 78
    database = get_database(settings)
    if database is None:
        print("refusing: isolation database unavailable", file=sys.stderr)
        return 78
    with database.connect() as conn:
        count_row = conn.execute(
            "SELECT count(*) FROM quant_system.paper_accounts WHERE owner_user_id = %s",
            (ROOT_USER_ID,),
        ).fetchone()
    if count_row is None or int(count_row[0]) == 0:
        backfill_account_file(
            account_path, settings=settings, source="coo_unify_preview"
        )
    with database.connect() as conn:
        existing = conn.execute(
            """
            SELECT quant_system.current_agent_v02_paper_authority_epoch(%s, %s)
            """,
            (ROOT_USER_ID, "default"),
        ).fetchone()
        if existing is None or existing[0] is None:
            conn.execute(
                "SELECT quant_system.bump_agent_v02_paper_authority_owner(%s)",
                (ROOT_USER_ID,),
            )
            row = conn.execute(
                """
                SELECT quant_system.ensure_agent_v02_paper_authority_epoch(%s, %s)
                """,
                (ROOT_USER_ID, "default"),
            ).fetchone()
        else:
            row = existing
    print(
        {
            "seeded": True,
            "database": _ISOLATION_DATABASE,
            "paper_authority_epoch": None if row is None else int(row[0]),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
