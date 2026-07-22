import type { HermesSessionMessage } from "@/lib/hermes/workspaceClient";

/**
 * Hermes messages BFF ids include canonical managed `web_*` sessions.
 * Platform registry `wm_*` must never hit /messages.
 */
export function isUsableHermesApiSessionId(
  value: string | null | undefined,
): value is string {
  if (typeof value !== "string") return false;
  const id = value.trim();
  if (!id) return false;
  if (id.startsWith("wm_")) return false;
  return true;
}

/** Keep non-empty user/assistant rows for workbench transcript canvas. */
export function displayableTranscriptMessages(
  messages: HermesSessionMessage[] | null | undefined,
): HermesSessionMessage[] {
  if (!Array.isArray(messages) || messages.length === 0) {
    return [];
  }
  return messages.filter((m) => {
    if (!m || typeof m !== "object") return false;
    if (m.role !== "user" && m.role !== "assistant") return false;
    return typeof m.content === "string" && m.content.trim().length > 0;
  });
}

/**
 * Prefer the newest command that already carries a usable hermes_session_id.
 */
export function pickLatestHermesSessionId(
  commands:
    | Array<{
        command_id?: string | null;
        state?: string | null;
        hermes_session_id?: string | null;
      }>
    | null
    | undefined,
): { hermesSessionId: string; commandId?: string } | null {
  if (!Array.isArray(commands) || commands.length === 0) {
    return null;
  }
  for (let i = commands.length - 1; i >= 0; i -= 1) {
    const row = commands[i];
    if (!row || !["succeeded", "failed", "cancelled"].includes(row.state ?? "")) {
      continue;
    }
    const id = row?.hermes_session_id;
    if (!isUsableHermesApiSessionId(id)) continue;
    return {
      hermesSessionId: id.trim(),
      commandId: row?.command_id ?? undefined,
    };
  }
  return null;
}

/** True when the scroll container is within `thresholdPx` of the bottom. */
export function isNearBottom(
  el: Pick<HTMLElement, "scrollHeight" | "scrollTop" | "clientHeight"> | null | undefined,
  thresholdPx = 80,
): boolean {
  if (!el) return true;
  const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
  return distance <= thresholdPx;
}

const PENDING_USER_ID = "local-pending-user";

/**
 * Append a local optimistic user bubble when the server transcript does not
 * already contain the same user text (L3b). Never invents assistant content.
 */
export function mergePendingUserMessage(
  messages: HermesSessionMessage[] | null | undefined,
  pendingText: string | null | undefined,
): HermesSessionMessage[] {
  const base = displayableTranscriptMessages(messages);
  const text = typeof pendingText === "string" ? pendingText.trim() : "";
  if (!text) return base;

  const already = base.some(
    (m) => m.role === "user" && m.content.trim() === text,
  );
  if (already) return base;

  return [
    ...base,
    {
      id: PENDING_USER_ID,
      role: "user",
      content: text,
      timestamp: null,
    },
  ];
}

