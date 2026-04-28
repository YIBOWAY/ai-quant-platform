from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, Request

from quant_system.config.settings import Settings


def get_services(request: Request) -> dict[str, Any]:
    return request.app.state.services


def get_settings(request: Request) -> Settings:
    return request.app.state.services["settings"]


def get_output_dir(request: Request) -> Path:
    return request.app.state.services["output_dir"]


def get_api_runs_dir(request: Request) -> Path:
    return request.app.state.services["api_runs_dir"]


def get_bind_address(request: Request) -> str:
    return request.app.state.services["bind_address"]


SettingsDep = Annotated[Settings, Depends(get_settings)]
OutputDirDep = Annotated[Path, Depends(get_output_dir)]
ApiRunsDirDep = Annotated[Path, Depends(get_api_runs_dir)]
BindAddressDep = Annotated[str, Depends(get_bind_address)]
