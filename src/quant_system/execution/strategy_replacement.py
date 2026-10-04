"""Explicit same-contract strategy version replacement, never new allocation.

Only a fixed admission verifier may authorize this operation. The existing
account -> sleeve -> book lock order is retained. Account, lots and historical
executions are read-only; an immutable config version and the same sleeve's
pointer replace two simultaneously funded candidates. Interrupted operations
remain PAUSED and require explicit, digest-bound recovery.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import re
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from quant_system.execution import assistant_remote
from quant_system.execution.account_repository_factory import build_paper_account_repository
from quant_system.execution.paper_observation_safety import observe_paper_emergency_stop
from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage
from quant_system.execution.paper_strategy_sleeves import (
    SleeveLot,
    StrategyConfig,
    StrategySleeve,
    StrategySleeveMode,
    StrategySleeveStatus,
)
from quant_system.research.definition_paper import definition_config_fields, require_paper_costs
from quant_system.research.evaluation_service import _hash, _write
from quant_system.research.fingerprint_grading import frozen_definition_identity
from quant_system.research.strategy_definition import validate_definition

SCHEMA = "same_contract_strategy_replacement/v1"
MARKER = "strategy_replacement_id"
_ID = re.compile(r"replacement-[0-9a-f]{24}\Z")
# The owner UI and the paper report both test this exact token, so every writer
# must emit this spelling; a second one silently drops their warning.
PERFORMANCE_SCOPE_ACROSS_VERSIONS = "cumulative_sleeve_history_across_versions"
# Spelling persisted by builds predating the unification; readers still accept it.
LEGACY_PERFORMANCE_SCOPE_ACROSS_VERSIONS = "cumulative_sleeve_history_spans_versions"

logger = logging.getLogger(__name__)
_SAME_FIELDS = (
    "symbols",
    "benchmark_symbol",
    "provider",
    "price_adjustment",
    "execution_price",
    "rebalance",
    "commission_bps",
    "slippage_bps",
    "whole_share_orders",
    "min_order_value",
)


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _now():
    return datetime.now(UTC).isoformat()


def _path(settings, identity):
    _require(isinstance(identity, str) and _ID.fullmatch(identity), "replacement_id_invalid")
    return Path(settings.data.data_dir) / "api_runs/strategy_replacements" / f"{identity}.json"


@contextmanager
def _financial_locks(settings, repo, storage, identity):
    """Also handle an error raised while the account transaction is exiting."""
    path = _path(settings, identity)
    before = file_sha(path) if path.exists() else None
    try:
        with (
            repo.mutation_lock(),
            storage.mutation_lock(),
            assistant_remote._book_mutation_lock(settings),
        ):
            yield
    except Exception as exc:
        # All financial locks have unwound. A state-only emergency pause takes
        # only the sleeve lock; it never reacquires account behind that lock and
        # never writes an account/book. Do not freeze a later replacement.
        try:
            if path.exists() and file_sha(path) != before:
                with storage.mutation_lock():
                    record = _load_journal(settings, identity)
                    sleeve = storage.load_sleeve(record["request"]["target_sleeve_id"])
                    ours = sleeve.metadata.get(MARKER) in {None, identity} and (
                        sleeve.metadata.get("replacement_committed_id") == identity
                        or (
                            sleeve.strategy_config_version == record["old_config"]["version"]
                            and sleeve.metadata.get("candidate_id")
                            == record["request"]["target_candidate_id"]
                        )
                    )
                    if ours:
                        _hold_failed(settings, record, storage, exc)
        except (OSError, ValueError, KeyError):
            pass
        raise


def _save_journal(settings, record, phase):
    record["phase"] = phase
    record.setdefault("events", []).append({"phase": phase, "at": _now()})
    record["journal_digest"] = _hash({k: v for k, v in record.items() if k != "journal_digest"})
    _write(_path(settings, record["replacement_id"]), record)


def _load_journal(settings, identity):
    record = json.loads(_path(settings, identity).read_text())
    _require(
        record.get("schema") == SCHEMA
        and record.get("replacement_id") == identity
        and identity == "replacement-" + _hash(record["request"])[:24]
        and record.get("journal_digest")
        == _hash({k: v for k, v in record.items() if k != "journal_digest"}),
        "replacement_journal_changed",
    )
    return record


def _candidate(book, identity):
    rows = [row for row in book["candidates"] if row.get("candidate_id") == identity]
    _require(len(rows) == 1, "replacement_candidate_identity_missing")
    return rows[0]


def _aborted_history_contains(directory, sleeve, ancestor):
    """Only a verified same-sleeve abort chain can supersede an older marker."""
    current, visited = sleeve.metadata.get("replacement_aborted_id"), set()
    while current and current not in visited:
        _require(
            isinstance(current, str) and _ID.fullmatch(current), "replacement_abort_history_invalid"
        )
        visited.add(current)
        record = json.loads((directory / f"{current}.json").read_text())
        _require(
            record.get("schema") == SCHEMA
            and record.get("replacement_id") == current
            and record.get("journal_digest")
            == _hash({k: v for k, v in record.items() if k != "journal_digest"}),
            "replacement_journal_changed",
        )
        if (
            record["phase"] != "aborted"
            or record["request"]["target_sleeve_id"] != sleeve.sleeve_id
            or record["old_config"]["version"] != sleeve.strategy_config_version
        ):
            return False
        if current == ancestor:
            return True
        current = record["old_sleeve"]["metadata"].get("replacement_aborted_id")
    return False


_TARGET_SLEEVE_ID = re.compile(r'"target_sleeve_id"\s*:\s*"([^"]*)"')


def _target_sleeve_ids(text):
    """Best-effort owner of a journal document that will not parse as JSON."""
    return {match.group(1) for match in _TARGET_SLEEVE_ID.finditer(text)}


def _target_sleeve_id(document):
    request = document.get("request") if isinstance(document, dict) else None
    return request.get("target_sleeve_id") if isinstance(request, dict) else None


def _journal_matches(document, identity):
    if not isinstance(document, dict):
        return False
    try:
        return (
            document.get("schema") == SCHEMA
            and document.get("replacement_id") == identity
            and document.get("journal_digest")
            == _hash({k: v for k, v in document.items() if k != "journal_digest"})
        )
    except (TypeError, ValueError):
        return False


def sleeve_replacement_pending(storage, sleeve):
    """Read-only scheduling guard, including crash before PAUSED was persisted.

    Only evidence attributable to this sleeve may freeze it. A journal naming
    another sleeve, or one that can be neither read nor attributed, is reported
    and skipped; corrupt evidence naming this sleeve still fails closed.
    """
    if sleeve.metadata.get(MARKER):
        return True
    root = getattr(storage, "root_dir", None)
    if root is None:
        return False
    for path in (Path(root).parent / "strategy_replacements").glob("replacement-*.json"):
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            logger.warning("ignored_corrupt_record:%s", path.name)
            continue
        try:
            document = json.loads(text)
        except ValueError:
            # A truncated write has no structure left to attribute; the raw
            # target field is the only remaining evidence of who owns it.
            if sleeve.sleeve_id in _target_sleeve_ids(text):
                return True
            logger.warning("ignored_corrupt_record:%s", path.name)
            continue
        if _target_sleeve_id(document) != sleeve.sleeve_id:
            if not _journal_matches(document, path.stem):
                logger.warning("ignored_corrupt_record:%s", path.name)
            continue
        try:
            _require(_journal_matches(document, path.stem), "replacement_journal_changed")
            if document["phase"] == "committed":
                version = document["new_config"]["version"]
                if sleeve.strategy_config_version < version or (
                    sleeve.strategy_config_version == version
                    and sleeve.metadata.get("replacement_committed_id")
                    != document["replacement_id"]
                ):
                    return True
            elif document["phase"] == "aborted":
                version = document["old_config"]["version"]
                if sleeve.strategy_config_version < version or (
                    sleeve.strategy_config_version == version
                    and not _aborted_history_contains(
                        path.parent, sleeve, document["replacement_id"]
                    )
                ):
                    return True
            else:
                return True
        except (OSError, ValueError, KeyError, TypeError):
            return True
    return False


def _definition(settings, candidate, *, historical=False):
    _require(
        candidate.get("source") == "strategy_definition",
        "replacement_requires_frozen_strategy_definition",
    )
    path = Path(candidate["source_path"]).resolve()
    _require(
        path.is_relative_to(Path(settings.data.data_dir).resolve() / "strategy_library"),
        "replacement_source_outside_owner_root",
    )
    _require(file_sha(path) == candidate.get("source_digest"), "replacement_source_changed")
    validator = frozen_definition_identity if historical else validate_definition
    definition = validator(json.loads(path.read_text()))
    _require(
        candidate.get("factor_id") == "definition_" + definition.content_digest[:24]
        and candidate.get("universe") == list(definition.symbols),
        "replacement_candidate_definition_mismatch",
    )
    return definition



def _target_status_allows_replacement(storage, sleeve):
    if sleeve.status == StrategySleeveStatus.RUNNING:
        return True
    if (sleeve.status != StrategySleeveStatus.PAUSED
            or not sleeve.metadata.get("replacement_restore_blocker")
            or not sleeve.metadata.get("replacement_aborted_id")):
        return False
    # A failed upgrade can restore the old identity while keeping obsolete code
    # paused. Only that exact verified abort edge may enter another upgrade.
    return any(
        edge["record"]["phase"] == "aborted"
        and edge["record"]["replacement_id"] == sleeve.metadata["replacement_aborted_id"]
        and edge["after"] == _financial_projection(sleeve)
        for edge in _terminal_transitions(storage, sleeve.sleeve_id)
    )

def inspect_replacement_target(settings, *, candidate_id, sleeve_id=None):
    """Read-only exact target identity for proposal freezing; never an authorization."""
    book = assistant_remote.load_book(settings)
    candidate = _candidate(book, candidate_id)
    _require(
        candidate.get("source") == "strategy_definition",
        "replacement_requires_frozen_strategy_definition",
    )
    selected = sleeve_id or candidate.get("sleeve_id")
    _require(
        isinstance(selected, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", selected),
        "replacement_target_not_current",
    )
    storage = PaperStrategySleeveStorage(Path(settings.data.data_dir) / "api_runs")
    sleeve = storage.load_sleeve(selected)
    _require(
        candidate.get("status") == "hung"
        and candidate.get("sleeve_id") == selected
        and sleeve.metadata.get("candidate_id") == candidate_id
        and _target_status_allows_replacement(storage, sleeve)
        and sleeve.mode == StrategySleeveMode.ALLOCATED
        and not sleeve_replacement_pending(storage, sleeve),
        "replacement_target_not_current",
    )
    _require(
        sum(
            row.get("status") == "hung" and row.get("sleeve_id") == selected
            for row in book["candidates"]
        )
        == 1,
        "replacement_duplicate_sleeve_binding",
    )
    config = storage.load_frozen_strategy_config(
        sleeve.strategy_config_id, version=sleeve.strategy_config_version
    )
    definition = _definition(settings, candidate, historical=True)
    _require(
        config.strategy_definition == definition.model_dump(mode="json")
        and sleeve.metadata.get("definition_digest") == definition.content_digest
        and (sleeve.metadata.get("source_digest") or sleeve.metadata.get("candidate_code_digest"))
        == candidate["source_digest"],
        "replacement_target_definition_mismatch",
    )
    return {
        "replacement_target": {
            "candidate_id": candidate_id,
            "sleeve_id": selected,
            "definition_digest": definition.content_digest,
            "config_id": config.strategy_config_id,
            "config_version": config.version,
        },
        "definition": definition.model_dump(mode="json"),
        "source_sha256": candidate["source_digest"],
        "source_path": str(Path(candidate["source_path"]).resolve()),
    }


def _paper_only(settings):
    _require(
        settings.safety.live_trading_enabled is False and settings.safety.paper_trading is True,
        "replacement_paper_safety_closed",
    )


def _gate(settings, record, new, old, sleeve, config, book):
    from quant_system.research import admission_v2

    _require(admission_v2.authority_configured(settings) is True, "replacement_authority_disabled")
    _require(
        observe_paper_emergency_stop(
            settings, workspace_id=str(sleeve.metadata.get("workspace_id", "default"))
        ).get("active")
        is False,
        "replacement_emergency_or_authority_unavailable",
    )
    verifier = getattr(admission_v2, "verify_for_replacement", None)
    _require(callable(verifier), "replacement_admission_verifier_unavailable")
    result = verifier(
        settings,
        new_candidate=new,
        target_candidate=old,
        target_sleeve=sleeve,
        target_config=config,
        book=book,
    )
    request = record["request"]
    _require(
        result.get("status") == "passed"
        and result.get("validated_tier") == "T2"
        and result.get("capital_delta_usd") == 0
        and result.get("replacement_target")
        == {
            "candidate_id": request["target_candidate_id"],
            "sleeve_id": sleeve.sleeve_id,
            "definition_digest": request["expected_old_definition_digest"],
            "config_id": config.strategy_config_id,
            "config_version": request["expected_old_config_version"],
        },
        "replacement_admission_target_mismatch",
    )
    return result


def _preflight(settings, *, new_candidate, target_candidate, target_sleeve, target_config, book):
    """Expensive fixed producer work is only called with NO financial locks held."""
    from quant_system.research import admission_v2

    operation = getattr(admission_v2, "prepare_replacement_preflight", None)
    _require(callable(operation), "replacement_preflight_unavailable")
    operation(
        settings,
        new_candidate=new_candidate,
        target_candidate=target_candidate,
        target_sleeve=target_sleeve,
        target_config=target_config,
        book=book,
    )


def _old_target_view(record):
    sleeve = StrategySleeve.model_validate(record["old_sleeve"])
    sleeve.status = StrategySleeveStatus.PAUSED
    sleeve.metadata[MARKER] = record["replacement_id"]
    return sleeve


def inspect_replacement_recovery_target(settings, *, replacement_id):
    """Authenticate a PAUSED preimage for lock-free fixed qualification preflight.

    It grants no authority. Final account/book/version CAS is repeated under the
    mutation locks by recover_replacement after the expensive work finishes.
    """
    record = _load_journal(settings, replacement_id)
    _require(
        record["phase"] == "needs_preflight" and record.get("recovery_action") != "abort",
        "replacement_not_waiting_preflight",
    )
    base = Path(settings.data.data_dir) / "api_runs"
    storage = PaperStrategySleeveStorage(base)
    sleeve = storage.load_sleeve(record["request"]["target_sleeve_id"])
    _require(
        sleeve.status == StrategySleeveStatus.PAUSED
        and sleeve.metadata.get(MARKER) == replacement_id,
        "replacement_recovery_marker_changed",
    )
    book = assistant_remote.load_book(settings)
    _require(_book_state(book, record) == "before", "replacement_binding_needs_restore")
    repo = build_paper_account_repository(base, settings=settings)
    account = repo.load()
    _require(
        account is not None and _economic_snapshot(account, storage, sleeve) == record["economic"],
        "replacement_economics_changed",
    )
    config = storage.load_frozen_strategy_config(
        record["old_config"]["strategy_config_id"], version=record["old_config"]["version"]
    )
    _require(
        config.model_dump(mode="json") == record["old_config"], "replacement_old_config_changed"
    )
    _definition(settings, record["old_candidate"], historical=True)
    _definition(settings, record["new_candidate"])
    return {
        "new_candidate": copy.deepcopy(record["new_candidate"]),
        "target_candidate": copy.deepcopy(record["old_candidate"]),
        "target_sleeve": _old_target_view(record),
        "target_config": config,
        "book": book,
        "journal_digest": record["journal_digest"],
    }


def _economic_snapshot(account, storage, sleeve):
    _require(account.account_id == sleeve.account_id, "replacement_account_sleeve_mismatch")
    source = "strategy:" + sleeve.sleeve_id
    owned = {
        symbol: position.source_quantity.get(source, 0.0)
        for symbol, position in account.positions.items()
        if position.source_quantity.get(source, 0.0)
    }
    lots = {}
    for lot in storage.load_sleeve_lots(sleeve.sleeve_id):
        _require(
            lot.sleeve_id == sleeve.sleeve_id and lot.account_id == account.account_id,
            "replacement_lot_owner_mismatch",
        )
        lots[lot.symbol] = lots.get(lot.symbol, 0.0) + lot.quantity
    _require(
        set(owned) == set(lots)
        and all(
            math.isclose(owned[symbol], quantity, rel_tol=0, abs_tol=1e-8)
            and account.position_quantity(symbol) + 1e-8 >= quantity
            for symbol, quantity in lots.items()
        ),
        "replacement_lot_account_mismatch",
    )
    history = {}
    directory = storage.sleeve_dir(sleeve.sleeve_id)
    if directory.exists():
        history = {
            str(path.relative_to(directory)): file_sha(path)
            for path in directory.rglob("*")
            if path.is_file() and path.name not in {"sleeve.json", "sleeve.pending.json"}
        }
    value = {
        "account_id": account.account_id,
        "sleeve_id": sleeve.sleeve_id,
        "initial_allocated_cash": sleeve.initial_allocated_cash,
        "sleeve_cash": sleeve.cash,
        "account_sleeve_cash": account.sleeve_cash.get(sleeve.sleeve_id),
        "account_owned_positions": owned,
        "target_ledger": [
            row.model_dump(mode="json")
            for row in account.ledger
            if row.source == "strategy:" + sleeve.sleeve_id
        ],
        "history_files": history,
    }
    _require(value["account_sleeve_cash"] == sleeve.cash, "replacement_cash_partition_mismatch")
    return value


def _no_pending(account, storage, sleeve):
    _require(
        not storage.pending_sleeve_path(sleeve.sleeve_id).exists(), "replacement_sleeve_pending"
    )
    _require(
        not any(row.source == "strategy:" + sleeve.sleeve_id for row in account.pending_orders),
        "replacement_pending_orders",
    )
    _require(
        not any(
            str(row.status) in {"pending", "blocked", "partially_filled"}
            for row in storage.load_executions(sleeve.sleeve_id)
        ),
        "replacement_pending_execution",
    )
    _require(
        not list(storage.execution_journal_dir(sleeve.sleeve_id).glob("*.pending.json")),
        "replacement_pending_execution_journal",
    )


def _result(record):
    return {
        "schema": SCHEMA,
        "replacement_id": record["replacement_id"],
        "status": record["phase"],
        "sleeve_id": record["request"]["target_sleeve_id"],
        "capital_delta_usd": 0,
        "old_config_version": record["old_config"]["version"],
        "new_config_version": record["new_config"]["version"],
        "active_config_version": record["old_config"]["version"]
        if record["phase"] == "aborted"
        else record["new_config"]["version"],
        "old_candidate_id": record["request"]["target_candidate_id"],
        "new_candidate_id": record["request"]["new_candidate_id"],
        "committed_at": record.get("committed_at") if record["phase"] == "committed" else None,
        "performance_scope": PERFORMANCE_SCOPE_ACROSS_VERSIONS,
        "current_version_performance": {
            "status": "not_evaluated",
            "reason": "version_partitioned_observations_required",
        },
    }


def _lot_documents(lots):
    return sorted(
        (lot.model_dump(mode="json") for lot in lots),
        key=lambda row: (row["symbol"], row["lot_id"]),
    )


def _version_metadata(record):
    return {
        "version_transition": {
            "replacement_id": record["replacement_id"],
            "from_config_version": record["old_config"]["version"],
            "to_config_version": record["new_config"]["version"],
            "effective_at": record["committed_at"],
        },
        "current_version_observation_start": record["committed_at"],
        "performance_scope": PERFORMANCE_SCOPE_ACROSS_VERSIONS,
        "current_version_performance": {
            "status": "not_evaluated",
            "reason": "version_partitioned_observations_required",
        },
    }


def _after_candidates(record):
    old, new = copy.deepcopy(record["old_candidate"]), copy.deepcopy(record["new_candidate"])
    request = record["request"]
    old.update(
        status="superseded",
        replaced_by=request["new_candidate_id"],
        replacement_id=record["replacement_id"],
    )
    new.update(
        status="hung",
        sleeve_id=request["target_sleeve_id"],
        replaces=request["target_candidate_id"],
        replacement_id=record["replacement_id"],
        strategy_config_version=record["new_config"]["version"],
        performance_scope=PERFORMANCE_SCOPE_ACROSS_VERSIONS,
        current_version_performance={
            "status": "not_evaluated",
            "reason": "version_partitioned_observations_required",
        },
    )
    return old, new


def _financial_projection(sleeve):
    """Exactly the nine fields used by hung_sleeve_effect's existing audit."""
    return {
        key: sleeve.model_dump(mode="json")[key]
        for key in (
            "sleeve_id",
            "account_id",
            "strategy_config_id",
            "strategy_config_version",
            "mode",
            "initial_allocated_cash",
            "cash",
            "created_at",
            "metadata",
        )
    }


