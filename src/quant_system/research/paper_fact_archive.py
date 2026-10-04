"""Immutable paper facts, preserved before any optional model interpretation.

Only enumerated paper/config files and algorithm sources are copied. Provider
caches and environment files are outside this archive. It preserves computed
valuation facts and their paper-state inputs, not a historical market-data vintage.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage

SCHEMA = "paper_fact_archive/v1"
IMPLEMENTATION_FILES = (
    "research/paper_fact_archive.py",
    "research/paper_evaluation.py",
    "research/active_metrics.py",
    "d34/hung_sleeve_effect.py",
    "execution/paper_strategy_sleeve_storage.py",
    "execution/paper_strategy_sleeves.py",
    "execution/strategy_replacement.py",
)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def capture_paper_sources(settings):
    """Read relevant live inputs without locks, writes, providers or recovery.

    The caller compares the byte identities before/after the existing facts
    builder. Its legitimate price-cache writes are intentionally outside scope.
    Missing version/config evidence is explicit, never fabricated.
    """
    storage = PaperStrategySleeveStorage(settings.data.data_dir / "api_runs")
    paths = {}
    official_ids = set()
    for sleeve in storage.list_sleeves():
        meta = sleeve.metadata
        if (
            meta.get("automation_source") != "d34"
            or meta.get("fossil") is True
            or meta.get("official_observation") is False
        ):
            continue
        sid = sleeve.sleeve_id
        official_ids.add(sid)
        paths[storage.sleeve_path(sid)] = ("sleeve", True)
        paths[storage.sleeve_signals_path(sid)] = ("signal", False)
        paths[storage.sleeve_executions_path(sid)] = ("execution", False)
        paths[storage.sleeve_lots_path(sid)] = ("lots", False)
        versions = {(sleeve.strategy_config_id, sleeve.strategy_config_version)}
        for item in [*storage.load_signals(sid), *storage.load_executions(sid)]:
            versions.add((item.strategy_config_id, item.strategy_config_version))
        for identifier, version in versions:
            paths[storage.strategy_config_path(identifier, version)] = ("config", True)
        for path in storage.execution_journal_dir(sid).glob("*.json"):
            paths[path] = (
                "committed_journal"
                if path.name.endswith(".committed.json")
                else "uncommitted_journal",
                True,
            )
    _replacement_sources(storage, official_ids, paths)
    package = Path(__file__).resolve().parents[1]
    for relative in IMPLEMENTATION_FILES:
        paths[package / relative] = ("implementation", True)
    references, blobs = [], {}
    for path, (role, required) in sorted(paths.items(), key=lambda item: str(item[0])):
        if not path.exists():
            references.append(
                {
                    "path": str(path),
                    "role": role,
                    "status": "missing" if required else "absent",
                    "sha256": None,
                    "bytes": None,
                }
            )
            continue
        if not path.is_file():
            raise ValueError("paper_fact_source_not_regular")
        raw = path.read_bytes()
        digest = _sha(raw)
        references.append(
            {
                "path": str(path),
                "role": role,
                "status": "available",
                "sha256": digest,
                "bytes": len(raw),
            }
        )
        blobs[digest] = raw
    return {"references": references, "blobs": blobs, "digest": _sha(_json(references))}


def _replacement_sources(storage, official_ids, paths):
    """Follow the exact replacement-history reader's additional file inputs.

    Its journal validation happens before sleeve filtering, so even another
    sleeve's malformed journal affects the computed facts and must be captured.
    Definition paths are bounded to the owner's strategy-library JSON sources;
    this is not authority to archive environment or arbitrary local files.
    """
    directory = storage.root_dir.parent / "strategy_replacements"
    library = storage.root_dir.parent.parent.resolve() / "strategy_library"
    for path in sorted(directory.glob("replacement-*.json")):
        paths[path] = ("replacement_journal", True)
        try:
            record = json.loads(path.read_bytes())
        except (OSError, ValueError):
            continue  # Preserve the unreadable original; the facts reader rejects it.
        if (
            not isinstance(record, dict)
            or record.get("phase") not in {"committed", "aborted"}
            or not isinstance(record.get("request"), dict)
            or record["request"].get("target_sleeve_id") not in official_ids
        ):
            continue
        sides = ("old", "new") if record["phase"] == "committed" else ("old",)
        for side in sides:
            config = record.get(side + "_config")
            if (
                isinstance(config, dict)
                and isinstance(config.get("strategy_config_id"), str)
                and type(config.get("version")) is int
            ):
                config_path = storage.strategy_config_path(
                    config["strategy_config_id"], config["version"]
                )
                if not config_path.resolve().is_relative_to(storage.strategy_configs_dir.resolve()):
                    raise ValueError("paper_fact_replacement_config_outside_scope")
                paths[config_path] = ("replacement_config", True)
            candidate = record.get(side + "_candidate")
            if isinstance(candidate, dict) and isinstance(candidate.get("source_path"), str):
                source = Path(candidate["source_path"])
                if (
                    not source.resolve().is_relative_to(library)
                    or source.suffix != ".json"
                    or source.name.startswith(".")
                ):
                    raise ValueError("paper_fact_replacement_definition_outside_scope")
                paths[source] = ("replacement_definition", True)


def _write_original(path, raw):
    """Create one complete file exclusively; never replace an existing inode."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
            raise ValueError("paper_fact_archive_collision")
        return
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
                raise ValueError("paper_fact_archive_collision") from None
    finally:
        temporary.unlink(missing_ok=True)


