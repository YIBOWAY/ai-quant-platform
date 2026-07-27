/**
 * L4b-SSE-Follow-M1: shared durable workspace follow spine.
 *
 * Prefer EventSource on GET …/follow/stream; fall back to GET …/follow poll.
 * Command lifecycle + V7d approvals + V7e gates + V7f results + V7g vertical
 * + Plan-V6 transcript **hints** (no assistant bodies on this spine).
 * On resync: snapshot then continue. No dual private approval poll.
 * Text authority for assistant text: messages BFF (spine-refetch).
 */

import {
  fetchWorkspaceFollow,
  fetchWorkspaceSnapshot,
  isTerminalCommandState,
  type WorkspaceApprovalProjection,
  type WorkspaceCommandProjection,
  type WorkspaceFollowEvent,
  type WorkspaceGateProjection,
  type WorkspacePublicCutoverResponse,
  type WorkspaceResultProjection,
  type WorkspaceSnapshot,
} from "@/lib/hermes/workspaceClient";
import { PLATFORM_WORKSPACE_ID } from "@/lib/hermes/darkIdentity";
import {
  sanitizeTranscriptHint,
  type TranscriptHint,
} from "@/lib/hermes/transcriptHelpers";

export type FollowTransport = "sse" | "poll" | "idle";

export type FollowSpineState = {
  cursor: number;
  commands: WorkspaceCommandProjection[];
  /** L5a/V7a: Hermes command-approval challenges from snapshot. */
  approvals: WorkspaceApprovalProjection[];
  /** V7e: Domain Gate 1/2/3 surfaces from snapshot (never in approvals[]). */
  gates: WorkspaceGateProjection[];
  /** Canonical PG release rows (or explicit legacy test rows) from the spine. */
  publicCutovers: WorkspacePublicCutoverResponse[];
  /** L5b: authority id slots from snapshot (honest empty until projectors). */
  tasks: string[];
  attempts: string[];
  runs: string[];
  /** V7f: typed results (objects). Empty honest. */
  results: WorkspaceResultProjection[];
  /** L5b: snapshot authority_health carry-through (optional keys). */
  authorityHealth: Record<string, string>;
  /** V7a: snapshot mutation_enabled — gates approval decide controls. */
  mutationEnabled: boolean;
  lastEvents: WorkspaceFollowEvent[];
  transport: FollowTransport;
  resyncCount: number;
  error: string | null;
  observedAt?: string;
  snapshotCursor?: number | null;
  /**
   * Plan-V6-Token-Stream-M1: body-free transcript hints from SSE event:transcript
   * or derived from command lifecycle. Never contains assistant text.
   */
  transcriptHints: TranscriptHint[];
  /** Monotonic dirty counter — transcript panel refetches when this bumps. */
  transcriptDirtySeq: number;
};

export type FollowSpineListener = (state: FollowSpineState) => void;

export type FollowSpineOptions = {
  workspaceId?: string;
  /** Poll interval when SSE unavailable (ms). */
  pollMs?: number;
  /** Periodic snapshot reconcile even when SSE healthy (ms). 0 = only on resync. */
  snapshotReconcileMs?: number;
  /** Prefer EventSource when available. */
  preferSse?: boolean;
  /** Soft max SSE reconnect attempts before sticky poll. */
  maxSseFailures?: number;
};

const DEFAULT_POLL_MS = 2_000;
const DEFAULT_SNAPSHOT_RECONCILE_MS = 30_000;
const DEFAULT_MAX_SSE_FAILURES = 3;

/** Pre-snapshot defaults: honest unavailable until first snapshot reconcile. */
export const EMPTY_AUTHORITY_HEALTH: Record<string, string> = {
  task: "unavailable",
  attempt: "unavailable",
  run: "unavailable",
  result: "unavailable",
  command_approval: "unavailable",
  gate_1: "unavailable",
  gate_2: "unavailable",
  gate_3: "unavailable",
};