def _terminal_transitions(storage, sleeve_id):
    """Semantic audit of owner-generated zero-economic-change journal edges."""
    root = Path(storage.root_dir).parent / "strategy_replacements"
    owner = Path(storage.root_dir).parent.parent.resolve()
    transitions = []
    for path in sorted(root.glob("replacement-*.json")):
        record = json.loads(path.read_text())
        _require(
            record.get("schema") == SCHEMA
            and record.get("replacement_id") == path.stem
            and record.get("replacement_id") == "replacement-" + _hash(record["request"])[:24]
            and record.get("journal_digest")
            == _hash({k: v for k, v in record.items() if k != "journal_digest"}),
            "replacement_history_journal_changed",
        )
        if record["request"]["target_sleeve_id"] != sleeve_id or record["phase"] not in {
            "committed",
            "aborted",
        }:
            continue
        before = StrategySleeve.model_validate(record["old_sleeve"])
        after = StrategySleeve.model_validate(
            record["new_sleeve"] if record["phase"] == "committed" else record["restored_sleeve"]
        )
        left, right = _financial_projection(before), _financial_projection(after)
        stable = set(left) - {"strategy_config_version", "metadata"}
        _require(
            all(left[key] == right[key] for key in stable) and before.sleeve_id == sleeve_id,
            "replacement_history_economic_change",
        )
        documents = _lot_documents(
            [SleeveLot.model_validate(row) for row in record["transition_lots"]]
        )
        _require(
            _hash(documents) == record["transition_lots_digest"]
            and all(
                row["sleeve_id"] == sleeve_id and row["account_id"] == before.account_id
                for row in documents
            ),
            "replacement_history_lots_changed",
        )
        economic = record["economic"]
        _require(
            economic["sleeve_cash"] == economic["account_sleeve_cash"] == before.cash
            and economic["initial_allocated_cash"] == before.initial_allocated_cash,
            "replacement_history_economic_change",
        )
        config_pairs = [(record["old_config"], record["old_candidate"])]
        if record["phase"] == "committed":
            config_pairs.append((record["new_config"], record["new_candidate"]))
        for config, candidate in config_pairs:
            config_path = storage.strategy_config_path(
                config["strategy_config_id"], config["version"]
            )
            _require(
                config_path.resolve().is_relative_to(storage.strategy_configs_dir.resolve())
                and _hash(json.loads(config_path.read_text())) == _hash(config),
                "replacement_history_config_changed",
            )
            source = Path(candidate["source_path"])
            _require(
                source.resolve().is_relative_to(owner / "strategy_library")
                and file_sha(source) == candidate["source_digest"]
                and _hash(json.loads(source.read_text())) == _hash(config["strategy_definition"]),
                "replacement_history_source_changed",
            )
        request = record["request"]
        _require(
            before.strategy_config_id == record["old_config"]["strategy_config_id"]
            and before.strategy_config_version
            == record["old_config"]["version"]
            == request["expected_old_config_version"]
            and before.metadata["candidate_id"] == request["target_candidate_id"]
            and record["old_config"]["strategy_definition"]["content_digest"]
            == request["expected_old_definition_digest"],
            "replacement_history_old_identity_changed",
        )
        if record["phase"] == "committed":
            _require(
                after.strategy_config_id
                == record["new_config"]["strategy_config_id"]
                == before.strategy_config_id
                and after.strategy_config_version
                == record["new_config"]["version"]
                > before.strategy_config_version
                and after.metadata["candidate_id"] == request["new_candidate_id"]
                and record["new_candidate"]["source_digest"]
                == request["expected_new_source_digest"]
                and all(
                    record["old_config"]["strategy_definition"][key]
                    == record["new_config"]["strategy_definition"][key]
                    for key in _SAME_FIELDS
                ),
                "replacement_history_new_identity_changed",
            )
            expected_metadata = {**record["new_config"]["metadata"], **_version_metadata(record)}
            _require(
                after.metadata == expected_metadata
                and datetime.fromisoformat(record["committed_at"]).utcoffset() is not None,
                "replacement_history_metadata_changed",
            )
        else:
            expected_metadata = {
                **before.metadata, "replacement_aborted_id": record["replacement_id"]
            }
            if record.get("restore_execution_blocker"):
                expected_metadata["replacement_restore_blocker"] = (
                    record["restore_execution_blocker"]
                )
                _require(after.status == StrategySleeveStatus.PAUSED,
                         "replacement_history_abort_resumed_stale")
            _require(
                after.strategy_config_version == before.strategy_config_version
                and after.metadata == expected_metadata,
                "replacement_history_abort_changed",
            )
        transitions.append(
            {
                "record": record,
                "before": left,
                "after": right,
                "lots_digest": record["transition_lots_digest"],
            }
        )
    return transitions


