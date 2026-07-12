from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from quant_system.hermes.models import HermesArtifactFeedResponse

_EXPECTED_SOURCE_KINDS = {
    "portfolio_risk",
    "prediction",
    "market_foresight",
}


class _ManifestInvalid(ValueError):
    pass


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _ManifestInvalid(f"duplicate manifest key: {key}")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise _ManifestInvalid(f"non-finite JSON number is not allowed: {value}")


def _unavailable(code: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "read_status": "unavailable",
        "as_of": None,
        "items": [],
        "sources": [],
        "warnings": [{"source": "artifact_feed", "code": code}],
    }


def _aware_timestamp(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise _ManifestInvalid("manifest timestamp must be timezone-aware")
        return parsed.astimezone(UTC)
    except (OSError, OverflowError, TypeError, ValueError) as exc:
        raise _ManifestInvalid("manifest timestamp is invalid") from exc


class HermesArtifactCatalog:
    """Read the versioned HQA artifact projection without mutating it."""

    def __init__(
        self,
        feed_path: Path,
        *,
        freshness_budget_seconds: int,
        max_future_clock_skew_seconds: int = 300,
        max_manifest_bytes: int,
    ) -> None:
        self._feed_path = Path(feed_path)
        self._freshness_budget_seconds = freshness_budget_seconds
        self._max_future_clock_skew_seconds = max_future_clock_skew_seconds
        self._max_manifest_bytes = max_manifest_bytes

    def latest(self, *, limit: int) -> dict[str, Any]:
        if not self._feed_path.is_file():
            return {
                "schema_version": "1.0",
                "read_status": "empty",
                "as_of": None,
                "items": [],
                "sources": [],
                "warnings": [
                    {"source": "artifact_feed", "code": "feed_not_built"}
                ],
            }
        try:
            if self._feed_path.stat().st_size > self._max_manifest_bytes:
                return _unavailable("feed_too_large")
            with self._feed_path.open("rb") as manifest_file:
                manifest_bytes = manifest_file.read(self._max_manifest_bytes + 1)
            if len(manifest_bytes) > self._max_manifest_bytes:
                return _unavailable("feed_too_large")
            manifest_text = manifest_bytes.decode("utf-8", errors="strict")
            raw = json.loads(
                manifest_text,
                object_pairs_hook=_object_without_duplicate_keys,
                parse_constant=_reject_constant,
            )
        except (
            OSError,
            RecursionError,
            UnicodeError,
            json.JSONDecodeError,
            _ManifestInvalid,
        ):
            return _unavailable("feed_corrupt")
        if not isinstance(raw, dict):
            return _unavailable("feed_corrupt")
        if raw.get("schema_version") != "1.0":
            return _unavailable("feed_schema_unsupported")
        try:
            manifest = HermesArtifactFeedResponse.model_validate(raw)
        except (RecursionError, TypeError, ValueError):
            return _unavailable("feed_corrupt")
        payload = manifest.model_dump(mode="json")
        try:
            as_of = (
                None if payload["as_of"] is None else _aware_timestamp(payload["as_of"])
            )
            if payload["read_status"] in {"available", "degraded"} and as_of is None:
                raise _ManifestInvalid("available manifest requires as_of")
            if payload["read_status"] == "empty" and payload["items"]:
                raise _ManifestInvalid("empty manifest must not contain artifacts")
            item_ids = [item["id"] for item in payload["items"]]
            if len(item_ids) != len(set(item_ids)):
                raise _ManifestInvalid("manifest artifact ids must be unique")
            source_kinds = [source["kind"] for source in payload["sources"]]
            if len(source_kinds) != len(set(source_kinds)):
                raise _ManifestInvalid("manifest source kinds must be unique")
            if set(source_kinds) != _EXPECTED_SOURCE_KINDS:
                raise _ManifestInvalid("manifest must report every artifact source")
            source_statuses = {
                source["kind"]: source["status"] for source in payload["sources"]
            }
            item_times = {
                item["id"]: _aware_timestamp(item["occurred_at"])
                for item in payload["items"]
            }
            source_times: list[datetime] = []
            for source in payload["sources"]:
                status = source["status"]
                latest_at = source["latest_at"]
                reason_code = source["reason_code"]
                if status == "empty" and latest_at is not None:
                    raise _ManifestInvalid("empty source must not have latest_at")
                if status == "available" and latest_at is None:
                    raise _ManifestInvalid("available source requires latest_at")
                if status in {"degraded", "unavailable"} and not reason_code:
                    raise _ManifestInvalid("failed source requires reason_code")
                if status in {"available", "empty"} and reason_code is not None:
                    raise _ManifestInvalid("healthy source must not have reason_code")
                if latest_at is not None:
                    source_times.append(_aware_timestamp(latest_at))
            if any(
                source_statuses[item["kind"]] != "available"
                for item in payload["items"]
            ):
                raise _ManifestInvalid("artifact item belongs to a failed source")
            failed_sources = {
                source["kind"]
                for source in payload["sources"]
                if source["status"] in {"degraded", "unavailable"}
            }
            warning_sources = {warning["source"] for warning in payload["warnings"]}
            if warning_sources != failed_sources:
                raise _ManifestInvalid("warnings must match failed sources")
            if not payload["items"] and any(
                source["status"] == "available" for source in payload["sources"]
            ):
                raise _ManifestInvalid("available source requires a retained artifact")
            expected_status = (
                "degraded"
                if failed_sources
                else ("available" if payload["items"] else "empty")
            )
            if payload["read_status"] != expected_status:
                raise _ManifestInvalid("manifest aggregate status is inconsistent")
        except _ManifestInvalid:
            return _unavailable("feed_corrupt")

        now = datetime.now(UTC)
        future_boundary = now + timedelta(
            seconds=self._max_future_clock_skew_seconds
        )
        if any(
            timestamp is not None and timestamp > future_boundary
            for timestamp in [as_of, *item_times.values(), *source_times]
        ):
            return _unavailable("feed_clock_skew")
        payload["items"] = sorted(
            payload["items"],
            key=lambda item: (item_times[item["id"]], item["id"]),
            reverse=True,
        )[:limit]
        if (
            as_of is not None
            and (now - as_of).total_seconds()
            > self._freshness_budget_seconds
        ):
            payload["read_status"] = "degraded"
            stale_warning = {"source": "artifact_feed", "code": "feed_stale"}
            if stale_warning not in payload["warnings"]:
                payload["warnings"].append(stale_warning)
        return payload
