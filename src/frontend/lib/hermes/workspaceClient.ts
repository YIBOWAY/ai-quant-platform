/**
 * Same-origin owner-gated workspace client for L2a-Send.
 *
 * Uses relative `/api/...` paths so Next rewrites keep Host/Origin/cookies on
 * the FE origin (required by mutation Sec-Fetch-Site + CSRF gates). Does not
 * go through apiClient (credentials: omit + absolute :8765 base).
 */

import {
  CHAT_PROMPT_MAX_BYTES,
  CSRF_COOKIE_NAME,
  CSRF_HEADER_NAME,
  MANAGED_SESSION_STORAGE_KEY,
  PAYLOAD_TTL_DAYS,
  PLATFORM_WORKSPACE_ID,
  PROVIDER_POLICY_DIGEST,
} from "./darkIdentity";
import { isUsableHermesApiSessionId } from "./transcriptHelpers";

export type ActionReceiptStatus =
  | "accepted"
  | "reconciling"
  | "conflict"
  | "unavailable"
  | "outcome_unknown";

export type WorkspaceActionReceipt = {
  status: ActionReceiptStatus;
  client_action_id: string;
  action_digest?: string;
  workspace?: { workspace_id: string };
  recovery_action?: string | null;
  mutation_enabled?: boolean;
  command_id?: string;
  run_id?: string;
  platform_session_id?: string;
  session_ref?: string;
  hermes_session_id?: string;
  reason_code?: string;
  payload_ref?: string;
  payload_digest?: string;
  kind?: string;
};

export class WorkspaceClientError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly code?: string,
  ) {
    super(message);
    this.name = "WorkspaceClientError";
  }
}

export function utf8ByteLength(text: string): number {
  return new TextEncoder().encode(text).length;
}

export function preflightPrompt(prompt: string): string {
  if (typeof prompt !== "string") {
    throw new WorkspaceClientError("prompt must be a string", 400, "validation");
  }
  if (!prompt.trim()) {
    throw new WorkspaceClientError(
      "prompt must be non-empty after stripping whitespace",
      400,
      "validation",
    );
  }
  if (utf8ByteLength(prompt) > CHAT_PROMPT_MAX_BYTES) {
    throw new WorkspaceClientError(
      "prompt exceeds 16 KiB UTF-8 chat ceiling",
      400,
      "prompt_too_large",
    );
  }
  return prompt;
}

export function readCsrfToken(
  cookieSource: string | undefined = typeof document !== "undefined"
    ? document.cookie
    : undefined,
): string | null {
  if (!cookieSource) {
    return null;
  }
  const parts = cookieSource.split(";");
  for (const part of parts) {
    const trimmed = part.trim();
    if (!trimmed) continue;
    const eq = trimmed.indexOf("=");
    if (eq <= 0) continue;
    const name = trimmed.slice(0, eq).trim();
    if (name === CSRF_COOKIE_NAME) {
      const value = trimmed.slice(eq + 1).trim();
      return value ? decodeURIComponent(value) : null;
    }
  }
  return null;
}

async function parseError(response: Response): Promise<WorkspaceClientError> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (payload.detail && typeof payload.detail === "object") {
      const detail = payload.detail as Record<string, unknown>;
      const message =
        typeof detail.message === "string"
          ? detail.message
          : response.statusText || "workspace request failed";
      const code = typeof detail.code === "string" ? detail.code : undefined;
      return new WorkspaceClientError(message, response.status, code);
    }
    if (typeof payload.detail === "string") {
      return new WorkspaceClientError(payload.detail, response.status);
    }
  } catch {
    // fall through
  }
  return new WorkspaceClientError(
    response.statusText || "workspace request failed",
    response.status,
  );
}

type SameOriginInit = {
  method?: string;
  body?: unknown;
  csrf?: boolean;
  signal?: AbortSignal;
};