def replacement_transition_verified(
    storage, *, before_sleeve, after_sleeve, before_lots, after_lots
):
    """Bridge only proved committed/aborted identity edges; no producer or writes."""
    try:
        left, right = _financial_projection(before_sleeve), _financial_projection(after_sleeve)
        _require(
            all(
                left[key] == right[key]
                for key in set(left) - {"strategy_config_version", "metadata"}
            ),
            "replacement_history_economic_change",
        )
        documents = _lot_documents(before_lots)
        _require(documents == _lot_documents(after_lots), "replacement_history_lots_changed")
        digest = _hash(documents)
        edges = _terminal_transitions(storage, before_sleeve.sleeve_id)
        frontier, visited = [_hash(left)], set()
        target = _hash(right)
        while frontier:
            current = frontier.pop()
            if current == target:
                return True
            if current in visited:
                continue
            visited.add(current)
            frontier.extend(
                _hash(edge["after"])
                for edge in edges
                if edge["lots_digest"] == digest and _hash(edge["before"]) == current
            )
        return False
    except (OSError, ValueError, KeyError, TypeError):
        return False


def verified_replacement_history(storage, sleeve):
    """Verified committed version timeline; abort never restarts observation time."""
    try:
        _require(not sleeve.metadata.get(MARKER), "replacement_history_transition_pending")
        if not hasattr(storage, "root_dir"):
            _require(
                not any(
                    sleeve.metadata.get(key)
                    for key in (
                        "replacement_committed_id",
                        "replacement_aborted_id",
                        "version_transition",
                        "current_version_observation_start",
                    )
                ),
                "replacement_history_storage_unavailable",
            )
            return []
        transitions = _terminal_transitions(storage, sleeve.sleeve_id)
        if sleeve.metadata.get("replacement_aborted_id"):
            _require(
                any(
                    edge["record"]["replacement_id"] == sleeve.metadata["replacement_aborted_id"]
                    and edge["record"]["phase"] == "aborted"
                    for edge in transitions
                ),
                "replacement_history_abort_missing",
            )
        commits = {
            edge["record"]["replacement_id"]: edge["record"]
            for edge in transitions
            if edge["record"]["phase"] == "committed"
        }
        current, seen, rows = sleeve.metadata.get("replacement_committed_id"), set(), []
        if current is None:
            _require(
                not commits
                and not sleeve.metadata.get("version_transition")
                and not sleeve.metadata.get("current_version_observation_start"),
                "replacement_history_unproven_metadata",
            )
            return []
        while current:
            _require(
                current in commits and current not in seen, "replacement_history_missing_or_cyclic"
            )
            seen.add(current)
            record = commits[current]
            rows.append(
                {
                    "replacement_id": current,
                    "status": "committed",
                    "from_config_version": record["old_config"]["version"],
                    "to_config_version": record["new_config"]["version"],
                    "from_candidate_id": record["request"]["target_candidate_id"],
                    "to_candidate_id": record["request"]["new_candidate_id"],
                    "effective_at": record["committed_at"],
                }
            )
            current = record["old_sleeve"]["metadata"].get("replacement_committed_id")
        rows.reverse()
        _require(
            len(rows) == len(commits)
            and all(
                first["to_config_version"] == second["from_config_version"]
                and first["effective_at"] <= second["effective_at"]
                for first, second in zip(rows, rows[1:], strict=False)
            ),
            "replacement_history_chain_mismatch",
        )
        _require(
            rows[-1]["to_config_version"] == sleeve.strategy_config_version
            and commits[rows[-1]["replacement_id"]]["new_config"]["strategy_config_id"]
            == sleeve.strategy_config_id
            and rows[-1]["to_candidate_id"] == sleeve.metadata.get("candidate_id")
            and rows[-1]["effective_at"]
            == sleeve.metadata.get("current_version_observation_start"),
            "replacement_history_current_identity_mismatch",
        )
        return rows
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("replacement_history_unverified:" + str(exc)) from exc


