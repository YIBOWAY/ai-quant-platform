from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from quant_system.api.dependencies import (
    OwnerSessionDep,
    SettingsDep,
    consume_owner_mutation_budget,
    require_mutation_security,
)
from quant_system.api.safety.mutation_rate_limit import D34_MANDATE_ROUTE
from quant_system.api.schemas.safety import (
    D34EmergencyStopRequest,
    EffectiveD34SafetyResponse,
    EffectivePaperSafetyResponse,
)
from quant_system.d34.research_routing import (
    D34ResearchRoutingAuthority,
    project_research_routing,
)
from quant_system.hermes.d34_safety_authority import (
    D34SafetyAuthority,
    D34SafetyAuthorityError,
)
from quant_system.hermes.paper_safety_authority import PaperSafetyAuthority

router = APIRouter()


@router.get(
    "/safety/effective",
    response_model=EffectivePaperSafetyResponse,
)
def effective_paper_safety(
    settings: SettingsDep,
) -> dict[str, object]:
    observation = PaperSafetyAuthority(settings).observe(
        settings.agent_v02_release.workspace_id
    )
    return observation.to_public_dict()


def _d34_authority(request: Request, settings: SettingsDep):
    services = getattr(request.app.state, "services", None)
    injected = services.get("d34_safety_authority") if isinstance(services, dict) else None
    return injected if injected is not None else D34SafetyAuthority(settings)


def _d34_error(exc: D34SafetyAuthorityError) -> HTTPException:
    return HTTPException(
        status_code=422 if exc.code == "d34_safety_validation" else 503,
        detail={"code": exc.code, "message": exc.message},
    )


def _with_research_routing(
    observation: dict[str, object],
    *,
    settings: SettingsDep,
) -> dict[str, object]:
    state = D34ResearchRoutingAuthority(
        settings.data.data_dir / "d34" / "research-routing.json"
    ).observe()
    routing = project_research_routing(observation, state)
    return {
        **observation,
        "research_routing": {
            key: routing[key]
            for key in (
                "requested_default",
                "default_research_entry",
                "final_acceptance_digest",
                "d33_new_intake_enabled",
                "d33_maintenance_enabled",
                "reason_codes",
            )
        },
    }


@router.get("/safety/effective/v2", response_model=EffectiveD34SafetyResponse)
def effective_d34_safety(
    request: Request,
    settings: SettingsDep,
    owner: OwnerSessionDep,
    workspace_id: str = Query(default="default", min_length=1, max_length=128),
) -> dict[str, object]:
    _ = owner
    try:
        observation = _d34_authority(request, settings).observe(workspace_id=workspace_id)
        return _with_research_routing(observation, settings=settings)
    except D34SafetyAuthorityError as exc:
        raise _d34_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": str(exc), "message": str(exc)},
        ) from exc


@router.post("/safety/emergency-stop", response_model=EffectiveD34SafetyResponse)
def set_d34_emergency_stop(
    body: D34EmergencyStopRequest,
    request: Request,
    settings: SettingsDep,
) -> dict[str, object]:
    owner = require_mutation_security(request)
    consume_owner_mutation_budget(
        request,
        owner_user_id=owner.owner_user_id,
        route=D34_MANDATE_ROUTE,
    )
    try:
        observation = _d34_authority(request, settings).set_emergency_stop(
            workspace_id=body.workspace_id,
            enabled=body.enabled,
            reason=body.reason,
        )
        return _with_research_routing(observation, settings=settings)
    except D34SafetyAuthorityError as exc:
        raise _d34_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": str(exc), "message": str(exc)},
        ) from exc