def _identity(packet):
    return {
        key: packet[key]
        for key in (
            "schema",
            "facts",
            "facts_digest",
            "source_references",
            "source_completeness",
            "scope",
        )
    }


def persist_fact_archive(cache_root, facts, sources):
    root = Path(cache_root) / "facts"
    references = sources["references"]
    packet = {
        "schema": SCHEMA,
        "facts": facts,
        "facts_digest": _sha(_json(facts)),
        "source_references": references,
        "source_completeness": "incomplete"
        if any(r["status"] == "missing" for r in references)
        else "complete",
        "scope": (
            "paper_state_config_implementation_and_computed_facts_not_provider_response_vintage"
        ),
    }
    identifier = _sha(_json(_identity(packet)))
    packet.update(fact_id=identifier, captured_at=datetime.now(UTC).isoformat())
    path = root / "packets" / f"{identifier}.json"
    # Resolve duplicates from the existing immutable capture time, not now.
    if path.exists() or path.is_symlink():
        old = read_fact_archive(cache_root, {"fact_id": identifier})
        if _identity(old) != _identity(packet):
            raise ValueError("paper_fact_archive_collision")
        return {
            "fact_id": identifier,
            "file_sha256": _sha(path.read_bytes()),
            "facts_digest": old["facts_digest"],
            "captured_at": old["captured_at"],
        }
    for digest, raw in sources["blobs"].items():
        if _sha(raw) != digest:
            raise ValueError("paper_fact_source_changed")
        _write_original(root / "blobs" / digest, raw)
    try:
        _write_original(path, _json(packet))
    except ValueError as exc:
        if str(exc) != "paper_fact_archive_collision":
            raise
        # Another complete writer may have won with the same identity and an
        # earlier capture time. Authenticate its full identity and all blobs,
        # then reuse those original bytes rather than overwriting its timestamp.
        original = read_fact_archive(cache_root, {"fact_id": identifier})
        if _identity(original) != _identity(packet):
            raise ValueError("paper_fact_archive_collision") from exc
        packet = original
    return {
        "fact_id": identifier,
        "file_sha256": _sha(path.read_bytes()),
        "facts_digest": packet["facts_digest"],
        "captured_at": packet["captured_at"],
    }


def read_fact_archive(cache_root, reference):
    """Pure archive read. Current mutable paper files are never consulted."""
    identifier = reference.get("fact_id")
    if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{64}", identifier):
        raise ValueError("paper_fact_archive_id_invalid")
    root = Path(cache_root) / "facts"
    path = root / "packets" / f"{identifier}.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("paper_fact_archive_missing")
    raw = path.read_bytes()
    if reference.get("file_sha256") is not None and _sha(raw) != reference["file_sha256"]:
        raise ValueError("paper_fact_archive_file_changed")
    packet = json.loads(raw)
    if (
        packet.get("schema") != SCHEMA
        or packet.get("fact_id") != identifier
        or _sha(_json(_identity(packet))) != identifier
        or _sha(_json(packet["facts"])) != packet["facts_digest"]
    ):
        raise ValueError("paper_fact_archive_identity_invalid")
    for item in packet["source_references"]:
        if item["status"] != "available":
            continue
        digest = item["sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("paper_fact_archive_blob_invalid")
        blob = root / "blobs" / digest
        if blob.is_symlink() or not blob.is_file() or _sha(blob.read_bytes()) != digest:
            raise ValueError("paper_fact_archive_blob_changed")
    return packet