function emptyState(): FollowSpineState {
  return {
    cursor: 0,
    commands: [],
    approvals: [],
    gates: [],
    publicCutovers: [],
    tasks: [],
    attempts: [],
    runs: [],
    results: [],
    authorityHealth: { ...EMPTY_AUTHORITY_HEALTH },
    mutationEnabled: false,
    lastEvents: [],
    transport: "idle",
    resyncCount: 0,
    error: null,
    transcriptHints: [],
    transcriptDirtySeq: 0,
  };
}

function asIdList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object" && "id" in item) {
        const id = (item as { id?: unknown }).id;
        return typeof id === "string" ? id : "";
      }
      return "";
    })
    .filter(Boolean);
}

/** Fail-closed sample/real: only exact "real" is real; everything else is sample. */
function normalizeSampleOrReal(value: unknown): "sample" | "real" {
  return typeof value === "string" && value.toLowerCase() === "real"
    ? "real"
    : "sample";
}

/** Fail-closed read_status: unknown/invalid → unavailable (never invent available). */
function normalizeReadStatus(
  value: unknown,
): WorkspaceResultProjection["read_status"] {
  if (typeof value !== "string") return "unavailable";
  const v = value.toLowerCase();
  if (
    v === "available" ||
    v === "degraded" ||
    v === "missing" ||
    v === "corrupt" ||
    v === "unavailable"
  ) {
    return v;
  }
  return "unavailable";
}

/** V7f: accept typed result objects; coerce bare id strings into minimal stubs. */
function asResultList(value: unknown): WorkspaceResultProjection[] {
  if (!Array.isArray(value)) return [];
  const out: WorkspaceResultProjection[] = [];
  for (const item of value) {
    if (!item) continue;
    if (typeof item === "string") {
      if (!item) continue;
      out.push({
        result_id: item,
        id: item,
        kind: "generic",
        display_title: item,
        sample_or_real: "sample",
        // Bare id has no proven payload — never claim available.
        read_status: "unavailable",
      });
      continue;
    }
    if (typeof item !== "object") continue;
    const row = item as Record<string, unknown>;
    const resultId =
      typeof row.result_id === "string"
        ? row.result_id
        : typeof row.id === "string"
          ? row.id
          : "";
    if (!resultId) continue;
    out.push({
      ...(row as WorkspaceResultProjection),
      result_id: resultId,
      id: typeof row.id === "string" ? row.id : resultId,
      kind: typeof row.kind === "string" ? row.kind : "generic",
      display_title:
        typeof row.display_title === "string" ? row.display_title : resultId,
      sample_or_real: normalizeSampleOrReal(row.sample_or_real),
      read_status: normalizeReadStatus(row.read_status),
    });
  }
  return out;
}

/** Ids-only view for L5b authority panel slot (never invents Task rows). */
export function resultIdsFromProjection(
  results: Array<WorkspaceResultProjection | string> | undefined,
): string[] {
  if (!Array.isArray(results)) return [];
  return results
    .map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object") {
        return item.result_id || item.id || "";
      }
      return "";
    })
    .filter(Boolean);
}

function applyCommandEvent(
  commands: WorkspaceCommandProjection[],
  event: WorkspaceFollowEvent,
): WorkspaceCommandProjection[] {
  if (!event.command_id) return commands;
  const idx = commands.findIndex((c) => c.command_id === event.command_id);
  const prev = idx >= 0 ? commands[idx] : undefined;
  const next: WorkspaceCommandProjection = {
    command_id: event.command_id,
    kind: event.kind ?? prev?.kind ?? "conversation_turn",
    state: event.state ?? prev?.state ?? "queued",
    version:
      typeof event.command_version === "number"
        ? event.command_version
        : (prev?.version ?? 1),
    client_request_id:
      event.client_request_id ?? prev?.client_request_id ?? undefined,
    client_action_id: event.client_action_id ?? prev?.client_action_id ?? undefined,
    platform_session_id:
      event.platform_session_id ?? prev?.platform_session_id ?? undefined,
    hermes_session_id: event.hermes_session_id ?? prev?.hermes_session_id ?? null,
    hermes_run_id: event.hermes_run_id ?? prev?.hermes_run_id ?? null,
    last_error_code: event.error_code ?? prev?.last_error_code ?? null,
    attempt_count: prev?.attempt_count,
    created_at: prev?.created_at,
    updated_at: event.occurred_at ?? prev?.updated_at,
  };
  if (idx < 0) return [next, ...commands];
  const copy = commands.slice();
  copy[idx] = next;
  return copy;
}

