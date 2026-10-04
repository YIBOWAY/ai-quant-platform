from fastapi import APIRouter

from quant_system.api.dependencies import ApiRunsDirDep, OutputDirDep, SettingsDep
from quant_system.api.schemas.collection import CollectionResponse
from quant_system.research.collection_catalog import build_collection

router = APIRouter()


@router.get("/collection", response_model=CollectionResponse)
def get_collection(
    settings: SettingsDep,
    api_runs_dir: ApiRunsDirDep,
    output_dir: OutputDirDep,
) -> dict:
    return build_collection(settings, api_runs_dir=api_runs_dir, output_dir=output_dir)