async function sameOriginJson<T>(path: string, init: SameOriginInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    accept: "application/json",
  };
  if (init.body !== undefined) {
    headers["content-type"] = "application/json";
  }
  if (init.csrf) {
    const csrf = readCsrfToken();
    if (!csrf) {
      throw new WorkspaceClientError(
        "owner CSRF cookie missing; bootstrap required",
        401,
        "auth",
      );
    }
    headers[CSRF_HEADER_NAME] = csrf;
  }

  const response = await fetch(path, {
    method: init.method ?? (init.body !== undefined ? "POST" : "GET"),
    credentials: "same-origin",
    headers,
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    signal: init.signal,
  });

  if (!response.ok) {
    throw await parseError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export type OwnerSessionView = {
  session_id?: string;
  mutation_enabled?: boolean;
  security_ready?: boolean;
  csrf_token?: string;
  csrf_header?: string;
};

/** GET session; returns null when unauthenticated (401/403). */
export async function getOwnerSession(
  signal?: AbortSignal,
): Promise<OwnerSessionView | null> {
  try {
    return await sameOriginJson<OwnerSessionView>("/api/auth/owner/session", {
      method: "GET",
      signal,
    });
  } catch (error) {
    if (
      error instanceof WorkspaceClientError &&
      (error.status === 401 || error.status === 403)
    ) {
      return null;
    }
    throw error;
  }
}

/**
 * Ensure owner loopback session exists.
 * Uses operator helper issue → one-time bootstrap exchange when no cookie yet.
 */
export async function ensureOwnerSession(
  signal?: AbortSignal,
): Promise<OwnerSessionView> {
  const existing = await getOwnerSession(signal);
  if (existing?.session_id) {
    return existing;
  }

  const issued = await sameOriginJson<{ bootstrap_token: string }>(
    "/api/auth/owner/bootstrap-token/issue",
    { method: "POST", signal },
  );
  if (!issued.bootstrap_token) {
    throw new WorkspaceClientError(
      "bootstrap token issue returned empty token",
      503,
      "unavailable",
    );
  }

  const bootstrapped = await sameOriginJson<OwnerSessionView>(
    "/api/auth/owner/bootstrap",
    {
      method: "POST",
      body: { bootstrap_token: issued.bootstrap_token },
      // Bootstrap is the cookie mint; CSRF not yet established.
      signal,
    },
  );
  if (!bootstrapped.session_id && !readCsrfToken()) {
    throw new WorkspaceClientError(
      "owner bootstrap did not establish session cookies",
      503,
      "unavailable",
    );
  }
  return bootstrapped;
}

function sessionStorageOrMemory(): Storage | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function loadManagedSessionRef(
  workspaceId: string = PLATFORM_WORKSPACE_ID,
): string | null {
  const store = sessionStorageOrMemory();
  if (!store) return null;
  const raw = store.getItem(`${MANAGED_SESSION_STORAGE_KEY}:${workspaceId}`);
  return raw && raw.startsWith("session:") ? raw : null;
}

export function saveManagedSessionRef(
  sessionRef: string,
  workspaceId: string = PLATFORM_WORKSPACE_ID,
): void {
  const store = sessionStorageOrMemory();
  if (!store) return;
  store.setItem(`${MANAGED_SESSION_STORAGE_KEY}:${workspaceId}`, sessionRef);
}

export async function createManagedSession(options?: {
  workspaceId?: string;
  clientActionId?: string;
  signal?: AbortSignal;
}): Promise<WorkspaceActionReceipt> {
  const workspaceId = options?.workspaceId ?? PLATFORM_WORKSPACE_ID;
  const clientActionId = options?.clientActionId ?? crypto.randomUUID();
  const receipt = await sameOriginJson<WorkspaceActionReceipt>(
    `/api/workspace/${encodeURIComponent(workspaceId)}/act`,
    {
      method: "POST",
      csrf: true,
      signal: options?.signal,
      body: {
        action: {
          schema_version: 1,
          kind: "managed_session.create",
          client_action_id: clientActionId,
          workspace: { workspace_id: workspaceId },
          provider_policy_digest: PROVIDER_POLICY_DIGEST,
          payload_ttl_days: PAYLOAD_TTL_DAYS,
        },
      },
    },
  );
  const sessionRef =
    receipt.session_ref ??
    (receipt.platform_session_id
      ? `session:${receipt.platform_session_id}`
      : null);
  if (sessionRef) {
    saveManagedSessionRef(sessionRef, workspaceId);
  }
  return receipt;
}

/** Ensure a managed session exists; create via /act when storage is empty. */
export async function ensureManagedSession(options?: {
  workspaceId?: string;
  signal?: AbortSignal;
}): Promise<string> {
  const workspaceId = options?.workspaceId ?? PLATFORM_WORKSPACE_ID;
  const existing = loadManagedSessionRef(workspaceId);
  if (existing) {
    return existing;
  }
  const receipt = await createManagedSession({
    workspaceId,
    signal: options?.signal,
  });
  const sessionRef =
    receipt.session_ref ??
    (receipt.platform_session_id
      ? `session:${receipt.platform_session_id}`
      : null);
  if (!sessionRef) {
    throw new WorkspaceClientError(
      receipt.reason_code ||
        `managed session create returned status=${receipt.status}`,
      503,
      receipt.status,
    );
  }
  if (receipt.status !== "accepted" && receipt.status !== "reconciling") {
    throw new WorkspaceClientError(
      receipt.reason_code ||
        `managed session create returned status=${receipt.status}`,
      receipt.status === "conflict" ? 409 : 503,
      receipt.status,
    );
  }
  return sessionRef;
}

export async function submitTurn(options: {
  prompt: string;
  clientActionId?: string;
  managedSessionRef?: string;
  workspaceId?: string;
  signal?: AbortSignal;
}): Promise<WorkspaceActionReceipt> {
  const prompt = preflightPrompt(options.prompt);
  const workspaceId = options.workspaceId ?? PLATFORM_WORKSPACE_ID;
  const managedSessionRef =
    options.managedSessionRef ?? (await ensureManagedSession({ workspaceId, signal: options.signal }));
  const clientActionId = options.clientActionId ?? crypto.randomUUID();

  return sameOriginJson<WorkspaceActionReceipt>(
    "/api/agent/workspace/submit-turn",
    {
      method: "POST",
      csrf: true,
      signal: options.signal,
      body: {
        workspace_id: workspaceId,
        managed_session_ref: managedSessionRef,
        client_action_id: clientActionId,
        prompt,
      },
    },
  );
}

/**
 * Full L2a send: owner bootstrap → create session if needed → submit-turn.
 * One client_action_id per call; retries of outcome_unknown should pass the same id.
 */
export async function sendComposerTurn(options: {
  prompt: string;
  clientActionId?: string;
  signal?: AbortSignal;
}): Promise<WorkspaceActionReceipt> {
  preflightPrompt(options.prompt);
  await ensureOwnerSession(options.signal);
  const clientActionId = options.clientActionId ?? crypto.randomUUID();
  const managedSessionRef = await ensureManagedSession({ signal: options.signal });
  return submitTurn({
    prompt: options.prompt,
    clientActionId,
    managedSessionRef,
    signal: options.signal,
  });
}

export type WorkspaceCommandProjection = {
  command_id: string;
  kind: string;
  state: string;
  version: number;
  client_request_id?: string;
  client_action_id?: string;
  platform_session_id?: string;
  hermes_session_id?: string | null;
  hermes_run_id?: string | null;
  last_error_code?: string | null;
  attempt_count?: number;
  updated_at?: string | null;
  created_at?: string | null;
};

/** L5a: Hermes command-approval challenge projection (observe-only). */
export type WorkspaceApprovalProjection = {
  approval_id: string;
  run_id?: string | null;
  command_id?: string | null;
  /** Canonical command digest bound to the challenge (plan §5.4). */
  digest?: string | null;
  expires_at?: string | null;
  expected_status?: string | null;
  status?: string | null;
  kind?: string | null;
};

export type WorkspaceSnapshot = {
  workspace?: { workspace_id: string };
  owner_user_id?: string;
  snapshot_workspace_cursor?: number;
  sessions?: string[];
  commands?: WorkspaceCommandProjection[];
  /** L5b: HQA Task authority ids/objects; empty until projector. */
  tasks?: string[];
  /** L5b: Attempt authority ids/objects; empty until projector. */
  attempts?: string[];
  /** L5b: Run authority ids/objects; empty until projector. */
  runs?: string[];
  /** L5b: result-ref ids/objects; empty until projector. */
  results?: string[];
  /** L5a: Hermes command-approval challenges; empty until durable projector. */
  approvals?: WorkspaceApprovalProjection[];
  authority_health?: Record<string, string>;
  mutation_enabled?: boolean;
  observed_at?: string;
};

export type WorkspaceFollowEvent = {
  event_id: number;
  type: string;
  event_type?: string;
  command_id: string;
  command_version?: number;
  client_request_id?: string | null;
  client_action_id?: string | null;
  kind?: string | null;
  platform_session_id?: string | null;
  from_state?: string | null;
  state?: string | null;
  hermes_session_id?: string | null;
  hermes_run_id?: string | null;
  error_code?: string | null;
  occurred_at?: string | null;
};

export type WorkspaceEventPage = {
  events: WorkspaceFollowEvent[];
  after_cursor: number | null;
  next_cursor: number | null;
  resync_required: boolean;
  recovery_action?: string | null;
  mutation_enabled?: boolean;
};

export async function fetchWorkspaceSnapshot(
  workspaceId: string = PLATFORM_WORKSPACE_ID,
  signal?: AbortSignal,
): Promise<WorkspaceSnapshot> {
  return sameOriginJson<WorkspaceSnapshot>(
    `/api/workspace/${encodeURIComponent(workspaceId)}/snapshot`,
    { method: "GET", signal },
  );
}

/** Poll durable workspace observation page (L2b-M1; not SSE). */
export async function fetchWorkspaceFollow(options?: {
  workspaceId?: string;
  afterCursor?: number | null;
  signal?: AbortSignal;
}): Promise<WorkspaceEventPage> {
  const workspaceId = options?.workspaceId ?? PLATFORM_WORKSPACE_ID;
  const params = new URLSearchParams();
  if (
    options?.afterCursor !== undefined &&
    options?.afterCursor !== null &&
    Number.isFinite(options.afterCursor)
  ) {
    params.set("after_cursor", String(Math.max(0, Math.floor(options.afterCursor))));
  }
  const query = params.toString();
  const path = `/api/workspace/${encodeURIComponent(workspaceId)}/follow${
    query ? `?${query}` : ""
  }`;
  return sameOriginJson<WorkspaceEventPage>(path, {
    method: "GET",
    signal: options?.signal,
  });
}

const TERMINAL_COMMAND_STATES = new Set([
  "delivered",
  "cancelled",
  "failed",
  "rejected",
  "timed_out",
  "outcome_unknown",
]);

export function isTerminalCommandState(state: string | null | undefined): boolean {
  return typeof state === "string" && TERMINAL_COMMAND_STATES.has(state);
}

/**
 * Poll follow until the target command reaches a terminal state or attempts exhaust.
 * Returns last known state string (or null if never observed).
 */
export type CommandTerminalPollResult = {
  state: string | null;
  hermesRunId: string | null;
  hermesSessionId: string | null;
  cursor: number | null;
  events: WorkspaceFollowEvent[];
  resyncRequired: boolean;
};

export async function pollCommandUntilTerminal(options: {
  commandId: string;
  workspaceId?: string;
  afterCursor?: number | null;
  maxAttempts?: number;
  intervalMs?: number;
  signal?: AbortSignal;
}): Promise<CommandTerminalPollResult> {
  const maxAttempts = options.maxAttempts ?? 40;
  const intervalMs = options.intervalMs ?? 500;
  let cursor =
    options.afterCursor === undefined || options.afterCursor === null
      ? 0
      : options.afterCursor;
  let state: string | null = null;
  let hermesRunId: string | null = null;
  let hermesSessionId: string | null = null;
  const seen: WorkspaceFollowEvent[] = [];
  let resyncRequired = false;

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (options.signal?.aborted) {
      break;
    }
    const page = await fetchWorkspaceFollow({
      workspaceId: options.workspaceId,
      afterCursor: cursor,
      signal: options.signal,
    });
    if (page.resync_required) {
      resyncRequired = true;
      // Resnapshot cursor then continue from 0 so we do not invent holes.
      try {
        const snap = await fetchWorkspaceSnapshot(
          options.workspaceId ?? PLATFORM_WORKSPACE_ID,
          options.signal,
        );
        const match = (snap.commands ?? []).find(
          (c) => c.command_id === options.commandId,
        );
        if (match) {
          state = match.state;
          hermesRunId = match.hermes_run_id ?? hermesRunId;
          hermesSessionId = match.hermes_session_id ?? hermesSessionId;
          if (isTerminalCommandState(state)) {
            return {
              state,
              hermesRunId,
              hermesSessionId,
              cursor: snap.snapshot_workspace_cursor ?? cursor,
              events: seen,
              resyncRequired,
            };
          }
        }
        cursor = snap.snapshot_workspace_cursor ?? 0;
      } catch {
        cursor = 0;
      }
    } else {
      for (const event of page.events ?? []) {
        seen.push(event);
        if (event.command_id === options.commandId) {
          if (typeof event.state === "string") {
            state = event.state;
          }
          if (event.hermes_run_id) {
            hermesRunId = event.hermes_run_id;
          }
          if (event.hermes_session_id) {
            hermesSessionId = event.hermes_session_id;
          }
        }
      }
      if (page.next_cursor !== null && page.next_cursor !== undefined) {
        cursor = page.next_cursor;
      }
      if (isTerminalCommandState(state)) {
        return {
          state,
          hermesRunId,
          hermesSessionId,
          cursor,
          events: seen,
          resyncRequired,
        };
      }
    }

    await new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, intervalMs);
      if (options.signal) {
        const onAbort = () => {
          clearTimeout(timer);
          resolve();
        };
        options.signal.addEventListener("abort", onAbort, { once: true });
      }
    });
  }

  return {
    state,
    hermesRunId,
    hermesSessionId,
    cursor,
    events: seen,
    resyncRequired,
  };
}

