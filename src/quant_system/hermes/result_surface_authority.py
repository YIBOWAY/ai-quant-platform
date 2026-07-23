"""V7f-Typed-Results-M1: hermetic typed result surface authority.

In-process store for workspace-scoped typed result projections used by the
AgentWorkspace snapshot/follow spine. Empty is honest. Never invents Task /
Attempt / Run / Gate / command-approval rows. Not live Futu / HQA final
authority — hermetic fixture class matching V7a–V7e.

M1 scope:
* seed typed results (including vertical-A options + vertical-B factor sample fields)
* sample vs real marking
* exact Task/Attempt/Run/artifact/command link fields when known
* list_observed for projector
* no public write path; no always-allow; no Gate expansion
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Literal

ResultSampleMark = Literal["sample", "real"]
ResultKind = Literal[
    "options_vertical_a",
    "backtest",
    "factor",
    "paper",
    "replication",
    "experiment",
    "factor_candidate",
    "generic",
]
ResultFreshness = Literal["fresh", "stale", "not_applicable", "unknown"]
ResultReadStatus = Literal[
    "available",
    "degraded",
    "missing",
    "corrupt",
    "unavailable",
]

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_PUBLIC_KINDS = frozenset(
    {
        "options_vertical_a",
        "backtest",
        "factor",
        "paper",
        "replication",
        "experiment",
        "factor_candidate",
        "generic",
    }
)
_PUBLIC_MARKS = frozenset({"sample", "real"})
_PUBLIC_FRESHNESS = frozenset({"fresh", "stale", "not_applicable", "unknown"})
_PUBLIC_READ = frozenset(
    {"available", "degraded", "missing", "corrupt", "unavailable"}
)


class ResultSurfaceAuthorityError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _dt_public(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if type(value) is str and value:
        return value
    return None


def _validate_id(value: str, field: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ResultSurfaceAuthorityError(
            "validation", f"{field} must be a bounded identifier"
        )
    return value


def _optional_id(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    return _validate_id(value, field)


def _optional_digest(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ResultSurfaceAuthorityError(
            "validation", f"{field} must be lowercase SHA-256 hex"
        )
    return value


def _bounded_text(
    value: str | None, field: str, *, max_len: int, required: bool = False
) -> str | None:
    if value is None:
        if required:
            raise ResultSurfaceAuthorityError(
                "validation", f"{field} is required"
            )
        return None
    if type(value) is not str or not value.strip() or len(value) > max_len:
        raise ResultSurfaceAuthorityError(
            "validation", f"{field} must be bounded nonempty text"
        )
    # Allow printable + common whitespace for notes/limitations.
    cleaned = value.strip()
    if any(ord(ch) < 9 or (13 < ord(ch) < 32) for ch in cleaned):
        raise ResultSurfaceAuthorityError(
            "validation", f"{field} contains control characters"
        )
    return cleaned


def _bounded_str_list(
    values: list[str] | tuple[str, ...] | None, field: str, *, max_items: int = 32
) -> tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, (list, tuple)):
        raise ResultSurfaceAuthorityError(
            "validation", f"{field} must be a list of strings"
        )
    if len(values) > max_items:
        raise ResultSurfaceAuthorityError(
            "validation", f"{field} exceeds max {max_items} items"
        )
    out: list[str] = []
    for item in values:
        text = _bounded_text(item, field, max_len=256, required=True)
        assert text is not None
        out.append(text)
    return tuple(out)


def _optional_number(value: Any, field: str) -> float | int | None:
    if value is None:
        return None
    if type(value) is bool:
        raise ResultSurfaceAuthorityError(
            "validation", f"{field} must be a number"
        )
    if type(value) is int:
        return value
    if type(value) is float:
        if value != value or value in (float("inf"), float("-inf")):
            raise ResultSurfaceAuthorityError(
                "validation", f"{field} must be a finite number"
            )
        return value
    raise ResultSurfaceAuthorityError("validation", f"{field} must be a number")


@dataclass
class TypedResultRecord:
    workspace_id: str
    result_id: str
    kind: str
    display_title: str
    status: str
    sample_or_real: ResultSampleMark
    freshness: ResultFreshness
    read_status: ResultReadStatus
    occurred_at: str
    summary: str | None = None
    # Exact authority links (optional; never invent when absent).
    task_id: str | None = None
    attempt_id: str | None = None
    run_id: str | None = None
    artifact_id: str | None = None
    command_id: str | None = None
    # Vertical A options fields (optional; present for options_vertical_a).
    ticker: str | None = None
    expiry: str | None = None
    strike: float | int | None = None
    bid: float | int | None = None
    ask: float | int | None = None
    delta: float | int | None = None
    iv: float | int | None = None
    apr: float | int | None = None
    # Vertical B factor fields (optional; present for kind=factor).
    factor_name: str | None = None
    paper_ref: str | None = None
    formula_sketch: str | None = None
    universe_note: str | None = None
    ic_mean: float | int | None = None
    sample_window: str | None = None
    # Evidence / honesty fields.
    provider_evidence: tuple[str, ...] = ()
    filters: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    detail_href: str | None = None
    original_href: str | None = None
    source: str | None = None
    authority: str | None = None
    payload_digest: str | None = None
    extra: dict[str, object] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "result_id": self.result_id,
            "id": self.result_id,  # spine asIdList / authority panel id slot
            "kind": self.kind,
            "display_title": self.display_title,
            "status": self.status,
            "sample_or_real": self.sample_or_real,
            "freshness": self.freshness,
            "read_status": self.read_status,
            "occurred_at": self.occurred_at,
        }
        if self.summary is not None:
            payload["summary"] = self.summary
        for key, value in (
            ("task_id", self.task_id),
            ("attempt_id", self.attempt_id),
            ("run_id", self.run_id),
            ("artifact_id", self.artifact_id),
            ("command_id", self.command_id),
            ("ticker", self.ticker),
            ("expiry", self.expiry),
            ("strike", self.strike),
            ("bid", self.bid),
            ("ask", self.ask),
            ("delta", self.delta),
            ("iv", self.iv),
            ("apr", self.apr),
            ("factor_name", self.factor_name),
            ("paper_ref", self.paper_ref),
            ("formula_sketch", self.formula_sketch),
            ("universe_note", self.universe_note),
            ("ic_mean", self.ic_mean),
            ("sample_window", self.sample_window),
            ("detail_href", self.detail_href),
            ("original_href", self.original_href),
            ("source", self.source),
            ("authority", self.authority),
            ("payload_digest", self.payload_digest),
        ):
            if value is not None:
                payload[key] = value
        if self.provider_evidence:
            payload["provider_evidence"] = list(self.provider_evidence)
        if self.filters:
            payload["filters"] = list(self.filters)
        if self.exclusions:
            payload["exclusions"] = list(self.exclusions)
        if self.limitations:
            payload["limitations"] = list(self.limitations)
        # Explicit exact-link block for FE presenter (never invent missing keys).
        links: dict[str, object] = {}
        if self.task_id is not None:
            links["task_id"] = self.task_id
            links["task_ref"] = f"task:{self.task_id}"
        if self.attempt_id is not None:
            links["attempt_id"] = self.attempt_id
            links["attempt_ref"] = f"attempt:{self.attempt_id}"
        if self.run_id is not None:
            links["run_id"] = self.run_id
            links["run_ref"] = f"run:{self.run_id}"
        if self.artifact_id is not None:
            links["artifact_id"] = self.artifact_id
            links["artifact_ref"] = f"artifact:{self.artifact_id}"
        if self.command_id is not None:
            links["command_id"] = self.command_id
        if links:
            payload["exact_links"] = links
        return payload


class ResultSurfaceAuthority:
    """Thread-safe in-process typed result store (hermetic + local-dark)."""

    def __init__(self) -> None:
        self._lock = Lock()
        # key = (workspace_id, result_id)
        self._rows: dict[tuple[str, str], TypedResultRecord] = {}

    def reset(self) -> None:
        with self._lock:
            self._rows.clear()

    def seed_result(
        self,
        *,
        workspace_id: str,
        result_id: str,
        kind: str,
        display_title: str,
        status: str = "ready",
        sample_or_real: str = "sample",
        freshness: str = "unknown",
        read_status: str = "available",
        occurred_at: str | datetime | None = None,
        summary: str | None = None,
        task_id: str | None = None,
        attempt_id: str | None = None,
        run_id: str | None = None,
        artifact_id: str | None = None,
        command_id: str | None = None,
        ticker: str | None = None,
        expiry: str | None = None,
        strike: float | int | None = None,
        bid: float | int | None = None,
        ask: float | int | None = None,
        delta: float | int | None = None,
        iv: float | int | None = None,
        apr: float | int | None = None,
        factor_name: str | None = None,
        paper_ref: str | None = None,
        formula_sketch: str | None = None,
        universe_note: str | None = None,
        ic_mean: float | int | None = None,
        sample_window: str | None = None,
        provider_evidence: list[str] | tuple[str, ...] | None = None,
        filters: list[str] | tuple[str, ...] | None = None,
        exclusions: list[str] | tuple[str, ...] | None = None,
        limitations: list[str] | tuple[str, ...] | None = None,
        detail_href: str | None = None,
        original_href: str | None = None,
        source: str | None = None,
        authority: str | None = None,
        payload_digest: str | None = None,
    ) -> TypedResultRecord:
        ws = _validate_id(workspace_id, "workspace_id")
        rid = _validate_id(result_id, "result_id")
        if kind not in _PUBLIC_KINDS:
            raise ResultSurfaceAuthorityError(
                "validation", f"kind must be one of {sorted(_PUBLIC_KINDS)}"
            )
        if sample_or_real not in _PUBLIC_MARKS:
            raise ResultSurfaceAuthorityError(
                "validation", "sample_or_real must be sample|real"
            )
        if freshness not in _PUBLIC_FRESHNESS:
            raise ResultSurfaceAuthorityError(
                "validation", "freshness must be a known token"
            )
        if read_status not in _PUBLIC_READ:
            raise ResultSurfaceAuthorityError(
                "validation", "read_status must be a known token"
            )
        title = _bounded_text(display_title, "display_title", max_len=256, required=True)
        assert title is not None
        status_s = _bounded_text(status, "status", max_len=128, required=True)
        assert status_s is not None
        ts = _dt_public(occurred_at) or _utc_now().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        row = TypedResultRecord(
            workspace_id=ws,
            result_id=rid,
            kind=kind,
            display_title=title,
            status=status_s,
            sample_or_real=sample_or_real,  # type: ignore[arg-type]
            freshness=freshness,  # type: ignore[arg-type]
            read_status=read_status,  # type: ignore[arg-type]
            occurred_at=ts,
            summary=_bounded_text(summary, "summary", max_len=1000),
            task_id=_optional_id(task_id, "task_id"),
            attempt_id=_optional_id(attempt_id, "attempt_id"),
            run_id=_optional_id(run_id, "run_id"),
            artifact_id=_optional_id(artifact_id, "artifact_id"),
            command_id=_optional_id(command_id, "command_id"),
            ticker=_bounded_text(ticker, "ticker", max_len=32),
            expiry=_bounded_text(expiry, "expiry", max_len=32),
            strike=_optional_number(strike, "strike"),
            bid=_optional_number(bid, "bid"),
            ask=_optional_number(ask, "ask"),
            delta=_optional_number(delta, "delta"),
            iv=_optional_number(iv, "iv"),
            apr=_optional_number(apr, "apr"),
            factor_name=_bounded_text(factor_name, "factor_name", max_len=64),
            paper_ref=_bounded_text(paper_ref, "paper_ref", max_len=256),
            formula_sketch=_bounded_text(formula_sketch, "formula_sketch", max_len=1000),
            universe_note=_bounded_text(universe_note, "universe_note", max_len=256),
            ic_mean=_optional_number(ic_mean, "ic_mean"),
            sample_window=_bounded_text(sample_window, "sample_window", max_len=128),
            provider_evidence=_bounded_str_list(provider_evidence, "provider_evidence"),
            filters=_bounded_str_list(filters, "filters"),
            exclusions=_bounded_str_list(exclusions, "exclusions"),
            limitations=_bounded_str_list(limitations, "limitations"),
            detail_href=_bounded_text(detail_href, "detail_href", max_len=1000),
            original_href=_bounded_text(original_href, "original_href", max_len=1000),
            source=_bounded_text(source, "source", max_len=128),
            authority=_bounded_text(authority, "authority", max_len=128),
            payload_digest=_optional_digest(payload_digest, "payload_digest"),
        )
        with self._lock:
            self._rows[(ws, rid)] = row
        return row

    def seed_options_vertical_a_sample(
        self,
        *,
        workspace_id: str,
        result_id: str,
        ticker: str,
        expiry: str,
        strike: float | int,
        bid: float | int,
        ask: float | int,
        delta: float | int,
        iv: float | int,
        apr: float | int,
        display_title: str | None = None,
        task_id: str | None = None,
        attempt_id: str | None = None,
        run_id: str | None = None,
        artifact_id: str | None = None,
        command_id: str | None = None,
        provider_evidence: list[str] | tuple[str, ...] | None = None,
        filters: list[str] | tuple[str, ...] | None = None,
        exclusions: list[str] | tuple[str, ...] | None = None,
        limitations: list[str] | tuple[str, ...] | None = None,
        freshness: str = "fresh",
        sample_or_real: str = "sample",
    ) -> TypedResultRecord:
        """Convenience seeder for Plan vertical A typed options fields.

        This helper is hermetic-fixture oriented: default limitations claim
        not_live_futu_quote. Callers that pass sample_or_real="real" without
        replacing limitations are coerced back to sample (honesty).
        """
        title = display_title or f"{ticker} {expiry} {strike} options"
        default_limitations = limitations or (
            "hermetic_fixture",
            "not_live_futu_quote",
            "not_tradeable",
        )
        # Honesty: hermetic/not_live limitations cannot wear a REAL badge.
        mark = sample_or_real
        lim_set = {str(x) for x in default_limitations}
        if mark == "real" and (
            "hermetic_fixture" in lim_set or "not_live_futu_quote" in lim_set
        ):
            mark = "sample"
        default_evidence = provider_evidence or ("hermetic_seed",)
        return self.seed_result(
            workspace_id=workspace_id,
            result_id=result_id,
            kind="options_vertical_a",
            display_title=title,
            status="ready",
            sample_or_real=mark,
            freshness=freshness,
            read_status="available",
            summary=f"{ticker} covered-call style options projection ({sample_or_real})",
            task_id=task_id,
            attempt_id=attempt_id,
            run_id=run_id,
            artifact_id=artifact_id,
            command_id=command_id,
            ticker=ticker,
            expiry=expiry,
            strike=strike,
            bid=bid,
            ask=ask,
            delta=delta,
            iv=iv,
            apr=apr,
            provider_evidence=default_evidence,
            filters=filters or ("delta_band", "dte_window"),
            exclusions=exclusions or ("earnings_week",),
            limitations=default_limitations,
            source="hermetic_result_surface",
            authority="hermetic_result_surface_authority",
        )

    def seed_factor_vertical_b_sample(
        self,
        *,
        workspace_id: str,
        result_id: str,
        factor_name: str,
        paper_ref: str,
        paper_digest: str,
        formula_sketch: str,
        universe_note: str,
        display_title: str | None = None,
        summary: str | None = None,
        status: str = "completed",
        task_id: str | None = None,
        attempt_id: str | None = None,
        run_id: str | None = None,
        provider_evidence: list[str] | tuple[str, ...] | None = None,
        filters: list[str] | tuple[str, ...] | None = None,
        exclusions: list[str] | tuple[str, ...] | None = None,
        limitations: list[str] | tuple[str, ...] | None = None,
        freshness: str = "fresh",
        read_status: str = "available",
        sample_or_real: str = "sample",
        ic_mean: float | int | None = 0.0,
        sample_window: str | None = "hermetic_fixture_window",
        source: str = "hermetic_vertical_b_binding",
        authority: str = "vertical_binding_authority",
    ) -> TypedResultRecord:
        """Convenience seeder for V7g-B-M1 typed factor fields.

        Hermetic-only: default limitations lock cascade + live backtest.
        sample_or_real="real" with hermetic/not_live_backtest limitations is
        coerced back to sample (honesty).
        """
        title = display_title or f"{factor_name} factor research ({status})"
        default_limitations = limitations or (
            "hermetic_fixture",
            "not_live_backtest",
            "not_tradeable",
            "zero_orders",
            "plan_confirm_required",
            "gate_cascade_locked",
            "not_git_commit",
        )
        # B-M1 hermetic-only seeder: never emit real, even if caller strips
        # limitations or passes sample_or_real="real".
        mark = "sample"
        if sample_or_real == "real":
            # Keep limitations honesty trail if caller tried real.
            default_limitations = tuple(
                dict.fromkeys(list(default_limitations) + ["honesty_coercion"])
            )
        default_evidence = provider_evidence
        if default_evidence is None:
            default_evidence = ("hermetic_factor_fixture", "hermetic_paper_ref")
        return self.seed_result(
            workspace_id=workspace_id,
            result_id=result_id,
            kind="factor",
            display_title=title,
            status=status,
            sample_or_real=mark,
            freshness=freshness,
            read_status=read_status,
            summary=summary or f"{factor_name} hermetic factor binding",
            task_id=task_id,
            attempt_id=attempt_id,
            run_id=run_id,
            factor_name=factor_name,
            paper_ref=paper_ref,
            formula_sketch=formula_sketch,
            universe_note=universe_note,
            ic_mean=ic_mean,
            sample_window=sample_window,
            provider_evidence=default_evidence,
            filters=filters or ("hermetic_factor_fixture", "plan_only_binding"),
            exclusions=exclusions or ("live_backtest", "gate_cascade", "git_commit"),
            limitations=default_limitations,
            source=source,
            authority=authority,
            payload_digest=paper_digest,
        )

    def seed_factor_vertical_b_plan_confirm_sample(
        self,
        *,
        workspace_id: str,
        result_id: str,
        factor_name: str,
        paper_ref: str,
        paper_digest: str,
        plan_digest: str,
        formula_sketch: str,
        universe_note: str,
        display_title: str | None = None,
        summary: str | None = None,
        status: str = "completed",
        task_id: str | None = None,
        attempt_id: str | None = None,
        run_id: str | None = None,
        provider_evidence: list[str] | tuple[str, ...] | None = None,
        filters: list[str] | tuple[str, ...] | None = None,
        exclusions: list[str] | tuple[str, ...] | None = None,
        limitations: list[str] | tuple[str, ...] | None = None,
        freshness: str = "fresh",
        read_status: str = "available",
        sample_or_real: str = "sample",
        ic_mean: float | int | None = None,
        sample_window: str | None = None,
        source: str = "hermetic_vertical_b_plan_confirm",
        authority: str = "vertical_binding_authority",
    ) -> TypedResultRecord:
        """V7g-B-M2 plan-confirm seeder.

        Always sample. payload_digest is the plan identity (plan_digest).
        Default limitations include plan_confirmed + gate_cascade_locked and
        exclude plan_confirm_required.
        """
        title = display_title or f"{factor_name} factor plan confirmed"
        default_limitations = limitations or (
            "hermetic_fixture",
            "not_live_backtest",
            "not_tradeable",
            "zero_orders",
            "plan_confirmed",
            "gate_cascade_locked",
            "not_git_commit",
        )
        # Never emit real from hermetic plan-confirm seeder.
        mark = "sample"
        if sample_or_real == "real":
            default_limitations = tuple(
                dict.fromkeys(list(default_limitations) + ["honesty_coercion"])
            )
        # Defense: strip plan_confirm_required if a caller smuggled it;
        # force honesty markers even if custom limitations are passed.
        default_limitations = tuple(
            x for x in default_limitations if x != "plan_confirm_required"
        )
        for required in (
            "plan_confirmed",
            "gate_cascade_locked",
            "zero_orders",
            "not_live_backtest",
            "not_tradeable",
            "not_git_commit",
            "hermetic_fixture",
        ):
            if required not in default_limitations:
                default_limitations = tuple(list(default_limitations) + [required])
        # paper_digest retained as API continuity (bind identity); payload_digest
        # is the plan identity per freeze — paper stays on task/bind result.
        _ = paper_digest
        default_evidence = provider_evidence
        if default_evidence is None:
            default_evidence = ("hermetic_factor_fixture", "hermetic_plan_confirm")
        return self.seed_result(
            workspace_id=workspace_id,
            result_id=result_id,
            kind="factor",
            display_title=title,
            status=status,
            sample_or_real=mark,
            freshness=freshness,
            read_status=read_status,
            summary=summary or f"{factor_name} hermetic factor plan confirm",
            task_id=task_id,
            attempt_id=attempt_id,
            run_id=run_id,
            factor_name=factor_name,
            paper_ref=paper_ref,
            formula_sketch=formula_sketch,
            universe_note=universe_note,
            ic_mean=ic_mean,
            sample_window=sample_window,
            provider_evidence=default_evidence,
            filters=filters
            or ("hermetic_factor_fixture", "plan_confirmed"),
            exclusions=exclusions
            or (
                "live_backtest",
                "gate_cascade",
                "git_commit",
                "start_research",
            ),
            limitations=default_limitations,
            source=source,
            authority=authority,
            payload_digest=plan_digest,
        )

    def seed_factor_vertical_b_gate1_seed_sample(
        self,
        *,
        workspace_id: str,
        result_id: str,
        factor_name: str,
        paper_ref: str,
        paper_digest: str,
        reviewed_source_sha256: str,
        formula_sketch: str,
        universe_note: str,
        display_title: str | None = None,
        summary: str | None = None,
        status: str = "completed",
        task_id: str | None = None,
        attempt_id: str | None = None,
        run_id: str | None = None,
        provider_evidence: list[str] | tuple[str, ...] | None = None,
        filters: list[str] | tuple[str, ...] | None = None,
        exclusions: list[str] | tuple[str, ...] | None = None,
        limitations: list[str] | tuple[str, ...] | None = None,
        freshness: str = "fresh",
        read_status: str = "available",
        sample_or_real: str = "sample",
        ic_mean: float | int | None = None,
        sample_window: str | None = None,
        source: str = "hermetic_vertical_b_gate1_seed",
        authority: str = "vertical_binding_authority",
    ) -> TypedResultRecord:
        """V7g-B-M3 Gate1-seed seeder.

        Always sample. payload_digest is the formula-source identity
        (reviewed_source_sha256). Default limitations include gate1_seeded +
        gate_cascade_locked and exclude plan_confirm_required.
        """
        title = display_title or f"{factor_name} factor Gate1 seeded"
        default_limitations = limitations or (
            "hermetic_fixture",
            "not_live_backtest",
            "not_tradeable",
            "zero_orders",
            "plan_confirmed",
            "gate1_seeded",
            "gate_cascade_locked",
            "not_git_commit",
        )
        mark = "sample"
        if sample_or_real == "real":
            default_limitations = tuple(
                dict.fromkeys(list(default_limitations) + ["honesty_coercion"])
            )
        default_limitations = tuple(
            x for x in default_limitations if x != "plan_confirm_required"
        )
        for required in (
            "plan_confirmed",
            "gate1_seeded",
            "gate_cascade_locked",
            "zero_orders",
            "not_live_backtest",
            "not_tradeable",
            "not_git_commit",
            "hermetic_fixture",
        ):
            if required not in default_limitations:
                default_limitations = tuple(list(default_limitations) + [required])
        # paper_digest retained for API continuity; payload is formula-source.
        _ = paper_digest
        default_evidence = provider_evidence
        if default_evidence is None:
            default_evidence = ("hermetic_factor_fixture", "hermetic_gate1_seed")
        return self.seed_result(
            workspace_id=workspace_id,
            result_id=result_id,
            kind="factor",
            display_title=title,
            status=status,
            sample_or_real=mark,
            freshness=freshness,
            read_status=read_status,
            summary=summary or f"{factor_name} hermetic factor Gate1 seed",
            task_id=task_id,
            attempt_id=attempt_id,
            run_id=run_id,
            factor_name=factor_name,
            paper_ref=paper_ref,
            formula_sketch=formula_sketch,
            universe_note=universe_note,
            ic_mean=ic_mean,
            sample_window=sample_window,
            provider_evidence=default_evidence,
            filters=filters
            or ("hermetic_factor_fixture", "gate1_seeded"),
            exclusions=exclusions
            or (
                "live_backtest",
                "gate_cascade_decide",
                "git_commit",
                "start_research",
                "orders",
            ),
            limitations=default_limitations,
            source=source,
            authority=authority,
            payload_digest=reviewed_source_sha256,
        )

    def seed_factor_vertical_b_gate1_confirm_sample(
        self,
        *,
        workspace_id: str,
        result_id: str,
        factor_name: str,
        paper_ref: str,
        paper_digest: str,
        reviewed_source_sha256: str,
        formula_sketch: str,
        universe_note: str,
        display_title: str | None = None,
        summary: str | None = None,
        status: str = "completed",
        task_id: str | None = None,
        attempt_id: str | None = None,
        run_id: str | None = None,
        provider_evidence: list[str] | tuple[str, ...] | None = None,
        filters: list[str] | tuple[str, ...] | None = None,
        exclusions: list[str] | tuple[str, ...] | None = None,
        limitations: list[str] | tuple[str, ...] | None = None,
        freshness: str = "fresh",
        read_status: str = "available",
        sample_or_real: str = "sample",
        ic_mean: float | int | None = None,
        sample_window: str | None = None,
        source: str = "hermetic_vertical_b_gate1_confirm",
        authority: str = "vertical_binding_authority",
    ) -> TypedResultRecord:
        """V7g-B-M4 Gate1-confirm seeder.

        Always sample. payload_digest is the formula-source identity.
        Default limitations include gate1_confirmed + gate_cascade_locked
        (umbrella lock retained) and historical gate1_seeded / plan_confirmed.
        """
        title = display_title or f"{factor_name} factor Gate1 confirmed"
        default_limitations = limitations or (
            "hermetic_fixture",
            "not_live_backtest",
            "not_tradeable",
            "zero_orders",
            "plan_confirmed",
            "gate1_seeded",
            "gate1_confirmed",
            "gate_cascade_locked",
            "not_git_commit",
        )
        mark = "sample"
        if sample_or_real == "real":
            default_limitations = tuple(
                dict.fromkeys(list(default_limitations) + ["honesty_coercion"])
            )
        # Strip any smuggled unlock markers.
        banned = {
            "plan_confirm_required",
            "gate_cascade_unlock",
            "gate2_seed",
            "start_research",
            "tradeable",
            "live_backtest",
        }
        default_limitations = tuple(
            x for x in default_limitations if x not in banned
        )
        for required in (
            "plan_confirmed",
            "gate1_seeded",
            "gate1_confirmed",
            "gate_cascade_locked",
            "zero_orders",
            "not_live_backtest",
            "not_tradeable",
            "not_git_commit",
            "hermetic_fixture",
        ):
            if required not in default_limitations:
                default_limitations = tuple(list(default_limitations) + [required])
        _ = paper_digest
        default_evidence = provider_evidence
        if default_evidence is None:
            default_evidence = ("hermetic_factor_fixture", "hermetic_gate1_confirm")
        return self.seed_result(
            workspace_id=workspace_id,
            result_id=result_id,
            kind="factor",
            display_title=title,
            status=status,
            sample_or_real=mark,
            freshness=freshness,
            read_status=read_status,
            summary=summary or f"{factor_name} hermetic factor Gate1 confirm",
            task_id=task_id,
            attempt_id=attempt_id,
            run_id=run_id,
            factor_name=factor_name,
            paper_ref=paper_ref,
            formula_sketch=formula_sketch,
            universe_note=universe_note,
            ic_mean=ic_mean,
            sample_window=sample_window,
            provider_evidence=default_evidence,
            filters=filters
            or ("hermetic_factor_fixture", "gate1_confirmed"),
            exclusions=exclusions
            or (
                "live_backtest",
                "gate2_seed",
                "gate_cascade_unlock",
                "git_commit",
                "start_research",
                "orders",
            ),
            limitations=default_limitations,
            source=source,
            authority=authority,
            payload_digest=reviewed_source_sha256,
        )


    def seed_factor_vertical_b_gate2_seed_sample(
        self,
        *,
        workspace_id: str,
        result_id: str,
        factor_name: str,
        paper_ref: str,
        paper_digest: str,
        expected_candidate_digest: str,
        formula_sketch: str,
        universe_note: str,
        display_title: str | None = None,
        summary: str | None = None,
        status: str = "completed",
        task_id: str | None = None,
        attempt_id: str | None = None,
        run_id: str | None = None,
        provider_evidence: list[str] | tuple[str, ...] | None = None,
        filters: list[str] | tuple[str, ...] | None = None,
        exclusions: list[str] | tuple[str, ...] | None = None,
        limitations: list[str] | tuple[str, ...] | None = None,
        freshness: str = "fresh",
        read_status: str = "available",
        sample_or_real: str = "sample",
        ic_mean: float | int | None = None,
        sample_window: str | None = None,
        source: str = "hermetic_vertical_b_gate2_seed",
        authority: str = "vertical_binding_authority",
    ) -> TypedResultRecord:
        """V7g-B-M5 Gate2-seed seeder.

        Always sample. payload_digest is the candidate identity
        (expected_candidate_digest). Default limitations include gate2_seeded +
        gate_cascade_locked and historical gate1_confirmed / gate1_seeded /
        plan_confirmed.
        """
        title = display_title or f"{factor_name} factor Gate2 seeded"
        default_limitations = limitations or (
            "hermetic_fixture",
            "not_live_backtest",
            "not_tradeable",
            "zero_orders",
            "plan_confirmed",
            "gate1_seeded",
            "gate1_confirmed",
            "gate2_seeded",
            "gate_cascade_locked",
            "not_git_commit",
        )
        mark = "sample"
        if sample_or_real == "real":
            default_limitations = tuple(
                dict.fromkeys(list(default_limitations) + ["honesty_coercion"])
            )
        banned = {
            "plan_confirm_required",
            "gate_cascade_unlock",
            "gate2_decide",
            "gate2_confirmed",
            "start_research",
            "tradeable",
            "live_backtest",
        }
        default_limitations = tuple(
            x for x in default_limitations if x not in banned
        )
        for required in (
            "plan_confirmed",
            "gate1_seeded",
            "gate1_confirmed",
            "gate2_seeded",
            "gate_cascade_locked",
            "zero_orders",
            "not_live_backtest",
            "not_tradeable",
            "not_git_commit",
            "hermetic_fixture",
        ):
            if required not in default_limitations:
                default_limitations = tuple(list(default_limitations) + [required])
        # paper_digest retained for API continuity; payload is candidate identity.
        _ = paper_digest
        default_evidence = provider_evidence
        if default_evidence is None:
            default_evidence = ("hermetic_factor_fixture", "hermetic_gate2_seed")
        return self.seed_result(
            workspace_id=workspace_id,
            result_id=result_id,
            kind="factor",
            display_title=title,
            status=status,
            sample_or_real=mark,
            freshness=freshness,
            read_status=read_status,
            summary=summary or f"{factor_name} hermetic factor Gate2 seed",
            task_id=task_id,
            attempt_id=attempt_id,
            run_id=run_id,
            factor_name=factor_name,
            paper_ref=paper_ref,
            formula_sketch=formula_sketch,
            universe_note=universe_note,
            ic_mean=ic_mean,
            sample_window=sample_window,
            provider_evidence=default_evidence,
            filters=filters
            or ("hermetic_factor_fixture", "gate2_seeded"),
            exclusions=exclusions
            or (
                "live_backtest",
                "gate2_decide",
                "gate_cascade_unlock",
                "git_commit",
                "start_research",
                "orders",
            ),
            limitations=default_limitations,
            source=source,
            authority=authority,
            payload_digest=expected_candidate_digest,
        )

    def get(self, workspace_id: str, result_id: str) -> TypedResultRecord | None:
        with self._lock:
            return self._rows.get((workspace_id, result_id))

    def delete_result(self, workspace_id: str, result_id: str) -> bool:
        """Remove a result row. Used to roll back orphan seeds on bind race/conflict."""
        with self._lock:
            key = (workspace_id, result_id)
            if key in self._rows:
                del self._rows[key]
                return True
            return False

    def list_observed(
        self,
        workspace_id: str,
        *,
        limit: int = 50,
    ) -> list[TypedResultRecord]:
        """Newest-first by occurred_at then result_id. Empty is honest."""
        lim = limit if type(limit) is int and limit > 0 else 50
        with self._lock:
            rows = [r for (ws, _), r in self._rows.items() if ws == workspace_id]
        rows.sort(key=lambda r: (r.occurred_at, r.result_id), reverse=True)
        return rows[:lim]


_DEFAULT_AUTHORITY = ResultSurfaceAuthority()


def default_result_surface_authority() -> ResultSurfaceAuthority:
    return _DEFAULT_AUTHORITY


def reset_default_result_surface_authority() -> None:
    _DEFAULT_AUTHORITY.reset()


__all__ = [
    "ResultSurfaceAuthority",
    "ResultSurfaceAuthorityError",
    "TypedResultRecord",
    "default_result_surface_authority",
    "reset_default_result_surface_authority",
]
