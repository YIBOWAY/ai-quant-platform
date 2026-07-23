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

export { PLATFORM_WORKSPACE_ID };

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
  signal?: AbortSignal;
}): Promise<WorkspaceActionReceipt> {
  preflightPrompt(options.prompt);
  await ensureOwnerSession(options.signal);
  const clientActionId = options.clientActionId ?? crypto.randomUUID();
  const managedSession = await ensureManagedSession({ signal: options.signal });
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

/** V7e: Domain Gate 1/2/3 projection — never shares command-approval shape. */
export type WorkspaceGateProjection = {
  gate_id: string;
  gate_kind: "gate1" | "gate2" | "gate3" | string;
  kind?: string | null;
  status?: string | null;
  expected_status?: string | null;
  task_id?: string | null;
  task_ref?: string | null;
  reviewed_source_sha256?: string | null;
  candidate_id?: string | null;
  candidate_ref?: string | null;
  expected_digest?: string | null;
  final_backtest_receipt_id?: string | null;
  final_backtest_receipt_ref?: string | null;
  base_commit?: string | null;
  expires_at?: string | null;
  note?: string | null;
  decided_at?: string | null;
};

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

export async function confirmFormulaSource(options: {
  taskId: string;
  reviewedSourceSha256: string;
  confirmationNote: string;
  clientActionId?: string;
  workspaceId?: string;
  signal?: AbortSignal;
}): Promise<WorkspaceActionReceipt> {
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

export async function reviewCandidateCAS(options: {
  candidateId: string;
  expectedDigest: string;
  note: string;
  clientActionId?: string;
  workspaceId?: string;
  signal?: AbortSignal;
}): Promise<WorkspaceActionReceipt> {
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

export async function preparePromotionReview(options: {
  candidateId: string;
  expectedDigest: string;
  finalBacktestReceiptId: string;
  baseCommit: string;
  clientActionId?: string;
  workspaceId?: string;
  signal?: AbortSignal;
}): Promise<WorkspaceActionReceipt> {
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
        if (last?.provision_state === "ready") {
          if (
            last.web_writable !== true ||
            !isUsableHermesApiSessionId(last.hermes_session_id)
          ) {
            throw new WorkspaceClientError(
              "managed session ready projection is internally inconsistent",
              503,
              "managed_session_ready_contract_invalid",
            );
          }
          return last;
        }
      } catch (error) {
        if (
          error instanceof WorkspaceClientError &&
          (error.code === "managed_session_provision_failed" ||
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
  "delivered",
  "cancelled",
  "failed",
  "rejected",
  "timed_out",
  "outcome_unknown",
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