/** Hermes gateway message row (loopback read path). */
export type HermesSessionMessage = {
  id: string;
  role: "user" | "assistant" | string;
  content: string;
  timestamp?: string | null;
};

export type HermesSessionMessagesView = {
  read_status: "available" | "unavailable" | string;
  session_id: string;
  messages: HermesSessionMessage[];
  omitted_message_count?: number;
  warnings?: unknown[];
};

/**
 * Pick the latest non-empty assistant message body from a gateway envelope.
 * Pure helper — no I/O. Returns null when none present.
 */
export function latestAssistantText(
  envelope:
    | HermesSessionMessagesView
    | { messages?: HermesSessionMessage[] | null }
    | null
    | undefined,
): string | null {
  const messages = envelope?.messages;
  if (!Array.isArray(messages) || messages.length === 0) {
    return null;
  }
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const row = messages[i];
    if (!row || row.role !== "assistant") continue;
    if (typeof row.content !== "string") continue;
    const text = row.content.trim();
    if (text) return text;
  }
  return null;
}

/** Collapse whitespace and truncate for composer status line. */
export function previewAssistantText(
  text: string,
  maxChars: number = 160,
): string {
  const collapsed = text.replace(/\s+/g, " ").trim();
  if (collapsed.length <= maxChars) return collapsed;
  if (maxChars <= 1) return "…";
  return `${collapsed.slice(0, Math.max(1, maxChars - 1))}…`;
}