def _book_state(book, record):
    old = _candidate(book, record["request"]["target_candidate_id"])
    new = _candidate(book, record["request"]["new_candidate_id"])
    if (old, new) == (record["old_candidate"], record["new_candidate"]):
        return "before"
    _require((old, new) == _after_candidates(record), "replacement_book_cas_changed")
    return "after"


def _hold_failed(settings, record, storage, exc):
    # The prepared write-ahead record also blocks scheduling if PAUSED cannot
    # be persisted (for example a full disk). Never delete it on failure.
    try:
        sleeve = storage.load_sleeve(record["request"]["target_sleeve_id"])
        if sleeve.status not in {StrategySleeveStatus.RUNNING, StrategySleeveStatus.PAUSED}:
            return
        sleeve.status = StrategySleeveStatus.PAUSED
        sleeve.metadata[MARKER] = record["replacement_id"]
        sleeve.paused_at = sleeve.paused_at or _now()
        storage.save_sleeve(sleeve)
    except (OSError, ValueError):
        pass
    try:
        record["error"] = type(exc).__name__ + ":" + str(exc)
        _save_journal(settings, record, "recovery_required")
    except OSError:
        pass


def replace_verified_strategy(
    settings,
    *,
    target_candidate_id,
    target_sleeve_id,
    expected_old_definition_digest,
    expected_old_config_version,
    new_candidate_id,
    expected_new_source_digest,
    expected_admission_sha256,
):
    _paper_only(settings)
    request = dict(
        target_candidate_id=target_candidate_id,
        target_sleeve_id=target_sleeve_id,
        expected_old_definition_digest=expected_old_definition_digest,
        expected_old_config_version=expected_old_config_version,
        new_candidate_id=new_candidate_id,
        expected_new_source_digest=expected_new_source_digest,
        expected_admission_sha256=expected_admission_sha256,
    )
    identity = "replacement-" + _hash(request)[:24]
    if _path(settings, identity).exists():
        return recover_replacement(settings, identity)
    from quant_system.research import admission_v2

    _require(admission_v2.authority_configured(settings) is True, "replacement_authority_disabled")
    _require(target_candidate_id != new_candidate_id, "replacement_same_candidate")
    base = Path(settings.data.data_dir) / "api_runs"
    repo, storage = (
        build_paper_account_repository(base, settings=settings),
        PaperStrategySleeveStorage(base),
    )
    # Warm only from actual owner records. Every identity is independently
    # checked again inside the lock; a changed snapshot cannot reuse this proof.
    try:
        pre_target = inspect_replacement_target(
            settings, candidate_id=target_candidate_id, sleeve_id=target_sleeve_id
        )
        _require(
            pre_target["replacement_target"]["definition_digest"] == expected_old_definition_digest
            and type(expected_old_config_version) is int
            and pre_target["replacement_target"]["config_version"] == expected_old_config_version,
            "replacement_old_version_changed",
        )
        pre_book = assistant_remote.load_book(settings)
        pre_sleeve = storage.load_sleeve(target_sleeve_id)
        pre_config = storage.load_frozen_strategy_config(
            pre_sleeve.strategy_config_id, version=pre_sleeve.strategy_config_version
        )
        pre_new = _candidate(pre_book, new_candidate_id)
        _require(
            pre_new.get("source_digest") == expected_new_source_digest
            and pre_new.get("admission_v2", {}).get("sha256") == expected_admission_sha256,
            "replacement_new_candidate_changed",
        )
        _preflight(
            settings,
            new_candidate=_candidate(pre_book, new_candidate_id),
            target_candidate=_candidate(pre_book, target_candidate_id),
            target_sleeve=pre_sleeve,
            target_config=pre_config,
            book=pre_book,
        )
    except (OSError, ValueError):
        # A concurrent identical operation may have linearized after the first
        # existence check. Join its durable outcome, never start another version.
        if _path(settings, identity).exists():
            return recover_replacement(settings, identity)
        raise
    with _financial_locks(settings, repo, storage, identity):
        if _path(settings, identity).exists():
            return _recover_locked(settings, _load_journal(settings, identity), repo, storage)
        assistant_remote._require_clean_persisted_account_allocation(repo)
        account = repo.load()
        _require(account is not None, "replacement_existing_account_required")
        book = assistant_remote.load_book(settings)
        old, new = _candidate(book, target_candidate_id), _candidate(book, new_candidate_id)
        inspect_replacement_target(
            settings, candidate_id=target_candidate_id, sleeve_id=target_sleeve_id
        )
        sleeve = storage.load_sleeve(target_sleeve_id)
        config = storage.load_frozen_strategy_config(
            sleeve.strategy_config_id, version=sleeve.strategy_config_version
        )
        _require(
            old.get("status") == "hung"
            and old.get("sleeve_id") == target_sleeve_id
            and sleeve.metadata.get("candidate_id") == target_candidate_id
            and _target_status_allows_replacement(storage, sleeve)
            and sleeve.mode == StrategySleeveMode.ALLOCATED
            and not sleeve_replacement_pending(storage, sleeve),
            "replacement_target_not_current",
        )
        _require(
            new.get("status") == "verified"
            and not new.get("sleeve_id")
            and new.get("source_digest") == expected_new_source_digest
            and new.get("admission_v2", {}).get("sha256") == expected_admission_sha256,
            "replacement_new_candidate_changed",
        )
        old_definition = _definition(settings, old, historical=True)
        new_definition = _definition(settings, new)
        require_paper_costs(new_definition, settings)
        _require(
            config.strategy_definition is not None
            and config.strategy_definition == old_definition.model_dump(mode="json"),
            "replacement_requires_frozen_strategy_definition",
        )
        _require(
            old_definition.content_digest == expected_old_definition_digest
            and type(expected_old_config_version) is int
            and config.version == expected_old_config_version,
            "replacement_old_version_changed",
        )
        _require(
            all(
                getattr(old_definition, key) == getattr(new_definition, key) for key in _SAME_FIELDS
            ),
            "replacement_contract_change_unsupported",
        )
        _no_pending(account, storage, sleeve)
        record = {"schema": SCHEMA, "replacement_id": identity, "request": request}
        record["admission"] = _gate(settings, record, new, old, sleeve, config, book)
        latest = storage.load_frozen_strategy_config(config.strategy_config_id)
        _require(latest.version >= config.version, "replacement_config_history_invalid")
        metadata = {
            **sleeve.metadata,
            "candidate_id": new_candidate_id,
            "source_digest": expected_new_source_digest,
            "candidate_code_digest": expected_new_source_digest,
            "factor_id": new["factor_id"],
            "artifact_id": new.get("artifact_id") or new_candidate_id,
            "artifact_code_path": str(Path(new["source_path"]).resolve()),
            "definition_digest": new_definition.content_digest,
            "comparison_digest": new.get("comparison_digest"),
            "replacement_committed_id": identity,
            "replaces_candidate_id": target_candidate_id,
        }
        for key in (
            "version_transition",
            "current_version_observation_start",
            "current_version_performance",
            "performance_scope",
            "replacement_restore_blocker",
        ):
            metadata.pop(key, None)
        next_config = latest.new_version(
            name=new_definition.title,
            universe_id="remote:" + new_candidate_id,
            metadata=metadata,
            **definition_config_fields(new_definition),
        )
        record.update(
            old_candidate=copy.deepcopy(old),
            new_candidate=copy.deepcopy(new),
            old_sleeve=sleeve.model_dump(mode="json"),
            old_config=config.model_dump(mode="json"),
            latest_config_before=latest.model_dump(mode="json"),
            new_config=next_config.model_dump(mode="json"),
            economic=_economic_snapshot(account, storage, sleeve),
            phase="prepared",
            transition_lots=_lot_documents(storage.load_sleeve_lots(sleeve.sleeve_id)),
        )
        record["transition_lots_digest"] = _hash(record["transition_lots"])
        _save_journal(settings, record, "prepared")
        try:
            return _complete_locked(settings, record, repo, storage)
        except Exception as exc:
            _hold_failed(settings, record, storage, exc)
            raise


