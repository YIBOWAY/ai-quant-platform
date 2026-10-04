from fastapi import APIRouter, HTTPException, Query

from quant_system.api.dependencies import SettingsDep
from quant_system.api.schemas.securities import SecuritySearchResponse
from quant_system.data.security_catalog import search_catalog

router = APIRouter()


@router.get("/securities/search", response_model=SecuritySearchResponse)
def securities_search(
    settings: SettingsDep,
    query: str = Query(min_length=1, max_length=100),
    limit: int = Query(default=8, ge=1, le=30),
) -> dict:
    try:
        return search_catalog(settings, query, limit=limit)
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "security_catalog_unavailable",
                "message": "证券目录暂不可用，仍可直接输入标的代码查询真实行情。",
            },
        ) from exc
