/**
 * L4b-SSE-Follow-M1: shared durable workspace follow spine.
 *
 * Prefer EventSource on GET …/follow/stream; fall back to GET …/follow poll.
 * Command lifecycle only — no assistant bodies. On resync: snapshot then continue.
 */

import {
  fetchWorkspaceFollow,
  fetchWorkspaceSnapshot,
  isTerminalCommandState,
  type WorkspaceApprovalProjection,
  type WorkspaceCommandProjection,
  type WorkspaceFollowEvent,
  type WorkspaceSnapshot,
} from "@/lib/hermes/workspaceClient";
import { PLATFORM_WORKSPACE_ID } from "@/lib/hermes/darkIdentity";

export type FollowTransport = "sse" | "poll" | "idle";

export type FollowSpineState = {
  cursor: number;
  commands: WorkspaceCommandProjection[];
  /** L5a: Hermes command-approval challenges from snapshot (empty until projector). */
  approvals: WorkspaceApprovalProjection[];
  lastEvents: WorkspaceFollowEvent[];
  transport: FollowTransport;
  resyncCount: number;
  error: string | null;
  observedAt?: string;
  snapshotCursor?: number | null;
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

function emptyState(): FollowSpineState {
  return {
    cursor: 0,
    commands: [],
    approvals: [],
    lastEvents: [],
    transport: "idle",
    resyncCount: 0,
    error: null,
  };
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
    client_request_id: event.client_request_id ?? prev?.client_request_id ?? null,
    client_action_id: event.client_action_id ?? prev?.client_action_id ?? null,
    platform_session_id:
      event.platform_session_id ?? prev?.platform_session_id ?? null,
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
    for (const event of events) {
      commands = applyCommandEvent(commands, event);
    }
    setState({
      commands,
      lastEvents: events,
      error: null,
    });
  };

  const snapshotReconcile = async (signal?: AbortSignal) => {
    const snap = await fetchWorkspaceSnapshot(workspaceId, signal);
    const commands = mergeSnapshotCommands(snap);
    const approvals = Array.isArray(snap.approvals) ? [...snap.approvals] : [];
    const cursor =
      typeof snap.snapshot_workspace_cursor === "number"
        ? snap.snapshot_workspace_cursor
        : state.cursor;
    setState({
      commands,
      approvals,
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
      setState({ cursor: Math.max(state.cursor, snapCursor) });
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
};