def _complete_locked(settings, record, repo, storage):
    request = record["request"]
    sleeve = storage.load_sleeve(request["target_sleeve_id"])
    sleeve.status = StrategySleeveStatus.PAUSED
    sleeve.paused_at = _now()
    sleeve.metadata[MARKER] = record["replacement_id"]
    storage.save_sleeve(sleeve)
    _save_journal(settings, record, "paused")
    next_config = StrategyConfig.model_validate(record["new_config"])
    storage.save_strategy_config(next_config)
    _save_journal(settings, record, "config_saved")
    book = assistant_remote.load_book(settings)
    _book_state(book, record)
    old, new = (
        _candidate(book, request["target_candidate_id"]),
        _candidate(book, request["new_candidate_id"]),
    )
    after_old, after_new = _after_candidates(record)
    old.clear()
    old.update(after_old)
    new.clear()
    new.update(after_new)
    assistant_remote.save_book(settings, book)
    _save_journal(settings, record, "book_bound")
    _require(
        _economic_snapshot(repo.load(), storage, sleeve) == record["economic"],
        "replacement_economics_changed",
    )
    sleeve.strategy_config_version = next_config.version
    sleeve.metadata = dict(next_config.metadata)
    sleeve.status = StrategySleeveStatus.RUNNING
    sleeve.paused_at = None
    record["committed_at"] = _now()
    sleeve.updated_at = record["committed_at"]
    sleeve.metadata.update(_version_metadata(record))
    record["new_sleeve"] = sleeve.model_dump(mode="json")
    _save_journal(settings, record, "ready_to_resume")
    storage.save_sleeve(sleeve)
    _save_journal(settings, record, "committed")
    return _result(record)


