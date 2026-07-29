import crypto from "node:crypto";

const WORKSPACE_ID = "ws-local-main";
const CSRF_TOKEN = "fixture-csrf-token";
const ACTIVE_PLATFORM_SESSION_ID = `wm_${"1".repeat(32)}`;
const ACTIVE_SESSION_ID = `web_${"1".repeat(40)}`;
const EXTERNAL_SESSION_ID = "fixture-long-session";
const INITIAL_COMMAND_ID = "fixture-command-active-001";
const INITIAL_RUN_ID = "fixture-run-active-001";
const APPROVAL_ID = "fixture-approval-active-001";
const FIXED_AT = "2026-07-29T08:00:00Z";

function clone(value) {
  return typeof structuredClone === "function"
    ? structuredClone(value)
    : JSON.parse(JSON.stringify(value));
}

function canonicalJson(value) {
  if (value === null || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("non-finite fixture action");
    return JSON.stringify(value);
  }
  if (typeof value === "string") {
    return JSON.stringify(value).replace(
      /[\u007f-\uffff]/g,
      (character) =>
        `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`,
    );
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  }
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${canonicalJson(key)}:${canonicalJson(value[key])}`)
      .join(",")}}`;
  }
  throw new Error("fixture action is not strict JSON");
}

function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function readyManagedSession(
  platformSessionId,
  hermesSessionId,
  lineage = {},
) {
  return {
    platform_session_id: platformSessionId,
    session_ref: `session:${platformSessionId}`,
    hermes_session_id: hermesSessionId,
    provision_state: "ready",
    web_writable: true,
    attempt_count: 1,
    provisioned_at: FIXED_AT,
    created_at: FIXED_AT,
    updated_at: FIXED_AT,
    ...lineage,
  };
}

function initialMessages() {
  return Array.from({ length: 28 }, (_, index) => ({
    id: `active-message-${String(index + 1).padStart(2, "0")}`,
    role: index % 2 === 0 ? "user" : "assistant",
    content: `${
      index % 2 === 0 ? "Research question" : "Fixture answer"
    } ${index + 1}: ${"bounded lifecycle context ".repeat(3)}`,
    timestamp: `2026-07-29T07:${String(index).padStart(2, "0")}:00Z`,
    fork_point: `message:${index + 1}`,
  }));
}

function externalMessages() {
  return [
    {
      id: "external-display-1",
      role: "user",
      content: "Historical Discord question",
      timestamp: "2026-07-28T01:00:00Z",
      fork_point: "message:41",
    },
    {
      id: "external-display-2",
      role: "assistant",
      content: "Historical read-only answer",
      timestamp: "2026-07-28T01:01:00Z",
      fork_point: "message:42",
    },
    {
      id: "external-display-3",
      role: "user",
      content: "Continue from this exact historical message",
      timestamp: "2026-07-28T01:02:00Z",
      fork_point: "message:43",
    },
  ];
}