/** Best-effort clipboard write; returns false when unavailable. */
export async function copyTextToClipboard(text: string): Promise<boolean> {
  const value = text.trim();
  if (!value) return false;
  try {
    if (
      typeof navigator !== "undefined" &&
      navigator.clipboard &&
      typeof navigator.clipboard.writeText === "function"
    ) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    // fall through
  }
  try {
    if (typeof document === "undefined") return false;
    const ta = document.createElement("textarea");
    ta.value = value;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

/** Plan-V6-Token-Stream-M1: honest assistant streaming phase (no invented tokens). */
export type AssistantPhase =
  | "idle"
  | "waiting"
  | "partial"
  | "final"
  | "unavailable";

export type TranscriptHint = {
  hermes_session_id?: string | null;
  command_id?: string | null;
  phase?: AssistantPhase | string | null;
  revision?: string | number | null;
  transport?: string | null;
  limitations?: string[] | null;
  workspace_id?: string | null;
  mutation_enabled?: boolean;
};

const TERMINAL_FOR_PHASE = new Set([
  "delivered",
  "cancelled",
  "failed",
  "rejected",
  "timed_out",
  "outcome_unknown",
]);

/**
 * Derive assistant phase from command state + messages presence.
 * Never invents assistant content — only classifies what already exists.
 */
export function deriveAssistantPhase(options: {
  hasActiveSession: boolean;
  commandState?: string | null;
  assistantContentLength?: number;
  messagesReadStatus?: string | null;
  submitAccepted?: boolean;
  priorPhase?: AssistantPhase | null;
}): AssistantPhase {
  const {
    hasActiveSession,
    commandState,
    assistantContentLength = 0,
    messagesReadStatus,
    submitAccepted = false,
    priorPhase = null,
  } = options;

  if (
    messagesReadStatus &&
    messagesReadStatus !== "available" &&
    messagesReadStatus !== ""
  ) {
    return "unavailable";
  }

  const state =
    typeof commandState === "string" ? commandState.trim().toLowerCase() : "";
  const terminal = state !== "" && TERMINAL_FOR_PHASE.has(state);
  const hasAssistant = assistantContentLength > 0;

  if (terminal) {
    // Terminal with or without assistant body is final (failed/cancelled/empty delivered honest).
    return "final";
  }

  if (hasAssistant && !terminal) {
    return "partial";
  }

  if (submitAccepted || state === "queued" || state === "leased" || state === "running") {
    return "waiting";
  }

  if (priorPhase === "waiting" || priorPhase === "partial") {
    return priorPhase;
  }

  if (!hasActiveSession) return "idle";
  return priorPhase === "final" ? "final" : "idle";
}

/** Total assistant content length (for growth detection). */
export function assistantContentLength(
  messages: HermesSessionMessage[] | null | undefined,
): number {
  if (!Array.isArray(messages)) return 0;
  let n = 0;
  for (const m of messages) {
    if (m && m.role === "assistant" && typeof m.content === "string") {
      n += m.content.length;
    }
  }
  return n;
}

/**
 * True when next messages extend prior assistant text (prefix/growth) without
 * requiring a full canvas wipe. Same session assumed by caller.
 */
export function assistantTextGrew(
  prior: HermesSessionMessage[] | null | undefined,
  next: HermesSessionMessage[] | null | undefined,
): boolean {
  const a = assistantContentLength(prior);
  const b = assistantContentLength(next);
  return b > a;
}

/** Strip forbidden body keys from a transcript hint (defense in depth). */
export function sanitizeTranscriptHint(
  raw: Record<string, unknown> | null | undefined,
): TranscriptHint | null {
  if (!raw || typeof raw !== "object") return null;
  const sid = raw.hermes_session_id;
  const normalizedSid = typeof sid === "string" ? sid.trim() : "";
  // Follow-spine transcript hints are not session-registry authority. Managed
  // web_* and workspace wm_* identifiers must be resolved through the
  // authoritative snapshot/messages path before they can drive a refetch.
  if (
    !normalizedSid ||
    normalizedSid.startsWith("web_") ||
    normalizedSid.startsWith("wm_") ||
    !isUsableHermesApiSessionId(normalizedSid)
  ) {
    return null;
  }
  const phaseRaw = typeof raw.phase === "string" ? raw.phase.trim().toLowerCase() : "";
  const phase =
    phaseRaw === "waiting" ||
    phaseRaw === "partial" ||
    phaseRaw === "final" ||
    phaseRaw === "unavailable"
      ? (phaseRaw as AssistantPhase)
      : undefined;
  return {
    hermes_session_id: normalizedSid,
    command_id:
      typeof raw.command_id === "string" || raw.command_id === null
        ? (raw.command_id as string | null)
        : null,
    phase,
    revision:
      typeof raw.revision === "string" || typeof raw.revision === "number"
        ? raw.revision
        : null,
    transport:
      typeof raw.transport === "string" ? raw.transport : "spine-refetch",
    limitations: Array.isArray(raw.limitations)
      ? raw.limitations.filter((x): x is string => typeof x === "string")
      : [
          "assistant_body_not_on_follow_spine",
          "not_provider_token_passthrough",
          "messages_bff_is_text_authority",
          "public_write_off",
        ],
    workspace_id:
      typeof raw.workspace_id === "string" ? raw.workspace_id : null,
    mutation_enabled: Boolean(raw.mutation_enabled),
  };
}

/**
 * Sole-owner quiet messages refetch scheduler (V8-M2 GAP-09).
 *
 * Dirty bumps + waiting/partial interval share one owner. In-flight bumps set
 * a pending bit; exactly one follow-up runs after the current fetch settles
 * (no recursive 200ms polling chain while hung).
 */
export type QuietRefetchSchedulerOptions = {
  coalesceMs?: number;
  fetch: (sessionId: string) => Promise<void>;
  /** Optional clock for tests; defaults to setTimeout/clearTimeout. */
  setTimer?: (fn: () => void, ms: number) => ReturnType<typeof setTimeout>;
  clearTimer?: (id: ReturnType<typeof setTimeout>) => void;
};

export type QuietRefetchScheduler = {
  schedule: (sessionId: string) => void;
  /** True while a fetch is outstanding. */
  isInFlight: () => boolean;
  /** True when a dirty bump arrived during flight and needs one follow-up. */
  isPending: () => boolean;
  /** Cancel timer + drop pending; does not abort an in-flight fetch. */
  dispose: () => void;
  /**
   * Test/hook: mark the outstanding fetch settled. Production wires this
   * from the fetch finally block automatically via schedule().
   */
  _notifySettledForTests?: () => void;
};

export function createQuietRefetchScheduler(
  opts: QuietRefetchSchedulerOptions,
): QuietRefetchScheduler {
  const coalesceMs = opts.coalesceMs ?? 200;
  const setTimer = opts.setTimer ?? ((fn, ms) => setTimeout(fn, ms));
  const clearTimer =
    opts.clearTimer ?? ((id) => clearTimeout(id as ReturnType<typeof setTimeout>));

  let timer: ReturnType<typeof setTimeout> | null = null;
  let inFlight = false;
  let pending = false;
  let activeSessionId: string | null = null;
  let disposed = false;

  const clearCoalesce = () => {
    if (timer != null) {
      clearTimer(timer);
      timer = null;
    }
  };

  const run = (sessionId: string) => {
    if (disposed) return;
    if (inFlight) {
      // Remember exactly one follow-up; do not spin a retry chain.
      pending = true;
      activeSessionId = sessionId;
      return;
    }
    inFlight = true;
    pending = false;
    activeSessionId = sessionId;
    void Promise.resolve()
      .then(() => opts.fetch(sessionId))
      .catch(() => {
        /* soft-fail; caller owns canvas */
      })
      .finally(() => {
        inFlight = false;
        if (disposed) return;
        if (pending) {
          pending = false;
          const next = activeSessionId;
          if (next) {
            // Single deferred follow-up (coalesced).
            clearCoalesce();
            timer = setTimer(() => {
              timer = null;
              run(next);
            }, coalesceMs);
          }
        }
      });
  };

  return {
    schedule(sessionId: string) {
      if (disposed) return;
      if (!sessionId) return;
      activeSessionId = sessionId;
      if (inFlight) {
        pending = true;
        return;
      }
      clearCoalesce();
      timer = setTimer(() => {
        timer = null;
        run(sessionId);
      }, coalesceMs);
    },
    isInFlight: () => inFlight,
    isPending: () => pending,
    dispose() {
      disposed = true;
      pending = false;
      clearCoalesce();
    },
  };
}