def _recover_locked(settings, record, repo, storage, action="complete", *, prepare_only=False):
    request = record["request"]
    sleeve = storage.load_sleeve(request["target_sleeve_id"])
    book = assistant_remote.load_book(settings)
    try:
        state = _book_state(book, record)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Neither bound book row matches; leave the durable diagnosis of the
        # refused recovery instead of an unexplained failure.
        _hold_failed(settings, record, storage, exc)
        raise
    physical_abort = (
        state == "before"
        and sleeve.strategy_config_version == record["old_config"]["version"]
        and sleeve.metadata.get("replacement_aborted_id") == record["replacement_id"]
        and not sleeve.metadata.get(MARKER)
    )
    if record["phase"] == "aborted" or physical_abort:
        _require(physical_abort, "replacement_aborted_state_changed")
        if record["phase"] != "aborted":
            _save_journal(settings, record, "aborted")
        return _result(record)
    physical_commit = (
        state == "after"
        and sleeve.strategy_config_version == record["new_config"]["version"]
        and sleeve.metadata.get("replacement_committed_id") == record["replacement_id"]
        and not sleeve.metadata.get(MARKER)
    )
    if record["phase"] == "committed" or physical_commit:
        _require(physical_commit, "replacement_committed_state_changed")
        if record["phase"] != "committed":
            _save_journal(settings, record, "committed")
        return _result(record)
    try:
        assistant_remote._require_clean_persisted_account_allocation(repo)
        account = repo.load()
        _require(account is not None, "replacement_existing_account_required")
        _require(
            sleeve.status in {StrategySleeveStatus.RUNNING, StrategySleeveStatus.PAUSED},
            "replacement_target_stopped",
        )
        _require(
            sleeve.strategy_config_id == record["old_config"]["strategy_config_id"]
            and sleeve.strategy_config_version
            in {record["old_config"]["version"], record["new_config"]["version"]}
            and sleeve.metadata.get(MARKER) in {None, record["replacement_id"]},
            "replacement_sleeve_cas_changed",
        )
        _require(
            _economic_snapshot(account, storage, sleeve) == record["economic"],
            "replacement_economics_changed",
        )
        _no_pending(account, storage, sleeve)
        old_config = storage.load_frozen_strategy_config(
            sleeve.strategy_config_id, version=record["old_config"]["version"]
        )
        _require(
            old_config.model_dump(mode="json") == record["old_config"],
            "replacement_old_config_changed",
        )
        latest = storage.load_frozen_strategy_config(sleeve.strategy_config_id)
        _require(
            latest.model_dump(mode="json")
            in [record["latest_config_before"], record["new_config"]],
            "replacement_config_history_changed",
        )
        old_definition = _definition(settings, record["old_candidate"], historical=True)
        new_definition = _definition(
            settings, record["new_candidate"], historical=action == "abort"
        )
        _require(
            old_definition.content_digest == request["expected_old_definition_digest"]
            and old_config.strategy_definition == old_definition.model_dump(mode="json")
            and record["old_sleeve"]["strategy_config_id"] == old_config.strategy_config_id
            and record["old_sleeve"]["strategy_config_version"] == old_config.version
            and old_config.version == request["expected_old_config_version"]
            and record["new_candidate"]["source_digest"] == request["expected_new_source_digest"]
            and record["new_candidate"].get("admission_v2", {}).get("sha256")
            == request["expected_admission_sha256"]
            and new_definition.model_dump(mode="json")
            == record["new_config"]["strategy_definition"],
            "replacement_definition_changed",
        )
        current_sleeve = sleeve.model_dump(mode="json")
        expected_sleeve = copy.deepcopy(record["old_sleeve"])
        if sleeve.strategy_config_version == record["new_config"]["version"]:
            if record.get("new_sleeve"):
                expected_sleeve = copy.deepcopy(record["new_sleeve"])
            else:
                expected_sleeve["strategy_config_version"] = sleeve.strategy_config_version
                expected_sleeve["metadata"] = copy.deepcopy(record["new_config"]["metadata"])
        for value in (current_sleeve, expected_sleeve):
            for key in ("status", "updated_at", "paused_at"):
                value.pop(key, None)
            value["metadata"].pop(MARKER, None)
            if value["metadata"].get("replacement_aborted_id") == record["replacement_id"]:
                prior_abort = record["old_sleeve"]["metadata"].get("replacement_aborted_id")
                if prior_abort is None:
                    value["metadata"].pop("replacement_aborted_id")
                else:
                    value["metadata"]["replacement_aborted_id"] = prior_abort
        _require(current_sleeve == expected_sleeve, "replacement_sleeve_cas_changed")
        _require(
            record.get("recovery_action") != "abort" or action == "abort",
            "replacement_abort_in_progress",
        )
        # Only the two physically proven before/after rows are projected back
        # for the fixed verifier. Other peers remain the CURRENT owner book.
        before_book = copy.deepcopy(book)
        before_book["candidates"] = [
            copy.deepcopy(record["old_candidate"])
            if row.get("candidate_id") == request["target_candidate_id"]
            else copy.deepcopy(record["new_candidate"])
            if row.get("candidate_id") == request["new_candidate_id"]
            else row
            for row in before_book["candidates"]
        ]
        if action == "abort":
            _require(
                observe_paper_emergency_stop(
                    settings, workspace_id=str(sleeve.metadata.get("workspace_id", "default"))
                ).get("active")
                is False,
                "replacement_emergency_or_authority_unavailable",
            )
            record["recovery_action"] = "abort"
            _save_journal(settings, record, "aborting")
            assistant_remote.save_book(settings, before_book)
            restored = StrategySleeve.model_validate(record["old_sleeve"])
            # Restoring ownership is not permission to resume obsolete code.
            try:
                validate_definition(old_definition)
            except ValueError as exc:
                restored.status = StrategySleeveStatus.PAUSED
                restored.paused_at = _now()
                restored.metadata["replacement_restore_blocker"] = str(exc)
                record["restore_execution_blocker"] = str(exc)
            restored.metadata["replacement_aborted_id"] = record["replacement_id"]
            restored.updated_at = _now()
            record["restored_sleeve"] = restored.model_dump(mode="json")
            record["aborted_at"] = restored.updated_at
            _save_journal(settings, record, "ready_to_abort")
            storage.save_sleeve(restored)
            _save_journal(settings, record, "aborted")
            return _result(record)
        require_paper_costs(new_definition, settings)
        if state == "after":
            # Restore only the two proven rows while the sleeve remains frozen.
            # The fixed data verifier reads the actual owner book, not a caller
            # supplied peer snapshot. A failed recheck leaves this original
            # binding PAUSED, never a silently re-authorized new version.
            assistant_remote.save_book(settings, before_book)
            _save_journal(settings, record, "binding_restored_for_recheck")
        # The immutable new config remains in history, but a cold recheck sees
        # the exact original PAUSED pointer and owner-book rows, not a mixture.
        sleeve = _old_target_view(record)
        sleeve.paused_at = _now()
        storage.save_sleeve(sleeve)
        if prepare_only:
            sleeve.status = StrategySleeveStatus.PAUSED
            sleeve.metadata[MARKER] = record["replacement_id"]
            sleeve.paused_at = sleeve.paused_at or _now()
            storage.save_sleeve(sleeve)
            _save_journal(settings, record, "needs_preflight")
            return {
                "pending_preflight": True,
                "new_candidate": copy.deepcopy(record["new_candidate"]),
                "target_candidate": copy.deepcopy(record["old_candidate"]),
                "target_sleeve": _old_target_view(record),
                "target_config": old_config,
                "book": before_book,
            }
        _gate(
            settings,
            record,
            record["new_candidate"],
            record["old_candidate"],
            _old_target_view(record),
            old_config,
            before_book,
        )
        return _complete_locked(settings, record, repo, storage)
    except Exception as exc:
        _hold_failed(settings, record, storage, exc)
        raise