function createState() {
  const managedSessions = [
    readyManagedSession(ACTIVE_PLATFORM_SESSION_ID, ACTIVE_SESSION_ID),
  ];
  return {
    audit: [],
    cursor: 7,
    sseConnectionSequence: 0,
    sseClients: new Map(),
    managedSessions,
    messagesBySession: new Map([
      [ACTIVE_SESSION_ID, initialMessages()],
      [EXTERNAL_SESSION_ID, externalMessages()],
    ]),
    commands: [
      {
        command_id: INITIAL_COMMAND_ID,
        kind: "conversation_turn",
        state: "delivered",
        version: 2,
        platform_session_id: ACTIVE_PLATFORM_SESSION_ID,
        hermes_session_id: ACTIVE_SESSION_ID,
        hermes_run_id: INITIAL_RUN_ID,
        updated_at: FIXED_AT,
        created_at: FIXED_AT,
      },
    ],
    approvals: [
      {
        approval_id: APPROVAL_ID,
        run_id: INITIAL_RUN_ID,
        command_id: INITIAL_COMMAND_ID,
        digest: "a".repeat(64),
        expires_at: "2099-07-29T08:00:00Z",
        expected_status: "pending",
        status: "pending",
        kind: "tool_execution",
      },
    ],
    gates: [
      {
        gate_id: "fixture-gate-1",
        gate_kind: "gate1",
        status: "confirmed",
        task_ref: "task:fixture-research",
        task_version: 3,
        reviewed_source_sha256: "b".repeat(64),
        gate1_confirmation_id: "fixture-confirmation-1",
        decided_at: FIXED_AT,
      },
      {
        gate_id: "fixture-gate-2",
        gate_kind: "gate2",
        status: "pending",
        expected_status: "pending",
        task_ref: "task:fixture-research",
        task_version: 3,
        candidate_ref: "candidate:fixture-factor",
        expected_digest: "c".repeat(64),
      },
      {
        gate_id: "fixture-gate-3",
        gate_kind: "gate3",
        status: "prepared",
        task_ref: "task:fixture-research",
        task_version: 3,
        candidate_ref: "candidate:fixture-factor",
        expected_digest: "c".repeat(64),
        promotion_id: "fixture-promotion-1",
        worktree: "/fixture/review/worktree",
        patch: "/fixture/review/change.patch",
        manifest: "/fixture/review/manifest.json",
        human_git_commit_required: true,
        auto_commit: false,
      },
    ],
    results: [
      {
        result_id: "fixture-result-terminal-001",
        id: "fixture-result-terminal-001",
        kind: "backtest",
        display_title: "Fixture terminal backtest",
        status: "completed",
        sample_or_real: "sample",
        freshness: "fresh",
        read_status: "available",
        occurred_at: FIXED_AT,
        summary: "Deterministic hermetic result; no provider or trading call.",
        task_id: "fixture-research",
        attempt_id: "fixture-attempt-1",
        run_id: INITIAL_RUN_ID,
        artifact_id: "fixture-artifact-1",
        command_id: INITIAL_COMMAND_ID,
        limitations: ["fixture-only", "zero external effects"],
        exact_links: {
          task_ref: "task:fixture-research",
          attempt_ref: "attempt:fixture-attempt-1",
          run_ref: `run:${INITIAL_RUN_ID}`,
          artifact_ref: "artifact:fixture-artifact-1",
          command_id: INITIAL_COMMAND_ID,
        },
      },
    ],
  };
}

function authorityHealth() {
  return {
    session_registry: "ready",
    command_approval: "ready",
    gate_1: "ready",
    gate_2: "ready",
    gate_3: "ready",
    task: "ready",
    attempt: "ready",
    run: "ready",
    result: "ready",
  };
}

function snapshot(state) {
  return {
    workspace: { workspace_id: WORKSPACE_ID },
    owner_user_id: "fixture-owner",
    snapshot_workspace_cursor: state.cursor,
    sessions: state.managedSessions.map((row) => row.session_ref),
    managed_sessions: clone(state.managedSessions),
    commands: clone(state.commands),
    tasks: ["task:fixture-research"],
    attempts: ["attempt:fixture-attempt-1"],
    runs: [`run:${INITIAL_RUN_ID}`],
    results: clone(state.results),
    approvals: clone(state.approvals),
    gates: clone(state.gates),
    public_cutovers: [],
    authority_health: authorityHealth(),
    mutation_enabled: true,
    observed_at: FIXED_AT,
  };
}

function followPage(state, afterCursor) {
  return {
    events: [],
    after_cursor: afterCursor,
    next_cursor: state.cursor,
    resync_required: false,
    mutation_enabled: true,
    approvals: clone(state.approvals),
    gates: clone(state.gates),
    results: clone(state.results),
    public_cutovers: [],
    tasks: ["task:fixture-research"],
    attempts: ["attempt:fixture-attempt-1"],
    runs: [`run:${INITIAL_RUN_ID}`],
    authority_health: authorityHealth(),
  };
}

function messageEnvelope(state, sessionId) {
  const messages = state.messagesBySession.get(sessionId);
  if (!messages) return null;
  return {
    read_status: "available",
    session_id: sessionId,
    messages: clone(messages),
    omitted_message_count: 0,
    warnings: [],
  };
}

