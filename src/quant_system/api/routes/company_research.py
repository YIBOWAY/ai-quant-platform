from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from quant_system.api.dependencies import SettingsDep, require_mutation_security
from quant_system.api.schemas.company_research import (
    CompanyResearchCompareResponse,
    CompanyResearchRefreshRequest,
    CompanyResearchResponse,
    DataSourceCheckRequest,
    DataSourcesResponse,
)
from quant_system.api.schemas.market_data import DailyBackupResponse
from quant_system.data.backup_bars import read_daily_bars_with_backup
from quant_system.data.price_history import HistoricalPriceReadError
from quant_system.data.providers.longbridge import (
    LongbridgeProviderError,
    normalize_longbridge_symbol,
)
from quant_system.research import company_research as service
from quant_system.research import data_source_checks

router = APIRouter()


def _symbol(value):
    try:
        return normalize_longbridge_symbol(value)
    except LongbridgeProviderError as exc:
        raise HTTPException(422, detail={"code": exc.code, "message": exc.message}) from exc


@router.get("/company-research", response_model=CompanyResearchResponse)
def company_research(settings: SettingsDep, symbol: str = Query(max_length=32)):
    return service.read_company(settings, _symbol(symbol))


@router.get("/company-research/compare", response_model=CompanyResearchCompareResponse)
def company_compare(settings: SettingsDep, symbols: str = Query(max_length=150)):
    values = list(dict.fromkeys(_symbol(value) for value in symbols.split(",")))
    if not 1 <= len(values) <= 4:
        raise HTTPException(422, detail="一次只比较1至4家公司。")
    return {"items": [service.read_company(settings, value) for value in values]}


@router.post(
    "/company-research/refresh",
    response_model=CompanyResearchResponse,
    status_code=202,
    dependencies=[Depends(require_mutation_security)],
)
def refresh_company(
    request: CompanyResearchRefreshRequest, settings: SettingsDep, background_tasks: BackgroundTasks
):
    symbol = _symbol(request.symbol)
    try:
        lease = service.begin_refresh(settings, symbol)
    except service.ResearchBusy as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    try:
        background_tasks.add_task(service.finish_refresh, settings, symbol, lease)
        return service.read_company(settings, symbol)
    except Exception:
        lease.close()
        raise


@router.get("/data-sources", response_model=DataSourcesResponse)
def data_sources(settings: SettingsDep):
    return data_source_checks.read_checks(settings)


@router.post(
    "/data-sources/check", status_code=202, response_model=DataSourcesResponse,
    dependencies=[Depends(require_mutation_security)]
)
def check_sources(
    request: DataSourceCheckRequest, settings: SettingsDep, background_tasks: BackgroundTasks
):
    symbol = _symbol(request.symbol)
    try:
        lease = data_source_checks.begin_checks(settings, symbol)
    except service.ResearchBusy as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    try:
        background_tasks.add_task(data_source_checks.finish_checks, settings, symbol, lease)
        return data_source_checks.read_checks(settings)
    except Exception:
        lease.close()
        raise


@router.get("/market-data/daily-backup", response_model=DailyBackupResponse)
def daily_backup(settings: SettingsDep, symbols: str, start: str, end: str):
    """Explicit read fallback only; frozen research and paper protocols do not call this."""
    try:
        result = read_daily_bars_with_backup(
            settings=settings,
            symbols=symbols.split(","),
            start=start,
            end=end,
            backup_providers=("longbridge",),
        )
        return result.to_dict()
    except HistoricalPriceReadError as exc:
        raise HTTPException(
            422 if exc.code == "historical_prices_invalid_request" else 503,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
