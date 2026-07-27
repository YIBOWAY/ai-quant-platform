"""Versioned Platform expectation for the local Hermes/HQA integration."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any


class HermesCompatibilityContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class HermesCompatibilityContract:
    schema_version: int
    profile: str
    hermes_contract_version_min: int
    required_bool_features: tuple[str, ...]
    required_exact_features: Mapping[str, str]
    required_durable: tuple[str, ...]
    durable_evidence_template: str
    hqa_cli_operations: tuple[str, ...]
    http_endpoints: tuple[tuple[str, str], ...]
    write_contract: Mapping[str, object]


_TOP_LEVEL_FIELDS = {
    "schema_version",
    "profile",
    "hermes_contract_version_min",
    "required_bool_features",
    "required_exact_features",
    "required_durable",
    "durable_evidence_template",
    "hqa_cli_operations",
    "http_endpoints",
    "write_contract",
}


def compatibility_manifest_path() -> Path:
    return Path(__file__).resolve().with_name(
        "agent_v02_hermes_compatibility.v1.json"
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HermesCompatibilityContractError(
                "compatibility manifest contains a duplicate field"
            )
        result[key] = value
    return result


def _string_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
        or len(set(value)) != len(value)
    ):
        raise HermesCompatibilityContractError(
            f"compatibility manifest {field} is invalid"
        )
    return tuple(value)


@lru_cache(maxsize=1)
def load_hermes_compatibility_contract() -> HermesCompatibilityContract:
    path = compatibility_manifest_path()
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise HermesCompatibilityContractError(
            "compatibility manifest is unavailable"
        ) from exc
    if not raw or len(raw) > 64 * 1024:
        raise HermesCompatibilityContractError(
            "compatibility manifest is empty or oversized"
        )
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                HermesCompatibilityContractError(
                    "compatibility manifest contains a non-finite number"
                )
            ),
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise HermesCompatibilityContractError(
            "compatibility manifest is invalid JSON"
        ) from exc
    if not isinstance(payload, dict) or set(payload) != _TOP_LEVEL_FIELDS:
        raise HermesCompatibilityContractError(
            "compatibility manifest fields do not match schema v1"
        )
    if payload.get("schema_version") != 1:
        raise HermesCompatibilityContractError(
            "compatibility manifest schema version is unsupported"
        )
    if payload.get("profile") != "local_agent_v0_2":
        raise HermesCompatibilityContractError(
            "compatibility manifest profile is unsupported"
        )
    contract_min = payload.get("hermes_contract_version_min")
    if (
        isinstance(contract_min, bool)
        or not isinstance(contract_min, int)
        or contract_min < 1
    ):
        raise HermesCompatibilityContractError(
            "compatibility manifest contract version is invalid"
        )
    exact = payload.get("required_exact_features")
    if (
        not isinstance(exact, dict)
        or set(exact)
        != {
            "managed_run_history_authority",
            "managed_session_fork_mode",
        }
        or any(not isinstance(value, str) or not value for value in exact.values())
    ):
        raise HermesCompatibilityContractError(
            "compatibility manifest exact features are invalid"
        )
    evidence_template = payload.get("durable_evidence_template")
    if (
        not isinstance(evidence_template, str)
        or evidence_template.count("{capability}") != 1
    ):
        raise HermesCompatibilityContractError(
            "compatibility manifest durable evidence template is invalid"
        )
    endpoints = payload.get("http_endpoints")
    if not isinstance(endpoints, list) or not endpoints:
        raise HermesCompatibilityContractError(
            "compatibility manifest endpoints are invalid"
        )
    endpoint_pairs: list[tuple[str, str]] = []
    for endpoint in endpoints:
        if (
            not isinstance(endpoint, dict)
            or set(endpoint) != {"method", "path"}
            or endpoint.get("method") not in {"GET", "POST"}
            or not isinstance(endpoint.get("path"), str)
            or not str(endpoint["path"]).startswith("/")
        ):
            raise HermesCompatibilityContractError(
                "compatibility manifest endpoint is invalid"
            )
        endpoint_pairs.append((str(endpoint["method"]), str(endpoint["path"])))
    if len(set(endpoint_pairs)) != len(endpoint_pairs):
        raise HermesCompatibilityContractError(
            "compatibility manifest endpoints are duplicated"
        )
    write_contract = payload.get("write_contract")
    if not isinstance(write_contract, dict):
        raise HermesCompatibilityContractError(
            "compatibility manifest write contract is invalid"
        )
    return HermesCompatibilityContract(
        schema_version=1,
        profile="local_agent_v0_2",
        hermes_contract_version_min=contract_min,
        required_bool_features=_string_tuple(
            payload.get("required_bool_features"),
            field="required_bool_features",
        ),
        required_exact_features=MappingProxyType(dict(exact)),
        required_durable=_string_tuple(
            payload.get("required_durable"),
            field="required_durable",
        ),
        durable_evidence_template=evidence_template,
        hqa_cli_operations=_string_tuple(
            payload.get("hqa_cli_operations"),
            field="hqa_cli_operations",
        ),
        http_endpoints=tuple(endpoint_pairs),
        write_contract=MappingProxyType(dict(write_contract)),
    )


__all__ = [
    "HermesCompatibilityContract",
    "HermesCompatibilityContractError",
    "compatibility_manifest_path",
    "load_hermes_compatibility_contract",
]
