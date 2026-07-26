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
import type { WorkspacePublicCutoverResponse } from "../api";

export { PLATFORM_WORKSPACE_ID };
export type { WorkspacePublicCutoverResponse } from "../api";

export type ActionReceiptStatus =
  "accepted" | "reconciling" | "conflict" | "unavailable" | "outcome_unknown";

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
  /** V7g-A-M1 hermetic vertical bind outcome (optional). */
  task_id?: string;
  attempt_id?: string;
  result_id?: string;
  terminal_status?: string;
  gate_id?: string;
  task_version?: number;
  gate1_confirmation_id?: string;
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
    throw new WorkspaceClientError(
      "prompt must be a string",
      400,
      "validation",
    );
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

async function sameOriginJson<T>(
  path: string,
  init: SameOriginInit = {},
): Promise<T> {
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

const OWNER_BOOTSTRAP_INSTRUCTION =
  "Owner session required. Run `quant-system owner-bootstrap-token` in the backend terminal, then paste the one-time token here.";

export async function bootstrapOwnerSession(
  bootstrapToken: string,
  signal?: AbortSignal,
): Promise<OwnerSessionView> {
  const token = bootstrapToken.trim();
  if (token.length < 32 || token.length > 256) {
    throw new WorkspaceClientError(
      "owner bootstrap token must be 32-256 characters",
      422,
      "validation",
    );
  }
  const bootstrapped = await sameOriginJson<OwnerSessionView>(
    "/api/auth/owner/bootstrap",
    {
      method: "POST",
      body: { bootstrap_token: token },
      // Bootstrap is the cookie mint; CSRF is not established yet.
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

/**
 * Ensure an owner loopback session exists. First bootstrap is an explicit
 * operator action: the browser never asks an unauthenticated HTTP route to
 * disclose the owner-only token file.
 */
export async function ensureOwnerSession(
  signal?: AbortSignal,
): Promise<OwnerSessionView> {
  const existing = await getOwnerSession(signal);
  if (existing?.session_id) {
    return existing;
  }

  const presented =
    typeof window !== "undefined" && typeof window.prompt === "function"
      ? window.prompt(OWNER_BOOTSTRAP_INSTRUCTION)
      : null;
  if (!presented) {
    throw new WorkspaceClientError(
      OWNER_BOOTSTRAP_INSTRUCTION,
      401,
      "owner_bootstrap_required",
    );
  }
  return bootstrapOwnerSession(presented, signal);
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

/**
 * Resolve the composer selection synchronously at click time. A deep-link is
 * read from the live URL so React effect timing can never turn it into the
 * "no active session" create/recover path.
 */
export function resolveComposerHermesSessionId(
  activeHermesSessionId?: string | null,
  locationSearch?: string,
): string | null {
  const search =
    locationSearch ??
    (typeof window !== "undefined" &&
    typeof window.location?.search === "string"
      ? window.location.search
      : "");
  const deepLinkValues = new URLSearchParams(search).getAll(
    "hermes_session_id",
  );
  if (deepLinkValues.length > 1) {
    throw new WorkspaceClientError(
      "multiple Hermes session deep-links are ambiguous",
      400,
      "composer_session_selection_ambiguous",
    );
  }
  const deepLinkedHermesSessionId = deepLinkValues[0] ?? null;
  if (
    deepLinkedHermesSessionId != null &&
    (deepLinkedHermesSessionId !== deepLinkedHermesSessionId.trim() ||
      !isUsableHermesApiSessionId(deepLinkedHermesSessionId))
  ) {
    throw new WorkspaceClientError(
      "Hermes session deep-link is invalid",
      400,
      "composer_session_deep_link_invalid",
    );
  }
  if (
    activeHermesSessionId != null &&
    (activeHermesSessionId !== activeHermesSessionId.trim() ||
      !isUsableHermesApiSessionId(activeHermesSessionId))
  ) {
    throw new WorkspaceClientError(
      "active Hermes session is invalid",
      400,
      "active_hermes_session_invalid",
    );
  }
  if (
    deepLinkedHermesSessionId != null &&
    activeHermesSessionId != null &&
    deepLinkedHermesSessionId !== activeHermesSessionId
  ) {
    throw new WorkspaceClientError(
      "active transcript and Hermes session deep-link disagree; wait for the selected session to bind before sending",
      409,
      "composer_session_selection_mismatch",
    );
  }
  return deepLinkedHermesSessionId ?? activeHermesSessionId ?? null;
}

/** Keep receipt/follow observations pinned to the submitted Hermes Session. */
export function requireSameComposerHermesSession(
  selectedHermesSessionId: string | null | undefined,
  observedHermesSessionId?: string | null,
): string {
  if (
    selectedHermesSessionId == null ||
    selectedHermesSessionId !== selectedHermesSessionId.trim() ||
    !isUsableHermesApiSessionId(selectedHermesSessionId)
  ) {
    throw new WorkspaceClientError(
      "selected managed Hermes session identity is missing",
      503,
      "composer_selected_session_missing",
    );
  }
  if (
    observedHermesSessionId != null &&
    (observedHermesSessionId !== observedHermesSessionId.trim() ||
      !isUsableHermesApiSessionId(observedHermesSessionId) ||
      observedHermesSessionId !== selectedHermesSessionId)
  ) {
    throw new WorkspaceClientError(
      "command follow observation does not match the submitted Hermes session",
      503,
      "composer_follow_session_mismatch",
    );
  }
  return selectedHermesSessionId;
}

const MANAGED_SESSION_PROVISION_STATES = new Set<ManagedSessionProvisionState>([
  "pending",
  "leased",
  "retryable",
  "ready",
  "failed",
]);

function assertManagedSessionProjectionIdentity(
  projection: ManagedSessionProjection,
): void {
  const platformId = projection?.platform_session_id?.trim();
  const sessionRef = projection?.session_ref?.trim();
  if (
    !platformId ||
    !platformId.startsWith("wm_") ||
    sessionRef !== `session:${platformId}` ||
    !MANAGED_SESSION_PROVISION_STATES.has(projection.provision_state) ||
    !Number.isInteger(projection.attempt_count) ||
    projection.attempt_count < 0
  ) {
    throw new WorkspaceClientError(
      "latest managed session projection is internally inconsistent",
      503,
      "managed_session_projection_invalid",
    );
  }
}

function managedSessionProjectionIsReady(
  projection: ManagedSessionProjection,
): boolean {
  if (projection.provision_state !== "ready") {
    return false;
  }
  if (
    projection.web_writable !== true ||
    !isUsableHermesApiSessionId(projection.hermes_session_id)
  ) {
    throw new WorkspaceClientError(
      "managed session ready projection is internally inconsistent",
      503,
      "managed_session_ready_contract_invalid",
    );
  }
  return true;
}

/**
 * Snapshot rows are emitted oldest-first by the current workspace contract.
 * Never skip a malformed newest row and silently resume an older lineage.
 */
export function latestManagedSessionProjection(
  snapshot: Pick<WorkspaceSnapshot, "managed_sessions">,
): ManagedSessionProjection | null {
  if (!Array.isArray(snapshot.managed_sessions)) {
    throw new WorkspaceClientError(
      "managed session projection is unavailable; refusing duplicate create",
      503,
      "managed_session_projection_unavailable",
    );
  }
  const latest = snapshot.managed_sessions.at(-1) ?? null;
  if (!latest) {
    return null;
  }
  assertManagedSessionProjectionIdentity(latest);
  return latest;
}

/**
 * Resolve one already-selected Hermes Session to its unique managed Web row.
 * This path never consults sessionStorage, selects "latest", or creates a
 * replacement lineage: observed external/history sessions require a fork.
 */
export async function resolveManagedSessionForHermesSession(options: {
  hermesSessionId: string;
  workspaceId?: string;
  signal?: AbortSignal;
}): Promise<ManagedSessionProjection> {
  const hermesSessionId = options.hermesSessionId;
  const workspaceId = options.workspaceId ?? PLATFORM_WORKSPACE_ID;
  if (
    hermesSessionId !== hermesSessionId.trim() ||
    !isUsableHermesApiSessionId(hermesSessionId)
  ) {
    throw new WorkspaceClientError(
      "active Hermes session id is invalid",
      400,
      "active_hermes_session_invalid",
    );
  }

  const snapshot = await fetchWorkspaceSnapshot(workspaceId, options.signal);
  if (!Array.isArray(snapshot.managed_sessions)) {
    throw new WorkspaceClientError(
      "managed session projection is unavailable; refusing session fallback",
      503,
      "managed_session_projection_unavailable",
    );
  }
  const matches = snapshot.managed_sessions.filter(
    (projection) => projection.hermes_session_id === hermesSessionId,
  );
  if (matches.length === 0) {
    throw new WorkspaceClientError(
      "This Hermes session is read-only in Web. Explicitly fork it to a managed session before sending.",
      409,
      "managed_session_explicit_fork_required",
    );
  }
  if (matches.length !== 1) {
    throw new WorkspaceClientError(
      "active Hermes session maps to multiple managed session references",
      503,
      "managed_session_identity_ambiguous",
    );
  }

  const matched = matches[0];
  assertManagedSessionProjectionIdentity(matched);
  const ready = managedSessionProjectionIsReady(matched)
    ? matched
    : await waitForManagedSessionReady({
        workspaceId,
        sessionRef: matched.session_ref,
        signal: options.signal,
      });
  if (ready.hermes_session_id !== hermesSessionId) {
    throw new WorkspaceClientError(
      "managed session identity changed while waiting for readiness",
      503,
      "managed_session_identity_changed",
    );
  }
  saveManagedSessionRef(ready.session_ref, workspaceId);
  return ready;
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

/**
 * Ensure a managed session exists. Restore the newest server-authoritative
 * lineage first; create only after a healthy, explicitly empty projection.
 */
export async function ensureManagedSession(options?: {
  workspaceId?: string;
  signal?: AbortSignal;
  provisionTimeoutMs?: number;
  provisionInitialIntervalMs?: number;
}): Promise<ManagedSessionProjection> {
  const workspaceId = options?.workspaceId ?? PLATFORM_WORKSPACE_ID;
  const existing = loadManagedSessionRef(workspaceId);
  if (existing) {
    return waitForManagedSessionReady({
      workspaceId,
      sessionRef: existing,
      signal: options?.signal,
      timeoutMs: options?.provisionTimeoutMs,
      initialIntervalMs: options?.provisionInitialIntervalMs,
    });
  }
  const snapshot = await fetchWorkspaceSnapshot(workspaceId, options?.signal);
  if (snapshot.authority_health?.session_registry !== "ready") {
    throw new WorkspaceClientError(
      "managed session registry is unavailable; refusing duplicate create",
      503,
      "managed_session_registry_unavailable",
    );
  }
  const recovered = latestManagedSessionProjection(snapshot);
  if (recovered) {
    saveManagedSessionRef(recovered.session_ref, workspaceId);
    if (managedSessionProjectionIsReady(recovered)) {
      return recovered;
    }
    return waitForManagedSessionReady({
      workspaceId,
      sessionRef: recovered.session_ref,
      signal: options?.signal,
      timeoutMs: options?.provisionTimeoutMs,
      initialIntervalMs: options?.provisionInitialIntervalMs,
    });
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
  return waitForManagedSessionReady({
    workspaceId,
    sessionRef,
    signal: options?.signal,
    timeoutMs: options?.provisionTimeoutMs,
    initialIntervalMs: options?.provisionInitialIntervalMs,
  });
}

export type ForkHermesSessionResult = {
  receipt: WorkspaceActionReceipt;
  managedSession: ManagedSessionProjection;
};

/**
 * Explicitly fork one authoritative Hermes message into a new managed Web
 * session. Source identity/channel/TTL remain server-owned. The browser must
 * explicitly confirm and send the one admitted immutable provider policy.
 */
export async function forkHermesSessionToManaged(options: {
  hermesSessionId: string;
  clientActionId: string;
  forkPoint: string;
  newProviderPolicyDigest: string;
  signal?: AbortSignal;
  provisionTimeoutMs?: number;
  provisionInitialIntervalMs?: number;
  onReceipt?: (receipt: WorkspaceActionReceipt) => void;
}): Promise<ForkHermesSessionResult> {
  const hermesSessionId = options.hermesSessionId;
  const clientActionId = options.clientActionId;
  const forkPoint = options.forkPoint;
  const newProviderPolicyDigest = options.newProviderPolicyDigest;
  if (
    hermesSessionId !== hermesSessionId.trim() ||
    !isUsableHermesApiSessionId(hermesSessionId)
  ) {
    throw new WorkspaceClientError(
      "valid Hermes session id required",
      400,
      "validation",
    );
  }
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(clientActionId)) {
    throw new WorkspaceClientError(
      "valid fork client_action_id required",
      400,
      "validation",
    );
  }
  if (!/^message:[1-9][0-9]*$/.test(forkPoint)) {
    throw new WorkspaceClientError(
      "authoritative message:<positive-integer> fork point required",
      400,
      "validation",
    );
  }
  if (newProviderPolicyDigest !== PROVIDER_POLICY_DIGEST) {
    throw new WorkspaceClientError(
      "selected provider policy is not admitted for managed Web sessions",
      409,
      "provider_policy_not_admitted",
    );
  }

  await ensureOwnerSession(options.signal);
  const receipt = await sameOriginJson<WorkspaceActionReceipt>(
    `/api/hermes/sessions/${encodeURIComponent(
      hermesSessionId,
    )}/forks-to-managed`,
    {
      method: "POST",
      csrf: true,
      signal: options.signal,
      body: {
        client_action_id: clientActionId,
        fork_point: forkPoint,
        new_provider_policy_digest: newProviderPolicyDigest,
      },
    },
  );
  if (receipt.client_action_id !== clientActionId) {
    throw new WorkspaceClientError(
      "fork receipt does not match the immutable attempt",
      503,
      "fork_receipt_identity_mismatch",
    );
  }
  if (receipt.workspace?.workspace_id !== PLATFORM_WORKSPACE_ID) {
    throw new WorkspaceClientError(
      "fork receipt does not match the local managed workspace",
      503,
      "fork_receipt_workspace_mismatch",
    );
  }
  if (receipt.status !== "accepted" && receipt.status !== "reconciling") {
    throw new WorkspaceClientError(
      receipt.reason_code || `fork returned status=${receipt.status}`,
      receipt.status === "conflict" ? 409 : 503,
      receipt.status,
    );
  }
  const sessionRef = receipt.session_ref;
  if (
    !sessionRef ||
    sessionRef !== sessionRef.trim() ||
    !sessionRef.startsWith("session:wm_") ||
    (receipt.platform_session_id != null &&
      sessionRef !== `session:${receipt.platform_session_id}`)
  ) {
    throw new WorkspaceClientError(
      "fork receipt is missing an exact managed session reference",
      503,
      "fork_receipt_session_ref_invalid",
    );
  }

  options.onReceipt?.(receipt);
  // Persist the exact lineage before a bounded observation can time out.
  saveManagedSessionRef(sessionRef, PLATFORM_WORKSPACE_ID);
  const managedSession = await waitForManagedSessionReady({
    workspaceId: PLATFORM_WORKSPACE_ID,
    sessionRef,
    signal: options.signal,
    timeoutMs: options.provisionTimeoutMs,
    initialIntervalMs: options.provisionInitialIntervalMs,
  });
  if (
    managedSession.session_ref !== sessionRef ||
    managedSession.fork_point !== forkPoint ||
    !managedSession.parent_session_ref?.startsWith("session:")
  ) {
    throw new WorkspaceClientError(
      "ready managed session does not preserve the requested fork lineage",
      503,
      "managed_session_fork_lineage_invalid",
    );
  }
  saveManagedSessionRef(sessionRef, PLATFORM_WORKSPACE_ID);
  return { receipt, managedSession };
}

async function submitReadyTurn(
  options: {
    prompt: string;
    clientActionId?: string;
    workspaceId?: string;
    signal?: AbortSignal;
  },
  managedSession: ManagedSessionProjection,
): Promise<WorkspaceActionReceipt> {
  const prompt = preflightPrompt(options.prompt);
  const workspaceId = options.workspaceId ?? PLATFORM_WORKSPACE_ID;
  const clientActionId = options.clientActionId ?? crypto.randomUUID();
  const receipt = await sameOriginJson<WorkspaceActionReceipt>(
    "/api/agent/workspace/submit-turn",
    {
      method: "POST",
      csrf: true,
      signal: options.signal,
      body: {
        workspace_id: workspaceId,
        managed_session_ref: managedSession.session_ref,
        client_action_id: clientActionId,
        prompt,
      },
    },
  );
  if (
    (receipt.session_ref != null &&
      receipt.session_ref !== managedSession.session_ref) ||
    (receipt.platform_session_id != null &&
      receipt.platform_session_id !== managedSession.platform_session_id) ||
    (receipt.hermes_session_id != null &&
      receipt.hermes_session_id !== managedSession.hermes_session_id)
  ) {
    throw new WorkspaceClientError(
      "submit receipt does not match the selected managed Hermes session",
      503,
      "composer_receipt_session_mismatch",
    );
  }
  return receipt.hermes_session_id
    ? receipt
    : {
        ...receipt,
        // The snapshot only admits this identity after exact provisioning
        // reached ready, so the transcript can bind immediately without
        // treating the platform-only wm_* reference as a Hermes Session.
        hermes_session_id: managedSession.hermes_session_id,
      };
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
  const managedSession = options.managedSessionRef
    ? await waitForManagedSessionReady({
        workspaceId,
        sessionRef: options.managedSessionRef,
        signal: options.signal,
      })
    : await ensureManagedSession({ workspaceId, signal: options.signal });
  return submitReadyTurn(
    {
      prompt,
      clientActionId: options.clientActionId,
      workspaceId,
      signal: options.signal,
    },
    managedSession,
  );
}

/**
 * Full L2a send: owner bootstrap → create session if needed → submit-turn.
 * One client_action_id per call; retries of outcome_unknown should pass the same id.
 */
export async function sendComposerTurn(options: {
  prompt: string;
  clientActionId?: string;
  activeHermesSessionId: string | null | undefined;
  signal?: AbortSignal;
}): Promise<WorkspaceActionReceipt> {
  preflightPrompt(options.prompt);
  // Capture the selection before the first await so navigation/effect timing
  // cannot change which transcript this click targets.
  const selectedHermesSessionId = resolveComposerHermesSessionId(
    options.activeHermesSessionId,
  );
  await ensureOwnerSession(options.signal);
  const clientActionId = options.clientActionId ?? crypto.randomUUID();
  const managedSession =
    selectedHermesSessionId != null
      ? await resolveManagedSessionForHermesSession({
          hermesSessionId: selectedHermesSessionId,
          signal: options.signal,
        })
      : await ensureManagedSession({ signal: options.signal });
  return submitReadyTurn(
    {
      prompt: options.prompt,
      clientActionId,
      signal: options.signal,
    },
    managedSession,
  );
}

/**
 * V7a-Hermes-Approval-Decide-M1: exact single-use allow_once|deny via /act.
 * Binds approval_ref + run_ref + command_digest + expected_status=pending +
 * expected_expires_at. No always-allow. Owner gate + CSRF required.
 * ≠ Gate 1/2/3, ≠ /hermes/approvals candidate page.
 */
export type DecideHermesCommandApprovalInput = {
  approvalId: string;
  runId: string;
  commandDigest: string;
  expectedExpiresAt: string;
  decision: "allow_once" | "deny";
  clientActionId?: string;
  workspaceId?: string;
  signal?: AbortSignal;
};

export function buildDecideApprovalAction(input: {
  approvalId: string;
  runId: string;
  commandDigest: string;
  expectedExpiresAt: string;
  decision: "allow_once" | "deny";
  clientActionId: string;
  workspaceId: string;
}): Record<string, unknown> {
  const approvalId = input.approvalId.startsWith("approval:")
    ? input.approvalId.slice("approval:".length)
    : input.approvalId;
  const runId = input.runId.startsWith("run:")
    ? input.runId.slice("run:".length)
    : input.runId;
  if (!/^[0-9a-f]{64}$/.test(input.commandDigest)) {
    throw new WorkspaceClientError(
      "command_digest must be lowercase SHA-256",
      400,
      "validation",
    );
  }
  if (input.decision !== "allow_once" && input.decision !== "deny") {
    throw new WorkspaceClientError(
      "decision must be allow_once or deny",
      400,
      "validation",
    );
  }
  return {
    schema_version: 1,
    kind: "hermes.command_approval.decide",
    client_action_id: input.clientActionId,
    workspace: { workspace_id: input.workspaceId },
    approval_ref: `approval:${approvalId}`,
    run_ref: `run:${runId}`,
    command_digest: input.commandDigest,
    expected_status: "pending",
    expected_expires_at: input.expectedExpiresAt,
    decision: input.decision,
  };
}

export async function decideHermesCommandApproval(
  options: DecideHermesCommandApprovalInput,
): Promise<WorkspaceActionReceipt> {
  await ensureOwnerSession(options.signal);
  const workspaceId = options.workspaceId ?? PLATFORM_WORKSPACE_ID;
  const clientActionId = options.clientActionId ?? crypto.randomUUID();
  const action = buildDecideApprovalAction({
    approvalId: options.approvalId,
    runId: options.runId,
    commandDigest: options.commandDigest,
    expectedExpiresAt: options.expectedExpiresAt,
    decision: options.decision,
    clientActionId,
    workspaceId,
  });
  return sameOriginJson<WorkspaceActionReceipt>(
    `/api/workspace/${encodeURIComponent(workspaceId)}/act`,
    {
      method: "POST",
      csrf: true,
      signal: options.signal,
      body: { action },
    },
  );
}

export type RequestHermesRunStopInput = {
  runId: string;
  clientActionId?: string;
  workspaceId?: string;
  signal?: AbortSignal;
};

export function buildRequestRunStopAction(input: {
  runId: string;
  clientActionId: string;
  workspaceId: string;
}): Record<string, unknown> {
  const runId = input.runId.startsWith("run:")
    ? input.runId.slice("run:".length)
    : input.runId;
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$/.test(runId)) {
    throw new WorkspaceClientError(
      "valid Hermes run_id required",
      400,
      "validation",
    );
  }
  return {
    schema_version: 1,
    kind: "run.stop.request",
    client_action_id: input.clientActionId,
    workspace: { workspace_id: input.workspaceId },
    run_ref: `run:${runId}`,
    // Run is the only proven authority on this surface. Never invent layers.
    task_ref: null,
    attempt_ref: null,
    platform_job_ref: null,
  };
}

/**
 * Request stop for one exact Hermes Run through the owner-gated workspace BFF.
 * Callers retry an unknown outcome with the same clientActionId.
 */
export async function requestHermesRunStop(
  options: RequestHermesRunStopInput,
): Promise<WorkspaceActionReceipt> {
  await ensureOwnerSession(options.signal);
  const workspaceId = options.workspaceId ?? PLATFORM_WORKSPACE_ID;
  const clientActionId = options.clientActionId ?? crypto.randomUUID();
  const action = buildRequestRunStopAction({
    runId: options.runId,
    clientActionId,
    workspaceId,
  });
  const receipt = await sameOriginJson<WorkspaceActionReceipt>(
    `/api/workspace/${encodeURIComponent(workspaceId)}/act`,
    {
      method: "POST",
      csrf: true,
      signal: options.signal,
      body: { action },
    },
  );
  if (receipt.client_action_id !== clientActionId) {
    throw new WorkspaceClientError(
      "stop receipt does not match the immutable attempt",
      503,
      "stop_receipt_identity_mismatch",
    );
  }
  if (
    typeof receipt.run_id === "string" &&
    receipt.run_id !== action.run_ref?.toString().slice("run:".length)
  ) {
    throw new WorkspaceClientError(
      "stop receipt does not match the exact Hermes Run",
      503,
      "stop_receipt_run_mismatch",
    );
  }
  return receipt;
}

/** V7e: Domain Gate 1/2/3 projection — never shares command-approval shape. */
export type WorkspaceGateProjection = {
  gate_id: string;
  gate_kind: "gate1" | "gate2" | "gate3" | string;
  attempt_ref?: string | null;
  command_id?: string | null;
  command_ref?: string | null;
  hermes_session_id?: string | null;
  hermes_run_id?: string | null;
  hqa_run_ref?: string | null;
  hqa_gate_ref?: string | null;
  managed_session_ref?: string | null;
  kind?: string | null;
  status?: string | null;
  expected_status?: string | null;
  task_id?: string | null;
  task_ref?: string | null;
  source_file_ref?: string | null;
  universe?: string | null;
  reviewed_source_sha256?: string | null;
  gate1_confirmation_id?: string | null;
  candidate_id?: string | null;
  candidate_ref?: string | null;
  expected_digest?: string | null;
  final_backtest_receipt_id?: string | null;
  final_backtest_receipt_ref?: string | null;
  base_commit?: string | null;
  hqa_receipt_ref?: string | null;
  hqa_receipt_digest?: string | null;
  promotion_id?: string | null;
  worktree?: string | null;
  patch?: string | null;
  manifest?: string | null;
  human_git_commit_required?: boolean | null;
  auto_commit?: false | null;
  reviewed_commit?: string | null;
  task_version?: number | null;
  task_status?: "completed" | null;
  task_terminal_outcome?: "completed" | null;
  attempt_status?: "completed" | null;
  attempt_terminal_outcome?: "completed" | null;
  domain_gate_outcome?: "passed" | null;
  provider_evidence_ref?: string | null;
  workflow_audit_status?: "consistent" | null;
  workflow_audit_ref?: string | null;
  workflow_audit_digest?: string | null;
  hqa_completion_receipt_ref?: string | null;
  hqa_completion_receipt_digest?: string | null;
  expires_at?: string | null;
  note?: string | null;
  decided_at?: string | null;
};

export type Gate1SourceEvidence = {
  schema_version: "1.0";
  gate_id: string;
  workspace_id: string;
  source_file_ref: string;
  reviewed_source_sha256: string;
  observed_source_sha256: string;
  client_verified_sha256: string;
  byte_length: number;
  media_type: "text/x-python; charset=utf-8";
  source_utf8: string;
};

type Gate1SourceEvidenceWire = Omit<
  Gate1SourceEvidence,
  "client_verified_sha256"
>;

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join(
    "",
  );
}

/** Independently re-hash exact UTF-8 bytes in the browser before review. */
export async function verifyGate1SourceEvidence(
  wire: Gate1SourceEvidenceWire,
  expected: {
    workspaceId: string;
    gateId: string;
    reviewedSourceSha256: string;
  },
): Promise<Gate1SourceEvidence> {
  if (
    wire.schema_version !== "1.0" ||
    wire.workspace_id !== expected.workspaceId ||
    wire.gate_id !== expected.gateId ||
    wire.reviewed_source_sha256 !== expected.reviewedSourceSha256 ||
    wire.observed_source_sha256 !== expected.reviewedSourceSha256 ||
    wire.media_type !== "text/x-python; charset=utf-8" ||
    typeof wire.source_file_ref !== "string" ||
    !wire.source_file_ref.startsWith("/") ||
    !Number.isInteger(wire.byte_length) ||
    wire.byte_length < 1 ||
    wire.byte_length > 1_048_576 ||
    typeof wire.source_utf8 !== "string" ||
    !wire.source_utf8
  ) {
    throw new WorkspaceClientError(
      "Gate 1 source evidence does not match the durable challenge",
      409,
      "paper_gate_source_evidence_mismatch",
    );
  }
  const payload = new TextEncoder().encode(wire.source_utf8);
  if (payload.byteLength !== wire.byte_length) {
    throw new WorkspaceClientError(
      "Gate 1 source byte length changed in transit",
      409,
      "paper_gate_source_evidence_mismatch",
    );
  }
  if (!globalThis.crypto?.subtle) {
    throw new WorkspaceClientError(
      "browser SHA-256 verifier is unavailable",
      503,
      "paper_gate_source_verifier_unavailable",
    );
  }
  const clientDigest = bytesToHex(
    new Uint8Array(await globalThis.crypto.subtle.digest("SHA-256", payload)),
  );
  if (clientDigest !== expected.reviewedSourceSha256) {
    throw new WorkspaceClientError(
      "Gate 1 source failed independent browser SHA-256 verification",
      409,
      "paper_gate_source_digest_mismatch",
    );
  }
  return {
    ...wire,
    client_verified_sha256: clientDigest,
  };
}

export async function fetchGate1SourceEvidence(options: {
  gateId: string;
  reviewedSourceSha256: string;
  workspaceId?: string;
  signal?: AbortSignal;
}): Promise<Gate1SourceEvidence> {
  await ensureOwnerSession(options.signal);
  const workspaceId = options.workspaceId ?? PLATFORM_WORKSPACE_ID;
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(options.gateId)) {
    throw new WorkspaceClientError("gate_id is invalid", 400, "validation");
  }
  if (!/^[0-9a-f]{64}$/.test(options.reviewedSourceSha256)) {
    throw new WorkspaceClientError(
      "reviewed_source_sha256 must be lowercase SHA-256",
      400,
      "validation",
    );
  }
  const wire = await sameOriginJson<Gate1SourceEvidenceWire>(
    `/api/workspace/${encodeURIComponent(workspaceId)}/gates/${encodeURIComponent(options.gateId)}/source`,
    { method: "GET", signal: options.signal },
  );
  return verifyGate1SourceEvidence(wire, {
    workspaceId,
    gateId: options.gateId,
    reviewedSourceSha256: options.reviewedSourceSha256,
  });
}

/** V7f: typed result projection on snapshot/follow spine (not bare id). */
export type WorkspaceResultProjection = {
  result_id: string;
  /** Spine/authority id slot compatibility. */
  id?: string;
  kind: string;
  display_title: string;
  status?: string | null;
  sample_or_real?: "sample" | "real" | string;
  freshness?: string | null;
  read_status?: string | null;
  occurred_at?: string | null;
  summary?: string | null;
  task_id?: string | null;
  attempt_id?: string | null;
  run_id?: string | null;
  artifact_id?: string | null;
  command_id?: string | null;
  ticker?: string | null;
  expiry?: string | null;
  strike?: number | null;
  bid?: number | null;
  ask?: number | null;
  delta?: number | null;
  iv?: number | null;
  apr?: number | null;
  provider_evidence?: string[] | null;
  filters?: string[] | null;
  exclusions?: string[] | null;
  limitations?: string[] | null;
  detail_href?: string | null;
  original_href?: string | null;
  source?: string | null;
  authority?: string | null;
  payload_digest?: string | null;
  exact_links?: {
    task_id?: string;
    task_ref?: string;
    attempt_id?: string;
    attempt_ref?: string;
    run_id?: string;
    run_ref?: string;
    artifact_id?: string;
    artifact_ref?: string;
    command_id?: string;
  } | null;
};

export function buildConfirmFormulaSourceAction(input: {
  taskId: string;
  reviewedSourceSha256: string;
  confirmationNote: string;
  clientActionId: string;
  workspaceId: string;
}): Record<string, unknown> {
  const taskId = input.taskId.startsWith("task:")
    ? input.taskId.slice("task:".length)
    : input.taskId;
  if (!/^[0-9a-f]{64}$/.test(input.reviewedSourceSha256)) {
    throw new WorkspaceClientError(
      "reviewed_source_sha256 must be lowercase SHA-256",
      400,
      "validation",
    );
  }
  if (!input.confirmationNote.trim()) {
    throw new WorkspaceClientError(
      "confirmation_note must be nonempty",
      400,
      "validation",
    );
  }
  return {
    schema_version: 1,
    kind: "gate1.formula_source.confirm",
    client_action_id: input.clientActionId,
    workspace: { workspace_id: input.workspaceId },
    task_ref: `task:${taskId}`,
    reviewed_source_sha256: input.reviewedSourceSha256,
    confirmation_note: input.confirmationNote,
  };
}

export function buildReviewCandidateCASAction(input: {
  candidateId: string;
  expectedDigest: string;
  note: string;
  clientActionId: string;
  workspaceId: string;
}): Record<string, unknown> {
  const candidateId = input.candidateId.startsWith("candidate:")
    ? input.candidateId.slice("candidate:".length)
    : input.candidateId;
  if (!/^[0-9a-f]{64}$/.test(input.expectedDigest)) {
    throw new WorkspaceClientError(
      "expected_digest must be lowercase SHA-256",
      400,
      "validation",
    );
  }
  if (!input.note.trim()) {
    throw new WorkspaceClientError("note must be nonempty", 400, "validation");
  }
  return {
    schema_version: 1,
    kind: "gate2.candidate.review",
    client_action_id: input.clientActionId,
    workspace: { workspace_id: input.workspaceId },
    candidate_ref: `candidate:${candidateId}`,
    expected_digest: input.expectedDigest,
    expected_status: "pending",
    note: input.note,
  };
}

export function buildPreparePromotionReviewAction(input: {
  candidateId: string;
  expectedDigest: string;
  finalBacktestReceiptId: string;
  baseCommit: string;
  clientActionId: string;
  workspaceId: string;
}): Record<string, unknown> {
  const candidateId = input.candidateId.startsWith("candidate:")
    ? input.candidateId.slice("candidate:".length)
    : input.candidateId;
  const receiptId = input.finalBacktestReceiptId.startsWith("receipt:")
    ? input.finalBacktestReceiptId.slice("receipt:".length)
    : input.finalBacktestReceiptId;
  if (!/^[0-9a-f]{64}$/.test(input.expectedDigest)) {
    throw new WorkspaceClientError(
      "expected_digest must be lowercase SHA-256",
      400,
      "validation",
    );
  }
  if (!/^[0-9a-f]{40}$/.test(input.baseCommit)) {
    throw new WorkspaceClientError(
      "base_commit must be lowercase 40-hex",
      400,
      "validation",
    );
  }
  return {
    schema_version: 1,
    kind: "gate3.promotion_review.prepare",
    client_action_id: input.clientActionId,
    workspace: { workspace_id: input.workspaceId },
    candidate_ref: `candidate:${candidateId}`,
    expected_digest: input.expectedDigest,
    final_backtest_receipt_ref: `receipt:${receiptId}`,
    base_commit: input.baseCommit,
  };
}

type PaperGateReceiptKind = "gate1" | "gate2" | "gate3";

const PAPER_GATE_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const GATE1_CONFIRMATION_ID_RE = /^gate1-[0-9a-f]{32}$/;

function requireExpectedPaperGateId(value: string): string {
  if (!PAPER_GATE_ID_RE.test(value)) {
    throw new WorkspaceClientError(
      "expected_gate_id must be an exact paper Gate identifier",
      400,
      "validation",
    );
  }
  return value;
}

function requireExpectedGate1ConfirmationId(value: string): string {
  if (!GATE1_CONFIRMATION_ID_RE.test(value)) {
    throw new WorkspaceClientError(
      "expected_gate1_confirmation_id must be an exact Gate 1 continuation",
      400,
      "validation",
    );
  }
  return value;
}

/**
 * Treat the BFF response as untrusted input. A successful paper Gate mutation
 * is usable only when it proves the exact action/Gate identity and returns a
 * durable, valid Task continuation. Gate 2/3 must preserve the Gate 1 lineage
 * projected to the user before the mutation.
 */
function validatePaperGateReceipt(
  receipt: unknown,
  expected: {
    kind: PaperGateReceiptKind;
    clientActionId: string;
    gateId: string;
    gate1ConfirmationId?: string;
  },
): WorkspaceActionReceipt {
  if (
    receipt === null ||
    typeof receipt !== "object" ||
    (receipt as WorkspaceActionReceipt).client_action_id !==
      expected.clientActionId ||
    (receipt as WorkspaceActionReceipt).gate_id !== expected.gateId
  ) {
    throw new WorkspaceClientError(
      "paper Gate receipt does not match the immutable action and Gate",
      503,
      "paper_gate_receipt_identity_mismatch",
    );
  }

  const exactReceipt = receipt as WorkspaceActionReceipt;
  if (exactReceipt.status !== "accepted") {
    return exactReceipt;
  }
  if (
    !Number.isSafeInteger(exactReceipt.task_version) ||
    (exactReceipt.task_version ?? 0) < 1
  ) {
    throw new WorkspaceClientError(
      "accepted paper Gate receipt has no valid Task continuation",
      503,
      "paper_gate_receipt_continuation_invalid",
    );
  }
  if (
    typeof exactReceipt.gate1_confirmation_id !== "string" ||
    !GATE1_CONFIRMATION_ID_RE.test(exactReceipt.gate1_confirmation_id)
  ) {
    throw new WorkspaceClientError(
      "accepted paper Gate receipt has no valid Gate 1 continuation",
      503,
      "paper_gate_receipt_continuation_invalid",
    );
  }
  if (
    expected.kind !== "gate1" &&
    exactReceipt.gate1_confirmation_id !== expected.gate1ConfirmationId
  ) {
    throw new WorkspaceClientError(
      "paper Gate receipt changed the reviewed Gate 1 continuation",
      503,
      "paper_gate_receipt_continuation_mismatch",
    );
  }
  return exactReceipt;
}

export async function confirmFormulaSource(options: {
  taskId: string;
  reviewedSourceSha256: string;
  confirmationNote: string;
  expectedGateId: string;
  clientActionId?: string;
  workspaceId?: string;
  signal?: AbortSignal;
}): Promise<WorkspaceActionReceipt> {
  const expectedGateId = requireExpectedPaperGateId(options.expectedGateId);
  await ensureOwnerSession(options.signal);
  const workspaceId = options.workspaceId ?? PLATFORM_WORKSPACE_ID;
  const clientActionId = options.clientActionId ?? crypto.randomUUID();
  const action = buildConfirmFormulaSourceAction({
    taskId: options.taskId,
    reviewedSourceSha256: options.reviewedSourceSha256,
    confirmationNote: options.confirmationNote,
    clientActionId,
    workspaceId,
  });
  const receipt = await sameOriginJson<unknown>(
    `/api/workspace/${encodeURIComponent(workspaceId)}/act`,
    {
      method: "POST",
      csrf: true,
      signal: options.signal,
      body: { action },
    },
  );
  return validatePaperGateReceipt(receipt, {
    kind: "gate1",
    clientActionId,
    gateId: expectedGateId,
  });
}

export async function reviewCandidateCAS(options: {
  candidateId: string;
  expectedDigest: string;
  note: string;
  expectedGateId: string;
  expectedGate1ConfirmationId: string;
  clientActionId?: string;
  workspaceId?: string;
  signal?: AbortSignal;
}): Promise<WorkspaceActionReceipt> {
  const expectedGateId = requireExpectedPaperGateId(options.expectedGateId);
  const expectedGate1ConfirmationId = requireExpectedGate1ConfirmationId(
    options.expectedGate1ConfirmationId,
  );
  await ensureOwnerSession(options.signal);
  const workspaceId = options.workspaceId ?? PLATFORM_WORKSPACE_ID;
  const clientActionId = options.clientActionId ?? crypto.randomUUID();
  const action = buildReviewCandidateCASAction({
    candidateId: options.candidateId,
    expectedDigest: options.expectedDigest,
    note: options.note,
    clientActionId,
    workspaceId,
  });
  const receipt = await sameOriginJson<unknown>(
    `/api/workspace/${encodeURIComponent(workspaceId)}/act`,
    {
      method: "POST",
      csrf: true,
      signal: options.signal,
      body: { action },
    },
  );
  return validatePaperGateReceipt(receipt, {
    kind: "gate2",
    clientActionId,
    gateId: expectedGateId,
    gate1ConfirmationId: expectedGate1ConfirmationId,
  });
}

export async function preparePromotionReview(options: {
  candidateId: string;
  expectedDigest: string;
  finalBacktestReceiptId: string;
  baseCommit: string;
  expectedGateId: string;
  expectedGate1ConfirmationId: string;
  clientActionId?: string;
  workspaceId?: string;
  signal?: AbortSignal;
}): Promise<WorkspaceActionReceipt> {
  const expectedGateId = requireExpectedPaperGateId(options.expectedGateId);
  const expectedGate1ConfirmationId = requireExpectedGate1ConfirmationId(
    options.expectedGate1ConfirmationId,
  );
  await ensureOwnerSession(options.signal);
  const workspaceId = options.workspaceId ?? PLATFORM_WORKSPACE_ID;
  const clientActionId = options.clientActionId ?? crypto.randomUUID();
  const action = buildPreparePromotionReviewAction({
    candidateId: options.candidateId,
    expectedDigest: options.expectedDigest,
    finalBacktestReceiptId: options.finalBacktestReceiptId,
    baseCommit: options.baseCommit,
    clientActionId,
    workspaceId,
  });
  const receipt = await sameOriginJson<unknown>(
    `/api/workspace/${encodeURIComponent(workspaceId)}/act`,
    {
      method: "POST",
      csrf: true,
      signal: options.signal,
      body: { action },
    },
  );
  return validatePaperGateReceipt(receipt, {
    kind: "gate3",
    clientActionId,
    gateId: expectedGateId,
    gate1ConfirmationId: expectedGate1ConfirmationId,
  });
}

/** V7g-A-M1: hermetic Vertical A options research bind (fixture only). */
export function buildBindOptionsVerticalAAction(input: {
  ticker: string;
  goalNote: string;
  expiry: string;
  strike: number;
  bid: number;
  ask: number;
  delta: number;
  iv: number;
  apr: number;
  includeProviderEvidence?: boolean;
  clientActionId: string;
  workspaceId: string;
}): Record<string, unknown> {
  return {
    schema_version: 1,
    kind: "vertical.options_a.bind",
    client_action_id: input.clientActionId,
    workspace: { workspace_id: input.workspaceId },
    ticker: input.ticker,
    goal_note: input.goalNote,
    expiry: input.expiry,
    strike: input.strike,
    bid: input.bid,
    ask: input.ask,
    delta: input.delta,
    iv: input.iv,
    apr: input.apr,
    include_provider_evidence: input.includeProviderEvidence !== false,
  };
}

export async function bindOptionsVerticalA(options: {
  ticker: string;
  goalNote: string;
  expiry: string;
  strike: number;
  bid: number;
  ask: number;
  delta: number;
  iv: number;
  apr: number;
  includeProviderEvidence?: boolean;
  clientActionId?: string;
  workspaceId?: string;
  signal?: AbortSignal;
}): Promise<WorkspaceActionReceipt> {
  await ensureOwnerSession(options.signal);
  const workspaceId = options.workspaceId ?? PLATFORM_WORKSPACE_ID;
  const clientActionId = options.clientActionId ?? crypto.randomUUID();
  const action = buildBindOptionsVerticalAAction({
    ticker: options.ticker,
    goalNote: options.goalNote,
    expiry: options.expiry,
    strike: options.strike,
    bid: options.bid,
    ask: options.ask,
    delta: options.delta,
    iv: options.iv,
    apr: options.apr,
    includeProviderEvidence: options.includeProviderEvidence,
    clientActionId,
    workspaceId,
  });
  return sameOriginJson<WorkspaceActionReceipt>(
    `/api/workspace/${encodeURIComponent(workspaceId)}/act`,
    {
      method: "POST",
      csrf: true,
      signal: options.signal,
      body: { action },
    },
  );
}

export type WorkspaceCommandProjection = {
  command_id: string;
  kind: string;
  state: string;
  version: number;
  client_request_id?: string | null;
  client_action_id?: string | null;
  platform_session_id?: string | null;
  hermes_session_id?: string | null;
  hermes_run_id?: string | null;
  last_error_code?: string | null;
  attempt_count?: number;
  updated_at?: string | null;
  created_at?: string | null;
};

/** L5a/V7a/V7d: Hermes command-approval challenge projection. */
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
  /** V7d: decided fact when status is allowed_once|denied. */
  decision?: "allow_once" | "deny" | string | null;
  decided_at?: string | null;
};

export type WorkspaceSnapshot = {
  workspace?: { workspace_id: string };
  owner_user_id?: string;
  snapshot_workspace_cursor?: number;
  sessions?: string[];
  managed_sessions?: ManagedSessionProjection[];
  commands?: WorkspaceCommandProjection[];
  /** L5b: HQA Task authority ids/objects; empty until projector. */
  tasks?: string[];
  /** L5b: Attempt authority ids/objects; empty until projector. */
  attempts?: string[];
  /** L5b: Run authority ids/objects; empty until projector. */
  runs?: string[];
  /** V7f: typed result projections; empty honest until seeded. */
  results?: WorkspaceResultProjection[] | string[];
  /** L5a/V7a: Hermes command-approval challenges; empty when none pending. */
  approvals?: WorkspaceApprovalProjection[];
  /** V7e: Domain Gate 1/2/3 surfaces; never mixed into approvals[]. */
  gates?: WorkspaceGateProjection[];
  /** Production projection: legacy hermetic rows or canonical PG release rows. */
  public_cutovers?: WorkspacePublicCutoverResponse[];
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
  /** V7d: approvals projection on follow pages (pending + recent decided). */
  approvals?: WorkspaceApprovalProjection[];
  /** V7e: gates projection on follow pages (separate from approvals). */
  gates?: WorkspaceGateProjection[];
  /** V7f: typed results projection on follow pages. */
  results?: WorkspaceResultProjection[];
  /** Canonical public-cutover facts; follow may omit when unchanged. */
  public_cutovers?: WorkspacePublicCutoverResponse[];
  /** V7g: Task/Attempt/Run id lists on follow pages (not only snapshot). */
  tasks?: string[];
  attempts?: string[];
  runs?: string[];
  authority_health?: Record<string, string>;
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

export type ManagedSessionProvisionState =
  "pending" | "leased" | "retryable" | "ready" | "failed";

export type ManagedSessionProjection = {
  platform_session_id: string;
  session_ref: string;
  hermes_session_id: string;
  provision_state: ManagedSessionProvisionState;
  web_writable: boolean;
  attempt_count: number;
  lease_until?: string | null;
  retry_at?: string | null;
  last_error_code?: string | null;
  provisioned_at?: string | null;
  parent_session_ref?: string | null;
  fork_point?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

function abortError(): Error {
  if (typeof DOMException !== "undefined") {
    return new DOMException("managed session wait aborted", "AbortError");
  }
  const error = new Error("managed session wait aborted");
  error.name = "AbortError";
  return error;
}

function managedSessionWaitError(
  projection: ManagedSessionProjection | null,
  observed: boolean,
  observationError: unknown,
): WorkspaceClientError {
  if (projection?.provision_state === "retryable") {
    const retry = projection.retry_at
      ? `; retry_at=${projection.retry_at}`
      : "";
    const reason = projection.last_error_code
      ? `; last_error=${projection.last_error_code}`
      : "";
    return new WorkspaceClientError(
      `managed session provisioning is retryable${reason}${retry}`,
      503,
      "managed_session_provision_retryable",
    );
  }
  if (!observed && observationError == null) {
    return new WorkspaceClientError(
      "managed session was not observed before the bounded wait expired",
      503,
      "managed_session_not_observed",
    );
  }
  if (observationError != null) {
    return new WorkspaceClientError(
      "managed session observation was unavailable before the bounded wait expired",
      503,
      "managed_session_observation_unavailable",
    );
  }
  return new WorkspaceClientError(
    `managed session provisioning timed out in state=${
      projection?.provision_state ?? "unknown"
    }`,
    503,
    "managed_session_provision_timeout",
  );
}

/**
 * Bounded wait on the existing workspace snapshot. This never clears the
 * durable session reference, creates a replacement, or starts a private
 * unbounded poll. Fork lineage therefore cannot be silently discarded.
 */
export async function waitForManagedSessionReady(options: {
  sessionRef: string;
  workspaceId?: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  initialIntervalMs?: number;
}): Promise<ManagedSessionProjection> {
  const workspaceId = options.workspaceId ?? PLATFORM_WORKSPACE_ID;
  const timeoutMs = Math.min(
    30_000,
    Math.max(1, Math.floor(options.timeoutMs ?? 15_000)),
  );
  let intervalMs = Math.min(
    1_000,
    Math.max(1, Math.floor(options.initialIntervalMs ?? 100)),
  );
  const sessionRef = options.sessionRef.trim();
  if (!sessionRef.startsWith("session:")) {
    throw new WorkspaceClientError(
      "invalid managed session reference",
      400,
      "managed_session_ref_invalid",
    );
  }

  const bounded = new AbortController();
  let timedOut = false;
  const onCallerAbort = () => bounded.abort();
  options.signal?.addEventListener("abort", onCallerAbort, { once: true });
  const timeout = setTimeout(() => {
    timedOut = true;
    bounded.abort();
  }, timeoutMs);
  let last: ManagedSessionProjection | null = null;
  let observed = false;
  let observationError: unknown = null;

  try {
    while (!bounded.signal.aborted) {
      try {
        const snapshot = await fetchWorkspaceSnapshot(
          workspaceId,
          bounded.signal,
        );
        observationError = null;
        const platformId = sessionRef.slice("session:".length);
        last =
          (snapshot.managed_sessions ?? []).find(
            (item) =>
              item.session_ref === sessionRef ||
              item.platform_session_id === platformId,
          ) ?? null;
        observed ||= last !== null;
        if (last?.provision_state === "failed") {
          const reason = last.last_error_code
            ? `: ${last.last_error_code}`
            : "";
          throw new WorkspaceClientError(
            `managed session provisioning failed${reason}`,
            503,
            "managed_session_provision_failed",
          );
        }
        if (last) {
          assertManagedSessionProjectionIdentity(last);
        }
        if (last && managedSessionProjectionIsReady(last)) {
          return last;
        }
      } catch (error) {
        if (
          error instanceof WorkspaceClientError &&
          (error.code === "managed_session_provision_failed" ||
            error.code === "managed_session_projection_invalid" ||
            error.code === "managed_session_ready_contract_invalid")
        ) {
          throw error;
        }
        if (bounded.signal.aborted) {
          break;
        }
        observationError = error;
      }

      await new Promise<void>((resolve) => {
        const timer = setTimeout(resolve, intervalMs);
        bounded.signal.addEventListener(
          "abort",
          () => {
            clearTimeout(timer);
            resolve();
          },
          { once: true },
        );
      });
      intervalMs = Math.min(1_000, intervalMs * 2);
    }
  } finally {
    clearTimeout(timeout);
    options.signal?.removeEventListener("abort", onCallerAbort);
  }

  if (options.signal?.aborted && !timedOut) {
    throw abortError();
  }
  throw managedSessionWaitError(last, observed, observationError);
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
    params.set(
      "after_cursor",
      String(Math.max(0, Math.floor(options.afterCursor))),
    );
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
  "succeeded",
  "cancelled",
  "failed",
  "rejected",
  "timed_out",
]);

export function isTerminalCommandState(
  state: string | null | undefined,
): boolean {
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
  /** Server-authoritative cursor; null when the upstream id was not a positive integer. */
  fork_point?: string | null;
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
      "Hermes SessionDB id required (reject platform wm_/unsafe/empty)",
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
