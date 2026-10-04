"""Translate official Run controls without claiming private-fork guarantees."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from quant_system.hermes.approval_release_port import ApprovalReleaseResult
from quant_system.hermes.native_run_port import digest
from quant_system.hermes.run_stop_port import StopResult


def activity(client, run_id):
    from quant_system.hermes.gateway_client import _control_id

    rid = _control_id(run_id, "run_id")
    path = client.settings.native_state_path
    if not path.is_file():
        return ()
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        rows = db.execute(
            "SELECT seq,event_type,payload FROM activity "
            "WHERE run_id=? ORDER BY seq DESC LIMIT 200",
            (rid,),
        ).fetchall()
    return tuple(
        {
            "seq": seq,
            "run_id": rid,
            "event": kind,
            **json.loads(payload),
            "evidence_source": "platform_observed_native_stream",
        }
        for seq, kind, payload in reversed(rows)
    )


def status(client, run_id):
    from quant_system.hermes.gateway_client import HermesRunControlError, _control_id

    rid = _control_id(run_id, "run_id")
    raw = client._get_json(f"/v1/runs/{quote(rid, safe='')}")
    mapped = {
        "queued": "queued",
        "started": "queued",
        "running": "running",
        "waiting_for_approval": "running",
        "stopping": "running",
        "completed": "succeeded",
        "failed": "failed",
        "cancelled": "stopped",
        "interrupted": "stopped",
    }.get(raw.get("status"))
    if raw.get("run_id") != rid or mapped is None:
        raise HermesRunControlError("invalid_upstream_response", "Invalid native status")
    result = {
        **raw,
        "status": mapped,
        "upstream_status": raw["status"],
        "evidence_source": "official_http_status",
    }
    if mapped == "succeeded" and (raw.get("partial") is True or raw.get("completed") is False):
        result["status"] = "failed"
    if raw["status"] in {"waiting_for_approval", "stopping"}:
        result["substate"] = raw["status"]
    return result


def _pending(raw):
    approval = raw.get("approval")
    if raw.get("upstream_status") != "waiting_for_approval" or not isinstance(approval, dict):
        return None
    request_id, timestamp = approval.get("request_id"), approval.get("timestamp")
    if not isinstance(request_id, str) or not request_id or not isinstance(timestamp, (int, float)):
        return None
    # This is a project review window, NOT an asserted upstream approval TTL.
    deadline = datetime.fromtimestamp(timestamp, UTC) + timedelta(minutes=30)
    if deadline <= datetime.now(UTC):
        return None
    return {
        "approval_id": "native:" + request_id,
        "command_id": request_id,
        "run_id": raw["run_id"],
        "digest": digest(approval),
        "expires_at": deadline.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "expected_status": "pending",
        "status": "pending",
        "kind": "hermes.command_approval",
        "evidence_source": "official_http_status",
        "validity_source": "platform_review_window",
    }


def pending(client, run_ids):
    from quant_system.hermes.gateway_client import HermesApiReadError, HermesRunControlError

    if len(run_ids) > 64 or len(set(run_ids)) != len(run_ids):
        raise HermesRunControlError("run_control_validation", "Invalid run list")
    result = []
    for rid in run_ids:
        try:
            row = _pending(status(client, rid))
        except HermesApiReadError as exc:
            if exc.status_code == 404 or exc.code == "run_not_found":
                continue
            raise
        if row:
            result.append(row)
    return tuple(result)


def approve(
    client, run_id, *, choice, challenge_id, action_digest, expected_status, expected_expires_at
):
    from quant_system.hermes.gateway_client import HermesRunControlError

    observed = _pending(status(client, run_id))
    if (
        choice not in {"once", "deny"}
        or expected_status != "pending"
        or not observed
        or observed["approval_id"] != challenge_id
        or observed["digest"] != action_digest
        or observed["expires_at"] != expected_expires_at
    ):
        raise HermesRunControlError(
            "approval_exact_binding_conflict", "Pending native request changed"
        )
    reply = client._post_json(
        f"/v1/runs/{quote(run_id, safe='')}/approval",
        {"choice": choice, "request_id": observed["command_id"]},
    )
    if reply.get("run_id") != run_id or reply.get("resolved") != 1 or reply.get("choice") != choice:
        raise HermesRunControlError(
            "outcome_unknown", "Native approval acknowledgement unavailable"
        )
    return ApprovalReleaseResult(
        run_id=run_id,
        choice=choice,
        decision_status="accepted",
        waiter_signal_status="confirmed",
        challenge_id=challenge_id,
        action_digest=action_digest,
        resolved=1,
    )


def stop(client, run_id):
    from quant_system.hermes.gateway_client import HermesRunControlError, _control_id

    rid = _control_id(run_id, "run_id")
    before = status(client, rid)
    if before["status"] in {"succeeded", "failed", "stopped"}:
        return StopResult(run_id=rid, status=before["status"], idempotent_replay=True)
    reply = client._post_json(f"/v1/runs/{quote(rid, safe='')}/stop", {})
    if reply.get("status") not in {"stopping", "cancelled", "interrupted"}:
        raise HermesRunControlError("outcome_unknown", "Native stop acknowledgement unavailable")
    # A stopping receipt is not proof of executor exit.
    return StopResult(run_id=rid, status="running" if reply["status"] == "stopping" else "stopped")