/**
 * L2b-M2: same-origin fetch of Hermes session messages.
 * Reuses existing BFF `GET /api/hermes/sessions/{id}/messages` (loopback socket).
 * Does not go through api.ts (absolute :8765 + credentials omit).
 */
export async function fetchHermesSessionMessages(
  sessionId: string,
  signal?: AbortSignal,
): Promise<HermesSessionMessagesView> {
  if (!isUsableHermesApiSessionId(sessionId)) {
    throw new WorkspaceClientError(
      "hermes session id required (reject web_/wm_/empty)",
      400,
      "validation",
    );
  }
  return sameOriginJson<HermesSessionMessagesView>(
    `/api/hermes/sessions/${encodeURIComponent(sessionId.trim())}/messages`,
    { method: "GET", signal },
  );
}

/**
 * After deliver: resolve latest assistant text for a Hermes session.
 * Returns null on unavailable / empty / network blip (caller keeps lifecycle status).
 */
export async function fetchLatestAssistantText(options: {
  hermesSessionId: string;
  signal?: AbortSignal;
}): Promise<string | null> {
  try {
    const envelope = await fetchHermesSessionMessages(
      options.hermesSessionId,
      options.signal,
    );
    if (envelope.read_status && envelope.read_status !== "available") {
      return null;
    }
    return latestAssistantText(envelope);
  } catch {
    return null;
  }
}