function mergeSnapshotCommands(
  snap: WorkspaceSnapshot,
): WorkspaceCommandProjection[] {
  return Array.isArray(snap.commands) ? [...snap.commands] : [];
}

export type WorkspaceFollowSpine = {
  getState: () => FollowSpineState;
  subscribe: (listener: FollowSpineListener) => () => void;
  start: () => void;
  stop: () => void;
  /** Force one snapshot reconcile (e.g. after submit accept). */
  resyncNow: () => Promise<void>;
};

export function createWorkspaceFollowSpine(
  options: FollowSpineOptions = {},
): WorkspaceFollowSpine {
  const workspaceId = options.workspaceId ?? PLATFORM_WORKSPACE_ID;
  const pollMs = options.pollMs ?? DEFAULT_POLL_MS;
  const snapshotReconcileMs =
    options.snapshotReconcileMs ?? DEFAULT_SNAPSHOT_RECONCILE_MS;
  const preferSse = options.preferSse !== false;
  const maxSseFailures = options.maxSseFailures ?? DEFAULT_MAX_SSE_FAILURES;

  let state = emptyState();
  const listeners = new Set<FollowSpineListener>();
  let running = false;
  let stopped = true;
  let sse: EventSource | null = null;
  let pollTimer: number | null = null;
  let snapTimer: number | null = null;
  let sseFailures = 0;
  let pollInFlight = false;

  const emit = () => {
    for (const listener of listeners) {
      try {
        listener(state);
      } catch {
        // subscriber errors must not kill the spine
      }
    }
  };

  const setState = (patch: Partial<FollowSpineState>) => {
    state = { ...state, ...patch };
    emit();
  };

  const applyEvents = (events: WorkspaceFollowEvent[]) => {
    if (!events.length) return;
    let commands = state.commands;
    let dirty = false;
    for (const event of events) {
      commands = applyCommandEvent(commands, event);
      if (event.hermes_session_id || event.state) {
        dirty = true;
      }
    }
    setState({
      commands,
      lastEvents: events,
      error: null,
      transcriptDirtySeq: dirty
        ? state.transcriptDirtySeq + 1
        : state.transcriptDirtySeq,
    });
  };

  /** Plan-V6-M1: apply body-free transcript hints; bump dirty for refetch. */
  const applyTranscriptHints = (rawHints: unknown) => {
    if (!Array.isArray(rawHints) || rawHints.length === 0) {
      // Single hint object form from SSE event:transcript
      if (rawHints && typeof rawHints === "object" && !Array.isArray(rawHints)) {
        const one = sanitizeTranscriptHint(rawHints as Record<string, unknown>);
        if (!one) return;
        const prior = state.transcriptHints;
        const same = prior.some(
          (h) =>
            h.hermes_session_id === one.hermes_session_id &&
            String(h.revision ?? "") === String(one.revision ?? ""),
        );
        if (same) return;
        const next = [
          ...prior.filter((h) => h.hermes_session_id !== one.hermes_session_id),
          one,
        ];
        setState({
          transcriptHints: next,
          transcriptDirtySeq: state.transcriptDirtySeq + 1,
          error: null,
        });
      }
      return;
    }
    const cleaned: TranscriptHint[] = [];
    for (const item of rawHints) {
      if (!item || typeof item !== "object") continue;
      const h = sanitizeTranscriptHint(item as Record<string, unknown>);
      if (h) cleaned.push(h);
    }
    if (!cleaned.length) return;
    let merged = state.transcriptHints.slice();
    let changed = false;
    for (const one of cleaned) {
      const idx = merged.findIndex(
        (h) => h.hermes_session_id === one.hermes_session_id,
      );
      if (idx >= 0) {
        if (String(merged[idx].revision ?? "") === String(one.revision ?? "")) {
          continue;
        }
        merged[idx] = one;
        changed = true;
      } else {
        merged = [...merged, one];
        changed = true;
      }
    }
    if (!changed) return;
    setState({
      transcriptHints: merged,
      transcriptDirtySeq: state.transcriptDirtySeq + 1,
      error: null,
    });
  };

  const applyApprovalsProjection = (
    approvals: WorkspaceApprovalProjection[] | undefined,
    authorityHealth?: Record<string, string> | undefined,
  ) => {
    if (!Array.isArray(approvals)) return;
    const patch: Partial<FollowSpineState> = {
      approvals: [...approvals],
      error: null,
    };
    if (authorityHealth && typeof authorityHealth === "object") {
      patch.authorityHealth = {
        ...state.authorityHealth,
        ...authorityHealth,
      };
    } else if (!state.authorityHealth.command_approval || state.authorityHealth.command_approval === "unavailable") {
      patch.authorityHealth = {
        ...state.authorityHealth,
        command_approval: "ready",
      };
    }
    setState(patch);
  };

  const applyGatesProjection = (
    gates: WorkspaceGateProjection[] | undefined,
    authorityHealth?: Record<string, string> | undefined,
  ) => {
    if (!Array.isArray(gates)) return;
    const patch: Partial<FollowSpineState> = {
      gates: [...gates],
      error: null,
    };
    if (authorityHealth && typeof authorityHealth === "object") {
      patch.authorityHealth = {
        ...state.authorityHealth,
        ...authorityHealth,
      };
    } else {
      const nextHealth = { ...state.authorityHealth };
      let touched = false;
      for (const key of ["gate_1", "gate_2", "gate_3"] as const) {
        if (!nextHealth[key] || nextHealth[key] === "unavailable") {
          nextHealth[key] = "ready";
          touched = true;
        }
      }
      if (touched) patch.authorityHealth = nextHealth;
    }
    setState(patch);
  };

  const applyResultsProjection = (
    results: WorkspaceResultProjection[] | undefined,
    authorityHealth?: Record<string, string> | undefined,
  ) => {
    if (!Array.isArray(results)) return;
    const patch: Partial<FollowSpineState> = {
      // Always normalize so poll/SSE match snapshot shape (sample/real fail-closed).
      results: asResultList(results),
      error: null,
    };
    if (authorityHealth && typeof authorityHealth === "object") {
      patch.authorityHealth = {
        ...state.authorityHealth,
        ...authorityHealth,
      };
    } else if (
      !state.authorityHealth.result ||
      state.authorityHealth.result === "unavailable"
    ) {
      patch.authorityHealth = {
        ...state.authorityHealth,
        result: "ready",
      };
    }
    setState(patch);
  };

  const applyPublicCutoversProjection = (
    publicCutovers: WorkspacePublicCutoverResponse[] | undefined,
    authorityHealth?: Record<string, string> | undefined,
  ) => {
    if (!Array.isArray(publicCutovers)) return;
    const patch: Partial<FollowSpineState> = {
      publicCutovers: [...publicCutovers],
      error: null,
    };
    if (authorityHealth && typeof authorityHealth === "object") {
      patch.authorityHealth = {
        ...state.authorityHealth,
        ...authorityHealth,
      };
    }
    setState(patch);
  };

  /** V7g: Task/Attempt/Run id lists on poll/SSE (not only snapshot). Empty honest. */
  const applyVerticalIdsProjection = (
    tasks: string[] | undefined,
    attempts: string[] | undefined,
    runs: string[] | undefined,
    authorityHealth?: Record<string, string> | undefined,
  ) => {
    // Require at least one array present so partial SSE payloads can still apply.
    if (
      !Array.isArray(tasks) &&
      !Array.isArray(attempts) &&
      !Array.isArray(runs)
    ) {
      return;
    }
    const patch: Partial<FollowSpineState> = {
      error: null,
    };
    if (Array.isArray(tasks)) patch.tasks = asIdList(tasks);
    if (Array.isArray(attempts)) patch.attempts = asIdList(attempts);
    if (Array.isArray(runs)) patch.runs = asIdList(runs);
    if (authorityHealth && typeof authorityHealth === "object") {
      patch.authorityHealth = {
        ...state.authorityHealth,
        ...authorityHealth,
      };
    } else {
      const nextHealth = { ...state.authorityHealth };
      let touched = false;
      for (const key of ["task", "attempt", "run"] as const) {
        if (!nextHealth[key] || nextHealth[key] === "unavailable") {
          nextHealth[key] = "ready";
          touched = true;
        }
      }
      if (touched) patch.authorityHealth = nextHealth;
    }
    setState(patch);
  };

  const snapshotReconcile = async (signal?: AbortSignal) => {
    const snap = await fetchWorkspaceSnapshot(workspaceId, signal);
    const commands = mergeSnapshotCommands(snap);
    const approvals = Array.isArray(snap.approvals) ? [...snap.approvals] : [];
    const gates = Array.isArray(snap.gates) ? [...snap.gates] : [];
    const publicCutovers = Array.isArray(snap.public_cutovers)
      ? [...snap.public_cutovers]
      : [];
    const tasks = asIdList(snap.tasks);
    const attempts = asIdList(snap.attempts);
    const runs = asIdList(snap.runs);
    const results = asResultList(snap.results);
    const authorityHealth =
      snap.authority_health && typeof snap.authority_health === "object"
        ? { ...snap.authority_health }
        : {};
    const cursor =
      typeof snap.snapshot_workspace_cursor === "number"
        ? snap.snapshot_workspace_cursor
        : state.cursor;
    setState({
      commands,
      approvals,
      gates,
      publicCutovers,
      tasks,
      attempts,
      runs,
      results,
      authorityHealth,
      mutationEnabled: snap.mutation_enabled === true,
      cursor: Math.max(state.cursor, cursor),
      observedAt: snap.observed_at,
      snapshotCursor: snap.snapshot_workspace_cursor,
      error: null,
    });
    return snap;
  };

  const handleResync = async () => {
    setState({ resyncCount: state.resyncCount + 1 });
    try {
      const snap = await snapshotReconcile();
      const snapCursor =
        typeof snap.snapshot_workspace_cursor === "number"
          ? snap.snapshot_workspace_cursor
          : state.cursor;
      // Never rewind: missing snapshot cursor keeps prior head.
      // Plan-V6: explicit resync may advance messages off-spine — nudge refetch once.
      setState({
        cursor: Math.max(state.cursor, snapCursor),
        transcriptDirtySeq: state.transcriptDirtySeq + 1,
      });
      // Restart transport from new cursor.
      restartTransport();
    } catch (error) {
      setState({
        error: error instanceof Error ? error.message : "resync failed",
      });
    }
  };

  const runPollTick = async () => {
    if (!running || pollInFlight) return;
    pollInFlight = true;
    try {
      const page = await fetchWorkspaceFollow({
        workspaceId,
        afterCursor: state.cursor,
      });
      if (page.resync_required) {
        await handleResync();
        return;
      }
      const events = page.events ?? [];
      if (events.length) {
        applyEvents(events);
      }
      // V7d–V7g: follow pages may carry approvals + gates + results + vertical ids.
      applyApprovalsProjection(page.approvals, page.authority_health);
      applyGatesProjection(page.gates, page.authority_health);
      applyPublicCutoversProjection(
        page.public_cutovers,
        page.authority_health,
      );
      applyResultsProjection(page.results, page.authority_health);
      applyVerticalIdsProjection(
        page.tasks,
        page.attempts,
        page.runs,
        page.authority_health,
      );
      if (typeof page.next_cursor === "number") {
        setState({
          cursor: Math.max(state.cursor, page.next_cursor),
          transport: "poll",
          error: null,
        });
      } else {
        setState({ transport: "poll", error: null });
      }
    } catch (error) {
      setState({
        transport: "poll",
        error: error instanceof Error ? error.message : "follow poll failed",
      });
    } finally {
      pollInFlight = false;
    }
  };

  const clearTimers = () => {
    if (pollTimer != null) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
    if (snapTimer != null) {
      window.clearInterval(snapTimer);
      snapTimer = null;
    }
  };

  const closeSse = () => {
    if (sse) {
      sse.close();
      sse = null;
    }
  };

  const startPoll = () => {
    closeSse();
    clearTimers();
    setState({ transport: "poll" });
    void runPollTick();
    pollTimer = window.setInterval(() => {
      void runPollTick();
    }, pollMs);
    if (snapshotReconcileMs > 0) {
      snapTimer = window.setInterval(() => {
        void snapshotReconcile().catch(() => {
          /* soft */
        });
      }, snapshotReconcileMs);
    }
  };

  const startSse = () => {
    closeSse();
    clearTimers();
    if (typeof EventSource === "undefined") {
      startPoll();
      return;
    }
    const params = new URLSearchParams();
    params.set("after_cursor", String(Math.max(0, Math.floor(state.cursor))));
    const url = `/api/workspace/${encodeURIComponent(workspaceId)}/follow/stream?${params}`;
    let es: EventSource;
    try {
      es = new EventSource(url, { withCredentials: true });
    } catch {
      sseFailures += 1;
      startPoll();
      return;
    }
    sse = es;
    setState({ transport: "sse", error: null });

    const onReady = () => {
      sseFailures = 0;
      setState({ transport: "sse", error: null });
    };
    const onCommand = (ev: MessageEvent) => {
      try {
        const data = JSON.parse(String(ev.data)) as WorkspaceFollowEvent;
        applyEvents([data]);
        if (typeof data.event_id === "number") {
          setState({ cursor: Math.max(state.cursor, data.event_id) });
        }
      } catch {
        /* ignore malformed */
      }
    };
    const onApprovals = (ev: MessageEvent) => {
      try {
        const data = JSON.parse(String(ev.data)) as {
          approvals?: WorkspaceApprovalProjection[];
          authority_health?: Record<string, string>;
        };
        applyApprovalsProjection(data.approvals, data.authority_health);
      } catch {
        /* ignore malformed */
      }
    };
    const onGates = (ev: MessageEvent) => {
      try {
        const data = JSON.parse(String(ev.data)) as {
          gates?: WorkspaceGateProjection[];
          authority_health?: Record<string, string>;
        };
        applyGatesProjection(data.gates, data.authority_health);
      } catch {
        /* ignore malformed */
      }
    };
    const onResults = (ev: MessageEvent) => {
      try {
        const data = JSON.parse(String(ev.data)) as {
          results?: WorkspaceResultProjection[];
          authority_health?: Record<string, string>;
        };
        applyResultsProjection(data.results, data.authority_health);
      } catch {
        /* ignore malformed */
      }
    };
    const onVertical = (ev: MessageEvent) => {
      try {
        const data = JSON.parse(String(ev.data)) as {
          tasks?: string[];
          attempts?: string[];
          runs?: string[];
          authority_health?: Record<string, string>;
        };
        applyVerticalIdsProjection(
          data.tasks,
          data.attempts,
          data.runs,
          data.authority_health,
        );
      } catch {
        /* ignore malformed */
      }
    };
    const onTranscript = (ev: MessageEvent) => {
      try {
        const data = JSON.parse(String(ev.data)) as Record<string, unknown>;
        // Single hint per event:transcript frame (no body fields).
        applyTranscriptHints(data);
      } catch {
        /* ignore malformed */
      }
    };
    const onCursor = (ev: MessageEvent) => {
      try {
        const data = JSON.parse(String(ev.data)) as { next_cursor?: number };
        if (typeof data.next_cursor === "number") {
          setState({
            cursor: Math.max(state.cursor, data.next_cursor),
            transport: "sse",
          });
        }
      } catch {
        /* ignore */
      }
    };
    const onResync = () => {
      void handleResync();
    };
    const onReconnect = (ev: MessageEvent) => {
      try {
        const data = JSON.parse(String(ev.data)) as { next_cursor?: number };
        if (typeof data.next_cursor === "number") {
          setState({ cursor: Math.max(state.cursor, data.next_cursor) });
        }
      } catch {
        /* ignore */
      }
      // Server asked for client reconnect — open a fresh EventSource.
      if (running) {
        closeSse();
        startSse();
      }
    };
    const onErrorEvent = () => {
      /* stream-level error frame; keep open unless ES errors */
    };
    const onEsError = () => {
      sseFailures += 1;
      closeSse();
      if (sseFailures >= maxSseFailures) {
        startPoll();
      } else if (running) {
        window.setTimeout(() => {
          if (running) startSse();
        }, 1_000 * sseFailures);
      }
    };

    es.addEventListener("ready", onReady);
    es.addEventListener("command", onCommand);
    es.addEventListener("approvals", onApprovals);
    es.addEventListener("gates", onGates);
    es.addEventListener("results", onResults);
    es.addEventListener("vertical", onVertical);
    es.addEventListener("transcript", onTranscript);
    es.addEventListener("cursor", onCursor);
    es.addEventListener("resync", onResync);
    es.addEventListener("reconnect", onReconnect);
    es.addEventListener("error", onErrorEvent);
    es.onerror = onEsError;

    if (snapshotReconcileMs > 0) {
      snapTimer = window.setInterval(() => {
        void snapshotReconcile().catch(() => {
          /* soft */
        });
      }, snapshotReconcileMs);
    }
  };

  const restartTransport = () => {
    if (!running) return;
    if (preferSse && sseFailures < maxSseFailures) {
      startSse();
    } else {
      startPoll();
    }
  };

  return {
    getState: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      listener(state);
      return () => {
        listeners.delete(listener);
      };
    },
    start: () => {
      if (running) return;
      running = true;
      stopped = false;
      void (async () => {
        try {
          await snapshotReconcile();
        } catch (error) {
          setState({
            error:
              error instanceof Error ? error.message : "snapshot bootstrap failed",
          });
        }
        if (!running || stopped) return;
        restartTransport();
      })();
    },
    stop: () => {
      running = false;
      stopped = true;
      closeSse();
      clearTimers();
      setState({ transport: "idle" });
    },
    resyncNow: async () => {
      await handleResync();
    },
  };
}