async function readJsonBody(req) {
  const chunks = [];
  let bytes = 0;
  for await (const chunk of req) {
    bytes += chunk.length;
    if (bytes > 65_536) {
      throw new Error("fixture request body exceeds 64 KiB");
    }
    chunks.push(chunk);
  }
  const raw = Buffer.concat(chunks).toString("utf8");
  return raw ? JSON.parse(raw) : {};
}

function hasFixtureCsrf(req) {
  const header = req.headers["x-csrf-token"];
  const cookie = req.headers.cookie ?? "";
  return (
    header === CSRF_TOKEN &&
    cookie.split(";").some((part) => part.trim() === `qs_aw_csrf=${CSRF_TOKEN}`)
  );
}

function broadcast(state, eventName, payload) {
  const frame = `event: ${eventName}\ndata: ${JSON.stringify(payload)}\n\n`;
  for (const response of [...state.sseClients.keys()]) {
    if (response.destroyed || response.writableEnded) {
      state.sseClients.delete(response);
      continue;
    }
    response.write(frame);
  }
}

function recordAudit(state, entry) {
  state.audit.push({
    sequence: state.audit.length + 1,
    ...entry,
  });
}

function gatewayStatus() {
  return {
    read_status: "available",
    connected: true,
    model: "fixture-model",
    session_api_available: true,
    chat_write_ready: true,
    features: {
      session_resources: true,
      hermetic_lifecycle_fixture: true,
    },
    upstream_blockers: [],
    platform_delivery_blockers: [],
    blockers: [],
    warnings: [],
  };
}

function sessionsResponse(state) {
  const managed = state.managedSessions.map((row) => ({
    id: row.hermes_session_id,
    title: "Managed fixture conversation",
    source: "web",
    model: "fixture-model",
    message_count:
      state.messagesBySession.get(row.hermes_session_id)?.length ?? 0,
    last_active: FIXED_AT,
    preview: "Deterministic managed lifecycle fixture.",
    parent_session_id: row.parent_session_ref?.replace(/^session:/, "") ?? null,
    ended_at: null,
  }));
  return {
    read_status: "available",
    sessions: [
      {
        id: EXTERNAL_SESSION_ID,
        title: "Historical Discord fixture",
        source: "discord",
        model: "fixture-model",
        message_count: externalMessages().length,
        last_active: "2026-07-28T01:02:00Z",
        preview: "Read-only external context with exact fork cursors.",
        parent_session_id: null,
        ended_at: null,
      },
      ...managed,
    ],
    limit: 50,
    offset: 0,
    has_more: false,
    warnings: [],
  };
}

