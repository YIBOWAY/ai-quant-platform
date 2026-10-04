"""Project-side adapter for the unmodified official Hermes HTTP API.

Project receipts are labelled as such. Native status observations do not pretend
to be the old fork's transactional event replay or durable approval challenges.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import quote

import httpx

from quant_system.hermes.dispatch_adapter import HermesRunObservation
from quant_system.hermes.managed_session_provisioner import (
    ManagedSessionProvisionError,
    ManagedSessionProvisionReceipt,
)
from quant_system.hermes.run_lifecycle_port import (
    HermesRunCompatibilityReceipt,
    HermesRunPortError,
    SubprocessHermesRunLifecyclePort,
)

PROTOCOL = "official-http-v1"
_STATES = {
    "queued": "accepted",
    "started": "accepted",
    "running": "running",
    "waiting_for_approval": "running",
    "stopping": "running",
    "completed": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
    "interrupted": "cancelled",
}


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


class NativeReceipts:
    """Small project-owned request journal, not a duplicate Hermes Run database."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS requests (
                request_key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                session_id TEXT NOT NULL, metadata TEXT NOT NULL,
                first_sent REAL NOT NULL, run_id TEXT, terminal TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS activity (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                event_type TEXT NOT NULL, payload TEXT NOT NULL)""")
        path.chmod(0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def reserve(self, key: str, body: dict, retention: float) -> dict:
        fingerprint = digest(body)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM requests WHERE request_key=?", (key,)).fetchone()
            if row:
                if row["fingerprint"] != fingerprint:
                    raise HermesRunPortError(
                        "idempotency_conflict", "Request changed", retryable=False
                    )
                if not row["run_id"] and time.time() - row["first_sent"] >= retention:
                    raise HermesRunPortError(
                        "native_replay_window_expired",
                        "Prior acceptance is unknown",
                        retryable=False,
                    )
                return dict(row)
            # An unresolved request blocks another turn of the same managed Session.
            active = db.execute(
                "SELECT request_key FROM requests WHERE session_id=? AND terminal IS NULL",
                (body["session_id"],),
            ).fetchone()
            if active:
                raise HermesRunPortError(
                    "session_busy", "Prior turn is not settled", retryable=True
                )
            db.execute(
                "INSERT INTO requests VALUES(?,?,?,?,?,?,?)",
                (
                    key,
                    fingerprint,
                    body["session_id"],
                    json.dumps(body.get("metadata", {})),
                    time.time(),
                    None,
                    None,
                ),
            )
            return {"run_id": None}

    def accepted(self, key: str, run_id: str):
        with self.connect() as db:
            db.execute(
                "UPDATE requests SET run_id=? WHERE request_key=? AND (run_id IS NULL OR run_id=?)",
                (run_id, key, run_id),
            )

    def terminal(self, run_id: str, document: dict):
        with self.connect() as db:
            db.execute(
                "UPDATE requests SET terminal=? WHERE run_id=? AND terminal IS NULL",
                (json.dumps(document, sort_keys=True), run_id),
            )

    def rejected(self, key: str, code: str):
        with self.connect() as db:
            db.execute(
                "UPDATE requests SET terminal=? WHERE request_key=? AND run_id IS NULL",
                (json.dumps({"rejected": code}), key),
            )


class NativeHermesRunPort(SubprocessHermesRunLifecyclePort):
    """Reuse project dispatch validation, replace the HQA subprocess with HTTP."""

    protocol = PROTOCOL

    def __init__(self, *, cli_settings, input_resolver, state_path: Path, client=None):
        super().__init__(cli_settings=cli_settings, input_resolver=input_resolver)
        self.receipts = NativeReceipts(state_path)
        self.http = client or httpx.Client(trust_env=False, timeout=cli_settings.timeout_seconds)
        self._collectors = set()
        self._collector_lock = threading.Lock()

    def request(self, method: str, path: str, *, body=None, headers=None):
        auth = (
            {"Authorization": "Bearer " + self.cli_settings.api_key}
            if self.cli_settings.api_key
            else {}
        )
        try:
            response = self.http.request(
                method,
                self.cli_settings.base_url.rstrip("/") + path,
                headers={**auth, **(headers or {})},
                json=body,
            )
            raw = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HermesRunPortError(
                "transport_error", "Native Hermes transport failed", retryable=True
            ) from exc
        if response.status_code >= 400:
            error = raw.get("error") if isinstance(raw, dict) else None
            code = (
                error.get("code", "native_http_error")
                if isinstance(error, dict)
                else "native_http_error"
            )
            exc = HermesRunPortError(
                str(code),
                "Native Hermes request failed",
                retryable=response.status_code >= 500 or response.status_code in (409, 429),
            )
            exc.http_status = response.status_code
            raise exc
        if not isinstance(raw, dict):
            raise HermesRunPortError(
                "invalid_upstream_response", "Expected JSON object", retryable=False
            )
        return raw

    def capabilities(self) -> Mapping[str, object]:
        return self.request("GET", "/v1/capabilities")

    def require_compatible_capabilities(self, contract=None):
        caps = self.capabilities()
        features = caps.get("features", {})
        idem = features.get("runs_idempotency", {})
        if (
            caps.get("object") != "hermes.api_server.capabilities"
            or not all(
                features.get(k) is True
                for k in ("run_submission", "run_status", "run_stop", "session_resources")
            )
            or idem.get("supported") is not True
            or idem.get("durable") is not True
            or not isinstance(idem.get("retention_seconds"), (int, float))
            or idem["retention_seconds"] <= 0
        ):
            raise HermesRunPortError(
                "native_contract_unavailable",
                "Official Hermes requirements unavailable",
                retryable=True,
            )
        self.retention_seconds = float(idem["retention_seconds"])
        # Zero explicitly means there is no private Hermes contract_version.
        return HermesRunCompatibilityReceipt(
            hermes_contract_version=0,
            cli_operations=(),
            evidence_digest=digest({"protocol": PROTOCOL, "capabilities": caps}),
        )

    def _invoke(self, operation: str, payload: dict):
        if operation != "submit":
            raise HermesRunPortError(
                "native_operation_unsupported", "Unsupported dispatch operation", retryable=False
            )
        self.require_compatible_capabilities()
        body = payload["request_body"]
        sid = body["session_id"]
        key = payload["idempotency_key"]
        prior = self.receipts.reserve(key, body, self.retention_seconds)
        if prior.get("terminal") and not prior.get("run_id"):
            raise HermesRunPortError(
                "native_request_rejected", "Prior request was rejected", retryable=False
            )
        if prior["run_id"]:
            rid, created = prior["run_id"], False
        else:
            try:
                reply = self.request(
                    "POST", "/v1/runs", body=body, headers={"Idempotency-Key": key}
                )
            except HermesRunPortError as exc:
                # Only definite validation/auth rejections release the session.
                # Timeouts, conflicts and server errors can hide acceptance.
                if getattr(exc, "http_status", None) in {400, 401, 403, 404, 422}:
                    self.receipts.rejected(key, exc.code)
                raise
            rid = reply.get("run_id")
            if not isinstance(rid, str) or not rid.startswith("run_"):
                raise HermesRunPortError(
                    "run_identity_mismatch", "Missing native Run identity", retryable=True
                )
            self.receipts.accepted(key, rid)
            created = reply.get("replayed") is not True
            if created:
                self._collect_activity(rid)
        return {
            "ok": True,
            "run_id": rid,
            "created": created,
            "requested_session_id": sid,
            "session_id": sid,
            "conversation_session_id": sid,
            "resolved_session_id": sid,
        }

    def _collect_activity(self, run_id):
        """One native SSE consumer records only no-body progress metadata."""
        with self._collector_lock:
            if run_id in self._collectors:
                return
            self._collectors.add(run_id)

        def collect():
            auth = (
                {"Authorization": "Bearer " + self.cli_settings.api_key}
                if self.cli_settings.api_key
                else {}
            )
            try:
                with self.http.stream(
                    "GET",
                    self.cli_settings.base_url.rstrip("/")
                    + f"/v1/runs/{quote(run_id, safe='')}/events",
                    headers=auth,
                    timeout=30,
                ) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line.startswith("data:"):
                            continue
                        event = json.loads(line[5:])
                        if event.get("run_id") != run_id:
                            continue
                        kind = event.get("event", "")
                        if kind not in {
                            "tool.started",
                            "tool.completed",
                            "run.completed",
                            "run.failed",
                            "run.cancelled",
                            "run.interrupted",
                        }:
                            continue
                        payload = {
                            k: event[k] for k in ("tool", "duration", "timestamp") if k in event
                        }
                        if "error" in event:
                            payload["error"] = bool(event["error"])
                        with self.receipts.connect() as db:
                            db.execute(
                                "INSERT INTO activity(run_id,event_type,payload) VALUES(?,?,?)",
                                (run_id, kind, json.dumps(payload)),
                            )
            except Exception:
                # Missing stream data does not counterfeit history or stop a
                # native run. Durable status remains the completion authority.
                with self.receipts.connect() as db:
                    db.execute(
                        "INSERT INTO activity(run_id,event_type,payload) VALUES(?,?,?)",
                        (run_id, "stream.unavailable", "{}"),
                    )
            finally:
                with self._collector_lock:
                    self._collectors.discard(run_id)

        threading.Thread(target=collect, name="hermes-native-progress", daemon=True).start()

    def observe(
        self,
        *,
        hermes_session_id,
        hermes_run_id,
        conversation_hermes_session_id=None,
        after_cursor=0,
    ):
        raw = self.request("GET", f"/v1/runs/{quote(hermes_run_id, safe='')}")
        sid = conversation_hermes_session_id or hermes_session_id
        valid = raw.get("run_id") == hermes_run_id and raw.get("session_id") == hermes_session_id
        state = _STATES.get(raw.get("status"), "outcome_unknown") if valid else "outcome_unknown"
        # A claimed completed status with explicit incomplete output is never success.
        if state == "succeeded" and (raw.get("completed") is False or raw.get("partial") is True):
            state = "failed"
        terminal = state in {"succeeded", "failed", "cancelled"}
        if terminal:
            self.receipts.terminal(hermes_run_id, raw)
        return HermesRunObservation(
            status=state,
            conversation_hermes_session_id=sid,
            hermes_session_id=hermes_session_id,
            hermes_run_id=hermes_run_id,
            evidence_digest=digest({"source": PROTOCOL, "status": raw}) if valid else None,
            next_cursor=after_cursor,
            replay_complete=False,
            terminal_evidence_source="native_status" if terminal else "event_replay",
            error_code="hermes_run_failed" if state == "failed" else None,
        )

    def ensure_session(self, *, session_id: str, action_digest: str):
        if (
            not isinstance(action_digest, str)
            or not re.fullmatch("[0-9a-f]{64}", action_digest)
            or session_id != "web_" + action_digest[:40]
        ):
            raise ManagedSessionProvisionError("managed_session_identity_mismatch", retryable=False)
        created = False
        try:
            doc = self.request("GET", "/api/sessions/" + quote(session_id, safe=""))
        except HermesRunPortError as exc:
            if exc.code not in {"session_not_found", "not_found"}:
                raise
            doc = self.request("POST", "/api/sessions", body={"id": session_id})
            created = True
        if doc.get("session", {}).get("id") != session_id:
            raise ManagedSessionProvisionError("managed_session_identity_mismatch", retryable=False)
        return ManagedSessionProvisionReceipt(session_id, action_digest, created, not created)

    def fork_session(self, **kwargs):
        # Official fork ends its source and clones the entire transcript. Never
        # pass our old preserve_source/cursor request to that different operation.
        raise ManagedSessionProvisionError("native_exact_fork_unavailable", retryable=False)