/**
 * L5a: wait on the shared spine until a command reaches a terminal state.
 * Replaces Composer private pollCommandUntilTerminal dual path.
 */
export function waitForCommandTerminalOnSpine(
  spine: WorkspaceFollowSpine,
  options: {
    commandId: string;
    signal?: AbortSignal;
    /** Soft ceiling; spine keeps running after. */
    timeoutMs?: number;
  },
): Promise<WorkspaceCommandProjection | null> {
  const timeoutMs = options.timeoutMs ?? 45_000;
  return new Promise((resolve) => {
    let settled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let unsub: (() => void) | null = null;
    const finish = (value: WorkspaceCommandProjection | null) => {
      if (settled) return;
      settled = true;
      unsub?.();
      if (timer != null) clearTimeout(timer);
      options.signal?.removeEventListener("abort", onAbort);
      resolve(value);
    };
    const onAbort = () => finish(null);
    const check = (state: FollowSpineState) => {
      const match = state.commands.find(
        (c) => c.command_id === options.commandId,
      );
      if (match && isTerminalCommandState(match.state)) {
        finish(match);
      }
    };
    unsub = spine.subscribe(check);
    // subscribe already emitted current state; if that settled us, drop the
    // listener now (finish ran while unsub was still being assigned).
    if (settled) {
      unsub();
      return;
    }
    if (options.signal) {
      if (options.signal.aborted) {
        finish(null);
        return;
      }
      options.signal.addEventListener("abort", onAbort, { once: true });
    }
    // globalThis timers work in browser + node vitest (avoid bare `window`).
    timer = setTimeout(() => finish(null), timeoutMs);
  });
}

/** Pure helpers exported for unit tests. */
export const __followSpineTestUtils = {
  applyCommandEvent,
  emptyState,
  asIdList,
  asResultList,
  resultIdsFromProjection,
  normalizeSampleOrReal,
  normalizeReadStatus,
  EMPTY_AUTHORITY_HEALTH,
};