export function createHermesLifecycleFixture() {
  const state = createState();

  return {
    state,
    async handle({ req, res, method, pathname, url, finish }) {
      if (method === "GET" && pathname === "/api/hermes/gateway") {
        finish(200, gatewayStatus());
        return true;
      }
      if (method === "GET" && pathname === "/api/auth/owner/session") {
        finish(
          200,
          {
            session_id: "fixture-owner-session",
            mutation_enabled: true,
            security_ready: true,
          },
          {
            "Set-Cookie": `qs_aw_csrf=${CSRF_TOKEN}; Path=/; SameSite=Strict`,
          },
        );
        return true;
      }
      if (
        method === "GET" &&
        pathname === `/api/workspace/${WORKSPACE_ID}/snapshot`
      ) {
        finish(200, snapshot(state));
        return true;
      }
      if (
        method === "GET" &&
        pathname === `/api/workspace/${WORKSPACE_ID}/follow`
      ) {
        const rawAfter = url.searchParams.get("after_cursor");
        finish(200, followPage(state, rawAfter === null ? null : Number(rawAfter)));
        return true;
      }
      if (
        method === "GET" &&
        pathname === `/api/workspace/${WORKSPACE_ID}/follow/stream`
      ) {
        res.statusCode = 200;
        // Prevent the Next rewrite from gzip-buffering small SSE frames.
        res.setHeader("Cache-Control", "no-store, no-transform");
        res.setHeader("Content-Type", "text/event-stream; charset=utf-8");
        res.setHeader("Content-Encoding", "identity");
        res.setHeader("Connection", "keep-alive");
        res.setHeader("X-Accel-Buffering", "no");
        res.flushHeaders();
        res.write(`event: ready\ndata: ${JSON.stringify({ ready: true })}\n\n`);
        state.sseConnectionSequence += 1;
        state.sseClients.set(res, {
          after_cursor: Number(url.searchParams.get("after_cursor") ?? 0),
          connection_sequence: state.sseConnectionSequence,
        });
        req.once("close", () => state.sseClients.delete(res));
        return true;
      }
      if (method === "GET" && pathname === "/api/hermes/fixture-audit") {
        finish(200, {
          events: clone(state.audit),
          sse_client_count: state.sseClients.size,
          sse_connection_sequence: state.sseConnectionSequence,
          sse_connections: clone([...state.sseClients.values()]),
          workspace_cursor: state.cursor,
        });
        return true;
      }
      if (method === "GET" && pathname === "/api/hermes/sessions") {
        finish(200, sessionsResponse(state));
        return true;
      }

      const messageMatch = pathname.match(
        /^\/api\/hermes\/sessions\/([^/]+)\/messages$/,
      );
      if (method === "GET" && messageMatch) {
        const sessionId = decodeURIComponent(messageMatch[1]);
        const envelope = messageEnvelope(state, sessionId);
        finish(
          envelope ? 200 : 404,
          envelope ?? { detail: "session_not_found" },
        );
        return true;
      }

      const detailMatch = pathname.match(/^\/api\/hermes\/sessions\/([^/]+)$/);
      if (method === "GET" && detailMatch) {
        const sessionId = decodeURIComponent(detailMatch[1]);
        if (sessionId === EXTERNAL_SESSION_ID) {
          finish(200, {
            read_status: "available",
            session: sessionsResponse(state).sessions[0],
            fork_context: {
              eligible: true,
              source_channel: "discord",
              reason_code: null,
            },
            warnings: [],
          });
          return true;
        }
        const managed = state.managedSessions.find(
          (row) => row.hermes_session_id === sessionId,
        );
        finish(
          managed ? 200 : 404,
          managed
            ? {
                read_status: "available",
                session: sessionsResponse(state).sessions.find(
                  (row) => row.id === sessionId,
                ),
                fork_context: {
                  eligible: false,
                  source_channel: "web",
                  reason_code: "source_session_not_external",
                },
                warnings: [],
              }
            : { detail: "session_not_found" },
        );
        return true;
      }

      if (
        method === "POST" &&
        pathname === "/api/hermes/fixture-append-assistant"
      ) {
        if (!hasFixtureCsrf(req)) {
          finish(403, { detail: "fixture_csrf_required" });
          return true;
        }
        const messages = state.messagesBySession.get(ACTIVE_SESSION_ID);
        messages.push({
          id: `active-stream-${messages.length + 1}`,
          role: "assistant",
          content: `Later streamed fixture update: ${"no scroll hijack ".repeat(20)}`,
          timestamp: FIXED_AT,
          fork_point: `message:${messages.length + 1}`,
        });
        state.cursor += 1;
        recordAudit(state, {
          kind: "fixture.transcript.append",
          hermes_session_id: ACTIVE_SESSION_ID,
        });
        broadcast(state, "transcript", {
          hermes_session_id: ACTIVE_SESSION_ID,
          revision: state.cursor,
        });
        finish(200, { appended: true, revision: state.cursor });
        return true;
      }

      const forkMatch = pathname.match(
        /^\/api\/hermes\/sessions\/([^/]+)\/forks-to-managed$/,
      );
      if (method === "POST" && forkMatch) {
        if (!hasFixtureCsrf(req)) {
          finish(403, { detail: "fixture_csrf_required" });
          return true;
        }
        const sourceSessionId = decodeURIComponent(forkMatch[1]);
        const body = await readJsonBody(req);
        const forkPoint = body.fork_point;
        const cursor = Number(String(forkPoint).replace(/^message:/, ""));
        const sourceMessages = state.messagesBySession.get(sourceSessionId);
        if (
          !sourceMessages ||
          !Number.isInteger(cursor) ||
          !sourceMessages.some((row) => row.fork_point === forkPoint)
        ) {
          finish(409, { detail: { code: "fork_point_not_authoritative" } });
          return true;
        }
        const digest = sha256(
          `${sourceSessionId}:${forkPoint}:${body.client_action_id}`,
        );
        const platformSessionId = `wm_${digest.slice(0, 32)}`;
        const hermesSessionId = `web_${digest.slice(0, 40)}`;
        const sessionRef = `session:${platformSessionId}`;
        const child = readyManagedSession(platformSessionId, hermesSessionId, {
          parent_session_ref: `session:external-${sourceSessionId}`,
          fork_point: forkPoint,
        });
        state.managedSessions.push(child);
        const selectedIndex = sourceMessages.findIndex(
          (row) => row.fork_point === forkPoint,
        );
        state.messagesBySession.set(
          hermesSessionId,
          clone(sourceMessages.slice(0, selectedIndex + 1)),
        );
        state.cursor += 1;
        recordAudit(state, {
          kind: "managed_session.fork",
          client_action_id: body.client_action_id,
          fork_point: forkPoint,
          hermes_session_id: hermesSessionId,
          new_provider_policy_digest: body.new_provider_policy_digest,
          source_session_id: sourceSessionId,
        });
        finish(200, {
          status: "accepted",
          client_action_id: body.client_action_id,
          action_digest: digest,
          workspace: { workspace_id: WORKSPACE_ID },
          mutation_enabled: true,
          platform_session_id: platformSessionId,
          session_ref: sessionRef,
          hermes_session_id: hermesSessionId,
        });
        return true;
      }

      if (
        method === "POST" &&
        pathname === `/api/workspace/${WORKSPACE_ID}/act`
      ) {
        if (!hasFixtureCsrf(req)) {
          finish(403, { detail: "fixture_csrf_required" });
          return true;
        }
        const body = await readJsonBody(req);
        const action = body.action ?? {};
        recordAudit(state, {
          kind: action.kind,
          client_action_id: action.client_action_id,
          approval_ref: action.approval_ref ?? null,
          decision: action.decision ?? null,
          run_ref: action.run_ref ?? null,
        });
        if (action.kind === "run.stop.request") {
          const runId = String(action.run_ref ?? "").replace(/^run:/, "");
          const command = state.commands.find(
            (row) => row.hermes_run_id === runId,
          );
          if (!command) {
            finish(409, { detail: { code: "run_not_stoppable" } });
            return true;
          }
          command.state = "cancelled";
          command.version += 1;
          command.updated_at = FIXED_AT;
          state.cursor += 1;
          broadcast(state, "command", {
            event_id: state.cursor,
            type: "command",
            command_id: command.command_id,
            command_version: command.version,
            kind: command.kind,
            state: command.state,
            hermes_session_id: command.hermes_session_id,
            hermes_run_id: command.hermes_run_id,
            occurred_at: FIXED_AT,
          });
          finish(200, {
            status: "accepted",
            client_action_id: action.client_action_id,
            workspace: { workspace_id: WORKSPACE_ID },
            mutation_enabled: true,
            run_id: runId,
          });
          return true;
        }
        if (action.kind === "hermes.command_approval.decide") {
          const approvalId = String(action.approval_ref ?? "").replace(
            /^approval:/,
            "",
          );
          const approval = state.approvals.find(
            (row) => row.approval_id === approvalId,
          );
          if (!approval || approval.status !== "pending") {
            finish(409, { detail: { code: "approval_not_pending" } });
            return true;
          }
          approval.status =
            action.decision === "allow_once" ? "allowed_once" : "denied";
          approval.decision = action.decision;
          approval.decided_at = FIXED_AT;
          state.cursor += 1;
          broadcast(state, "approvals", {
            approvals: state.approvals,
            authority_health: authorityHealth(),
          });
          finish(200, {
            status: "accepted",
            client_action_id: action.client_action_id,
            workspace: { workspace_id: WORKSPACE_ID },
            mutation_enabled: true,
          });
          return true;
        }
        if (action.kind === "managed_session.create") {
          const digest = sha256(canonicalJson(action));
          const platformSessionId = `wm_${digest.slice(0, 32)}`;
          const hermesSessionId = `web_${digest.slice(0, 40)}`;
          const managed = readyManagedSession(
            platformSessionId,
            hermesSessionId,
          );
          state.managedSessions.push(managed);
          state.messagesBySession.set(hermesSessionId, []);
          state.cursor += 1;
          finish(200, {
            status: "accepted",
            client_action_id: action.client_action_id,
            action_digest: digest,
            workspace: { workspace_id: WORKSPACE_ID },
            mutation_enabled: true,
            platform_session_id: platformSessionId,
            session_ref: managed.session_ref,
            hermes_session_id: hermesSessionId,
          });
          return true;
        }
        finish(409, { detail: { code: "fixture_action_not_supported" } });
        return true;
      }

      if (
        method === "POST" &&
        pathname === "/api/agent/workspace/submit-turn"
      ) {
        if (!hasFixtureCsrf(req)) {
          finish(403, { detail: "fixture_csrf_required" });
          return true;
        }
        const body = await readJsonBody(req);
        const managed = state.managedSessions.find(
          (row) => row.session_ref === body.managed_session_ref,
        );
        if (!managed) {
          finish(409, { detail: { code: "managed_session_not_ready" } });
          return true;
        }
        const messages = state.messagesBySession.get(managed.hermes_session_id);
        const turn = state.commands.filter(
          (row) => row.kind === "conversation_turn",
        ).length;
        const commandId = `fixture-command-turn-${String(turn).padStart(3, "0")}`;
        const runId = `fixture-run-turn-${String(turn).padStart(3, "0")}`;
        messages.push(
          {
            id: `active-user-${messages.length + 1}`,
            role: "user",
            content: body.prompt,
            timestamp: FIXED_AT,
            fork_point: `message:${messages.length + 1}`,
          },
          {
            id: `active-assistant-${messages.length + 2}`,
            role: "assistant",
            content: `Fixture reply ${turn}: ${body.prompt}`,
            timestamp: FIXED_AT,
            fork_point: `message:${messages.length + 2}`,
          },
        );
        const command = {
          command_id: commandId,
          kind: "conversation_turn",
          state: "succeeded",
          version: 3,
          client_action_id: body.client_action_id,
          platform_session_id: managed.platform_session_id,
          hermes_session_id: managed.hermes_session_id,
          hermes_run_id: runId,
          updated_at: FIXED_AT,
          created_at: FIXED_AT,
        };
        state.commands.unshift(command);
        state.cursor += 1;
        recordAudit(state, {
          kind: "conversation.turn",
          client_action_id: body.client_action_id,
          command_id: commandId,
          managed_session_ref: body.managed_session_ref,
          prompt_sha256: sha256(String(body.prompt)),
        });
        broadcast(state, "command", {
          event_id: state.cursor,
          type: "command",
          command_id: command.command_id,
          command_version: command.version,
          client_action_id: command.client_action_id,
          kind: command.kind,
          state: command.state,
          platform_session_id: command.platform_session_id,
          hermes_session_id: command.hermes_session_id,
          hermes_run_id: command.hermes_run_id,
          occurred_at: FIXED_AT,
        });
        broadcast(state, "transcript", {
          hermes_session_id: managed.hermes_session_id,
          revision: state.cursor,
        });
        finish(200, {
          status: "accepted",
          client_action_id: body.client_action_id,
          command_id: commandId,
          payload_ref: `payload:sha256:${sha256(String(body.prompt))}`,
          payload_digest: sha256(String(body.prompt)),
          kind: "conversation.turn",
          mutation_enabled: true,
          workspace: { workspace_id: WORKSPACE_ID },
          platform_session_id: managed.platform_session_id,
          session_ref: managed.session_ref,
          hermes_session_id: managed.hermes_session_id,
        });
        return true;
      }

      return false;
    },
  };
}

export const HERMES_LIFECYCLE_FIXTURE_IDS = Object.freeze({
  activeSessionId: ACTIVE_SESSION_ID,
  approvalId: APPROVAL_ID,
  externalSessionId: EXTERNAL_SESSION_ID,
  initialCommandId: INITIAL_COMMAND_ID,
  initialRunId: INITIAL_RUN_ID,
  workspaceId: WORKSPACE_ID,
});