def recover_replacement(settings, replacement_id, *, action="complete"):
    _paper_only(settings)
    _require(action in {"complete", "abort"}, "replacement_recovery_action_invalid")
    _load_journal(settings, replacement_id)
    base = Path(settings.data.data_dir) / "api_runs"
    repo, storage = (
        build_paper_account_repository(base, settings=settings),
        PaperStrategySleeveStorage(base),
    )
    with _financial_locks(settings, repo, storage, replacement_id):
        prepared = _recover_locked(
            settings,
            _load_journal(settings, replacement_id),
            repo,
            storage,
            action,
            prepare_only=action == "complete",
        )
    if not prepared.get("pending_preflight"):
        return prepared
    try:
        _preflight(settings, **{k: v for k, v in prepared.items() if k != "pending_preflight"})
    except Exception as exc:
        with _financial_locks(settings, repo, storage, replacement_id):
            record = _load_journal(settings, replacement_id)
            if record["phase"] not in {"committed", "aborted"}:
                record["error"] = "preflight:" + type(exc).__name__ + ":" + str(exc)
                _save_journal(settings, record, "needs_preflight")
        raise
    with _financial_locks(settings, repo, storage, replacement_id):
        return _recover_locked(
            settings, _load_journal(settings, replacement_id), repo, storage, action
        )
