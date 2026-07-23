import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  __followSpineTestUtils,
  createWorkspaceFollowSpine,
  waitForCommandTerminalOnSpine,
  type FollowSpineListener,
  type FollowSpineState,
  type WorkspaceFollowSpine,
} from "./workspaceFollowSpine";
import type {
  WorkspaceCommandProjection,
  WorkspaceFollowEvent,
  WorkspaceSnapshot,
} from "./workspaceClient";

const { applyCommandEvent, emptyState, asIdList, EMPTY_AUTHORITY_HEALTH } =
  __followSpineTestUtils;

const fetchWorkspaceSnapshot = vi.fn();
const fetchWorkspaceFollow = vi.fn();

vi.mock("./workspaceClient", async () => {
  const actual = await vi.importActual<typeof import("./workspaceClient")>(
    "./workspaceClient",
  );
  return {
    ...actual,
    fetchWorkspaceSnapshot: (...args: unknown[]) =>
      fetchWorkspaceSnapshot(...args),
    fetchWorkspaceFollow: (...args: unknown[]) => fetchWorkspaceFollow(...args),
  };
});

function baseCmd(
  partial: Partial<WorkspaceCommandProjection> & { command_id: string },
): WorkspaceCommandProjection {
  return {
    kind: "conversation_turn",
    state: "queued",
    version: 1,
    ...partial,
  };
}

function evt(
  partial: Partial<WorkspaceFollowEvent> & {
    command_id: string;
    event_id: number;
  },
): WorkspaceFollowEvent {
  return {
    type: "command.queued",
    state: "queued",
    ...partial,
  };
}

function baseSnapshot(
  partial: Partial<WorkspaceSnapshot> = {},
): WorkspaceSnapshot {
  return {
    workspace_id: "ws-local-main",
    observed_at: "2026-07-22T00:00:00Z",
    snapshot_workspace_cursor: 0,
    sessions: [],
    commands: [],
    approvals: [],
    tasks: [],
    attempts: [],
    runs: [],
    results: [],
    authority_health: {
      task: "unavailable",
      attempt: "unavailable",
      run: "unavailable",
      result: "unavailable",
      command_approval: "unavailable",
    },
    ...partial,
  } as WorkspaceSnapshot;
}

describe("workspaceFollowSpine helpers (L4b)", () => {
  it("inserts a new command from an event", () => {
    const next = applyCommandEvent(
      [],
      evt({
        event_id: 1,
        command_id: "c1",
        state: "queued",
        kind: "conversation_turn",
      }),
    );
    expect(next).toHaveLength(1);
    expect(next[0].command_id).toBe("c1");
    expect(next[0].state).toBe("queued");
  });

  it("updates existing command state and hermes ids", () => {
    const prior = [
      baseCmd({
        command_id: "c1",
        state: "queued",
        hermes_session_id: null,
      }),
    ];
    const next = applyCommandEvent(
      prior,
      evt({
        event_id: 2,
        command_id: "c1",
        state: "delivered",
        type: "command.delivered",
        hermes_session_id: "run_abc",
        hermes_run_id: "run_abc",
      }),
    );
    expect(next).toHaveLength(1);
    expect(next[0].state).toBe("delivered");
    expect(next[0].hermes_session_id).toBe("run_abc");
    expect(next[0].hermes_run_id).toBe("run_abc");
  });

  it("ignores events without command_id", () => {
    const prior = [baseCmd({ command_id: "c1" })];
    const next = applyCommandEvent(
      prior,
      evt({ event_id: 3, command_id: "", state: "failed" }),
    );
    expect(next[0].state).toBe("queued");
  });

  it("emptyState carries honest empty approvals (L5a)", () => {
    const s = emptyState();
    expect(s.approvals).toEqual([]);
    expect(s.commands).toEqual([]);
  });

  it("emptyState carries honest empty authority slots (L5b)", () => {
    const s = emptyState();
    expect(s.tasks).toEqual([]);
    expect(s.attempts).toEqual([]);
    expect(s.runs).toEqual([]);
    expect(s.results).toEqual([]);
    expect(s.authorityHealth).toEqual(EMPTY_AUTHORITY_HEALTH);
  });

  it("asIdList accepts string ids and {id} objects", () => {
    expect(asIdList(["a", { id: "b" }, { id: 3 }, null, ""])).toEqual([
      "a",
      "b",
    ]);
  });
});

describe("snapshot reconcile authority slots (L5b)", () => {
  beforeEach(() => {
    fetchWorkspaceSnapshot.mockReset();
    fetchWorkspaceFollow.mockReset();
    // Prevent EventSource / poll loops if start() is ever called.
    fetchWorkspaceFollow.mockResolvedValue({
      events: [],
      next_cursor: 0,
      resync_required: false,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("resyncNow copies empty authority slots + health from snapshot", async () => {
    fetchWorkspaceSnapshot.mockResolvedValue(
      baseSnapshot({
        snapshot_workspace_cursor: 7,
        tasks: [],
        attempts: [],
        runs: [],
        results: [],
        authority_health: {
          task: "unavailable",
          attempt: "unavailable",
          run: "unavailable",
          result: "unavailable",
          command_approval: "unavailable",
          command_ledger: "ready",
        },
      }),
    );

    // Avoid real EventSource during restartTransport after resync.
    vi.stubGlobal(
      "EventSource",
      class {
        close() {
          /* noop */
        }
        addEventListener() {
          /* noop */
        }
        removeEventListener() {
          /* noop */
        }
      },
    );

    const spine = createWorkspaceFollowSpine({
      preferSse: false,
      pollMs: 60_000,
      snapshotReconcileMs: 0,
    });
    try {
      await spine.resyncNow();
      const s = spine.getState();
      expect(s.tasks).toEqual([]);
      expect(s.attempts).toEqual([]);
      expect(s.runs).toEqual([]);
      expect(s.results).toEqual([]);
      expect(s.authorityHealth.task).toBe("unavailable");
      expect(s.authorityHealth.attempt).toBe("unavailable");
      expect(s.authorityHealth.run).toBe("unavailable");
      expect(s.authorityHealth.result).toBe("unavailable");
      expect(s.authorityHealth.command_approval).toBe("unavailable");
      expect(s.snapshotCursor).toBe(7);
      expect(fetchWorkspaceSnapshot).toHaveBeenCalled();
    } finally {
      spine.stop();
    }
  });

  it("command events never invent authority rows", () => {
    const prior = emptyState();
    // applyCommandEvent only returns commands; authority slots stay spine-owned.
    const nextCommands = applyCommandEvent(
      prior.commands,
      evt({
        event_id: 9,
        command_id: "c-auth",
        state: "delivered",
        type: "command.delivered",
        hermes_run_id: "run-should-not-become-authority",
      }),
    );
    expect(nextCommands[0].hermes_run_id).toBe(
      "run-should-not-become-authority",
    );
    // Authority slots are not part of applyCommandEvent return — still empty.
    expect(prior.tasks).toEqual([]);
    expect(prior.attempts).toEqual([]);
    expect(prior.runs).toEqual([]);
    expect(prior.results).toEqual([]);
  });
});

function makeFakeSpine(initial: FollowSpineState): {
  spine: WorkspaceFollowSpine;
  push: (next: FollowSpineState) => void;
} {
  let state = initial;
  const listeners = new Set<FollowSpineListener>();
  const spine: WorkspaceFollowSpine = {
    getState: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      listener(state);
      return () => {
        listeners.delete(listener);
      };
    },
    start: () => undefined,
    stop: () => undefined,
    resyncNow: async () => undefined,
  };
  return {
    spine,
    push: (next) => {
      state = next;
      for (const listener of listeners) listener(state);
    },
  };
}

describe("waitForCommandTerminalOnSpine (L5a)", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("resolves immediately when command already terminal", async () => {
    const listeners = { count: 0 };
    let state: FollowSpineState = {
      ...emptyState(),
      commands: [
        baseCmd({
          command_id: "c-done",
          state: "delivered",
          hermes_session_id: "sess-1",
          hermes_run_id: "run-1",
        }),
      ],
    };
    const spine: WorkspaceFollowSpine = {
      getState: () => state,
      subscribe: (listener) => {
        listeners.count += 1;
        listener(state);
        return () => {
          listeners.count -= 1;
        };
      },
      start: () => undefined,
      stop: () => undefined,
      resyncNow: async () => undefined,
    };
    const match = await waitForCommandTerminalOnSpine(spine, {
      commandId: "c-done",
      timeoutMs: 1_000,
    });
    expect(match?.state).toBe("delivered");
    expect(match?.hermes_session_id).toBe("sess-1");
    // Sync-terminal settle must not leave a zombie listener.
    expect(listeners.count).toBe(0);
  });

  it("resolves when a later push reaches terminal", async () => {
    const { spine, push } = makeFakeSpine({
      ...emptyState(),
      commands: [baseCmd({ command_id: "c-live", state: "queued" })],
    });
    const pending = waitForCommandTerminalOnSpine(spine, {
      commandId: "c-live",
      timeoutMs: 5_000,
    });
    push({
      ...emptyState(),
      commands: [
        baseCmd({
          command_id: "c-live",
          state: "delivered",
          hermes_run_id: "run-z",
        }),
      ],
    });
    const match = await pending;
    expect(match?.state).toBe("delivered");
    expect(match?.hermes_run_id).toBe("run-z");
  });

  it("returns null on abort", async () => {
    const { spine } = makeFakeSpine({
      ...emptyState(),
      commands: [baseCmd({ command_id: "c-ab", state: "leased" })],
    });
    const ac = new AbortController();
    const pending = waitForCommandTerminalOnSpine(spine, {
      commandId: "c-ab",
      signal: ac.signal,
      timeoutMs: 5_000,
    });
    ac.abort();
    await expect(pending).resolves.toBeNull();
  });

  it("returns null on timeout", async () => {
    vi.useFakeTimers();
    const { spine } = makeFakeSpine({
      ...emptyState(),
      commands: [baseCmd({ command_id: "c-to", state: "queued" })],
    });
    const pending = waitForCommandTerminalOnSpine(spine, {
      commandId: "c-to",
      timeoutMs: 100,
    });
    await vi.advanceTimersByTimeAsync(150);
    await expect(pending).resolves.toBeNull();
  });
});

describe("V7d durable approval projector on spine", () => {
  beforeEach(() => {
    fetchWorkspaceSnapshot.mockReset();
    fetchWorkspaceFollow.mockReset();
    fetchWorkspaceFollow.mockResolvedValue({
      events: [],
      next_cursor: 0,
      resync_required: false,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("snapshot reconcile carries pending + decided approvals", async () => {
    fetchWorkspaceSnapshot.mockResolvedValue(
      baseSnapshot({
        snapshot_workspace_cursor: 1,
        approvals: [
          {
            approval_id: "c-pend",
            run_id: "run.1",
            digest: "a".repeat(64),
            expires_at: "2099-01-01T00:00:00.000000Z",
            status: "pending",
            kind: "hermes.command_approval",
          },
          {
            approval_id: "c-done",
            run_id: "run.2",
            digest: "b".repeat(64),
            expires_at: "2099-01-01T00:00:00.000000Z",
            status: "denied",
            decision: "deny",
            decided_at: "2026-07-22T00:00:00.000000Z",
            kind: "hermes.command_approval",
          },
        ],
        tasks: [],
        attempts: [],
        runs: [],
        results: [],
        authority_health: {
          ...EMPTY_AUTHORITY_HEALTH,
          command_approval: "ready",
        },
      }),
    );

    vi.stubGlobal(
      "EventSource",
      class {
        close() {
          /* noop */
        }
        addEventListener() {
          /* noop */
        }
        removeEventListener() {
          /* noop */
        }
      },
    );

    const spine = createWorkspaceFollowSpine({
      preferSse: false,
      pollMs: 60_000,
      snapshotReconcileMs: 0,
    });
    try {
      await spine.resyncNow();
      const s = spine.getState();
      expect(s.approvals.length).toBe(2);
      expect(s.approvals[0].approval_id).toBe("c-pend");
      expect(s.approvals[1].status).toBe("denied");
      expect(s.approvals[1].decision).toBe("deny");
      expect(s.authorityHealth.command_approval).toBe("ready");
      // Empty honest authority slots remain empty (no Task invention).
      expect(s.tasks).toEqual([]);
      expect(s.attempts).toEqual([]);
      expect(s.runs).toEqual([]);
      expect(s.results).toEqual([]);
    } finally {
      spine.stop();
    }
  });
});

describe("V7e Domain Gate surfaces on spine", () => {
  beforeEach(() => {
    fetchWorkspaceSnapshot.mockReset();
    fetchWorkspaceFollow.mockReset();
    fetchWorkspaceFollow.mockResolvedValue({
      events: [],
      next_cursor: 0,
      resync_required: false,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("emptyState carries honest empty gates", () => {
    const s = emptyState();
    expect(s.gates).toEqual([]);
    expect(s.authorityHealth.gate_1).toBe("unavailable");
    expect(s.authorityHealth.gate_2).toBe("unavailable");
    expect(s.authorityHealth.gate_3).toBe("unavailable");
  });

  it("snapshot reconcile carries gates separate from approvals", async () => {
    fetchWorkspaceSnapshot.mockResolvedValue(
      baseSnapshot({
        snapshot_workspace_cursor: 3,
        approvals: [],
        gates: [
          {
            gate_id: "g1-pend",
            gate_kind: "gate1",
            status: "pending",
            task_id: "t1",
            reviewed_source_sha256: "a".repeat(64),
            kind: "gate1.formula_source",
          },
          {
            gate_id: "g2-done",
            gate_kind: "gate2",
            status: "reviewed",
            candidate_id: "c1",
            expected_digest: "b".repeat(64),
            note: "ok",
            kind: "gate2.candidate",
          },
        ],
        authority_health: {
          ...EMPTY_AUTHORITY_HEALTH,
          command_approval: "ready",
          gate_1: "ready",
          gate_2: "ready",
          gate_3: "ready",
        },
      }),
    );

    vi.stubGlobal(
      "EventSource",
      class {
        close() {}
        addEventListener() {}
        removeEventListener() {}
      },
    );

    const spine = createWorkspaceFollowSpine({
      preferSse: false,
      pollMs: 60_000,
      snapshotReconcileMs: 0,
    });
    try {
      await spine.resyncNow();
      const s = spine.getState();
      expect(s.gates.length).toBe(2);
      expect(s.gates[0].gate_id).toBe("g1-pend");
      expect(s.gates[1].status).toBe("reviewed");
      expect(s.approvals).toEqual([]);
      expect(s.authorityHealth.gate_1).toBe("ready");
      expect(s.authorityHealth.gate_2).toBe("ready");
      expect(s.authorityHealth.gate_3).toBe("ready");
      // No Task invention
      expect(s.tasks).toEqual([]);
    } finally {
      spine.stop();
    }
  });
});

describe("V7g Vertical A ids on spine", () => {
  beforeEach(() => {
    fetchWorkspaceSnapshot.mockReset();
    fetchWorkspaceFollow.mockReset();
    fetchWorkspaceFollow.mockResolvedValue({
      events: [],
      next_cursor: 0,
      resync_required: false,
    });
    // Node vitest env has no window; spine timers need it.
    vi.stubGlobal("window", {
      setInterval: (fn: TimerHandler, ms?: number) =>
        setInterval(fn as () => void, ms) as unknown as number,
      clearInterval: (id: number) => clearInterval(id as unknown as NodeJS.Timeout),
      setTimeout: (fn: TimerHandler, ms?: number) =>
        setTimeout(fn as () => void, ms) as unknown as number,
      clearTimeout: (id: number) => clearTimeout(id as unknown as NodeJS.Timeout),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("snapshot reconcile carries task/attempt/run ids with ready health", async () => {
    fetchWorkspaceSnapshot.mockResolvedValue(
      baseSnapshot({
        snapshot_workspace_cursor: 7,
        tasks: ["task.v7g.1"],
        attempts: ["attempt.v7g.1"],
        runs: ["run.v7g.1"],
        results: [
          {
            result_id: "result.v7g.1",
            id: "result.v7g.1",
            kind: "options_vertical_a",
            display_title: "AAPL sample",
            sample_or_real: "sample",
            status: "completed",
          },
        ],
        authority_health: {
          ...EMPTY_AUTHORITY_HEALTH,
          task: "ready",
          attempt: "ready",
          run: "ready",
          result: "ready",
        },
      }),
    );

    vi.stubGlobal(
      "EventSource",
      class {
        close() {}
        addEventListener() {}
        removeEventListener() {}
      },
    );

    const spine = createWorkspaceFollowSpine({
      preferSse: false,
      pollMs: 60_000,
      snapshotReconcileMs: 0,
    });
    try {
      await spine.resyncNow();
      const s = spine.getState();
      expect(s.tasks).toEqual(["task.v7g.1"]);
      expect(s.attempts).toEqual(["attempt.v7g.1"]);
      expect(s.runs).toEqual(["run.v7g.1"]);
      expect(s.results[0]?.result_id).toBe("result.v7g.1");
      expect(s.authorityHealth.task).toBe("ready");
      expect(s.authorityHealth.attempt).toBe("ready");
      expect(s.authorityHealth.run).toBe("ready");
    } finally {
      spine.stop();
    }
  });

  it("poll follow pages project task/attempt/run ids (MAJOR-2)", async () => {
    fetchWorkspaceSnapshot.mockResolvedValue(
      baseSnapshot({
        snapshot_workspace_cursor: 0,
        authority_health: { ...EMPTY_AUTHORITY_HEALTH },
      }),
    );
    fetchWorkspaceFollow.mockResolvedValue({
      events: [],
      after_cursor: 0,
      next_cursor: 1,
      resync_required: false,
      tasks: ["task.poll.1"],
      attempts: ["attempt.poll.1"],
      runs: ["run.poll.1"],
      results: [],
      authority_health: {
        task: "ready",
        attempt: "ready",
        run: "ready",
      },
    });

    vi.stubGlobal(
      "EventSource",
      class {
        close() {}
        addEventListener() {}
        removeEventListener() {}
      },
    );

    const spine = createWorkspaceFollowSpine({
      preferSse: false,
      pollMs: 60_000,
      snapshotReconcileMs: 0,
    });
    try {
      spine.start();
      // Allow poll tick after bootstrap snapshot.
      await new Promise((r) => setTimeout(r, 30));
      const s = spine.getState();
      expect(s.tasks).toEqual(["task.poll.1"]);
      expect(s.attempts).toEqual(["attempt.poll.1"]);
      expect(s.runs).toEqual(["run.poll.1"]);
      expect(s.authorityHealth.task).toBe("ready");
    } finally {
      spine.stop();
    }
  });

  it("SSE event:vertical projects task/attempt/run ids (MAJOR-2)", async () => {
    fetchWorkspaceSnapshot.mockResolvedValue(
      baseSnapshot({
        snapshot_workspace_cursor: 0,
        authority_health: { ...EMPTY_AUTHORITY_HEALTH },
      }),
    );

    type Handler = (ev: MessageEvent) => void;
    const handlers: Record<string, Handler[]> = {};
    vi.stubGlobal(
      "EventSource",
      class {
        close() {}
        addEventListener(type: string, handler: Handler) {
          (handlers[type] ||= []).push(handler);
        }
        removeEventListener() {}
      },
    );

    const spine = createWorkspaceFollowSpine({
      preferSse: true,
      pollMs: 60_000,
      snapshotReconcileMs: 0,
    });
    try {
      spine.start();
      await new Promise((r) => setTimeout(r, 20));
      const verticalHandlers = handlers["vertical"] || [];
      expect(verticalHandlers.length).toBeGreaterThan(0);
      for (const h of verticalHandlers) {
        h({
          data: JSON.stringify({
            tasks: ["task.sse.1"],
            attempts: ["attempt.sse.1"],
            runs: ["run.sse.1"],
            authority_health: {
              task: "ready",
              attempt: "ready",
              run: "ready",
            },
          }),
        } as MessageEvent);
      }
      const s = spine.getState();
      expect(s.tasks).toEqual(["task.sse.1"]);
      expect(s.attempts).toEqual(["attempt.sse.1"]);
      expect(s.runs).toEqual(["run.sse.1"]);
      expect(s.authorityHealth.task).toBe("ready");
      expect(s.authorityHealth.attempt).toBe("ready");
      expect(s.authorityHealth.run).toBe("ready");
    } finally {
      spine.stop();
    }
  });
});

describe("Plan-V6-Token-Stream-M1 transcript hints on spine", () => {
  beforeEach(() => {
    fetchWorkspaceSnapshot.mockReset();
    fetchWorkspaceFollow.mockReset();
    fetchWorkspaceFollow.mockResolvedValue({
      events: [],
      next_cursor: 0,
      resync_required: false,
    });
    vi.stubGlobal("window", {
      setInterval: (fn: TimerHandler, ms?: number) =>
        setInterval(fn as () => void, ms) as unknown as number,
      clearInterval: (id: number) =>
        clearInterval(id as unknown as NodeJS.Timeout),
      setTimeout: (fn: TimerHandler, ms?: number) =>
        setTimeout(fn as () => void, ms) as unknown as number,
      clearTimeout: (id: number) =>
        clearTimeout(id as unknown as NodeJS.Timeout),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("emptyState starts with transcriptHints=[] and dirtySeq=0", () => {
    const s = emptyState();
    expect(s.transcriptHints).toEqual([]);
    expect(s.transcriptDirtySeq).toBe(0);
  });

  it("command events with hermes_session_id bump transcriptDirtySeq", async () => {
    fetchWorkspaceSnapshot.mockResolvedValue(
      baseSnapshot({ snapshot_workspace_cursor: 0 }),
    );
    fetchWorkspaceFollow.mockResolvedValue({
      events: [
        evt({
          event_id: 3,
          command_id: "c-stream",
          state: "leased",
          type: "command.leased",
          hermes_session_id: "run_stream_1",
        }),
      ],
      after_cursor: 0,
      next_cursor: 3,
      resync_required: false,
    });

    vi.stubGlobal(
      "EventSource",
      class {
        close() {}
        addEventListener() {}
        removeEventListener() {}
      },
    );

    const spine = createWorkspaceFollowSpine({
      preferSse: false,
      pollMs: 60_000,
      snapshotReconcileMs: 0,
    });
    try {
      expect(spine.getState().transcriptDirtySeq).toBe(0);
      spine.start();
      await new Promise((r) => setTimeout(r, 40));
      const s = spine.getState();
      expect(s.transcriptDirtySeq).toBeGreaterThan(0);
      expect(s.commands.some((c) => c.command_id === "c-stream")).toBe(true);
      // No body fields invented on spine
      expect(s.transcriptHints.every((h) => !("content" in h))).toBe(true);
    } finally {
      spine.stop();
    }
  });

  it("SSE event:transcript applies body-free hint and bumps dirty", async () => {
    fetchWorkspaceSnapshot.mockResolvedValue(
      baseSnapshot({ snapshot_workspace_cursor: 0 }),
    );

    type Handler = (ev: MessageEvent) => void;
    const handlers: Record<string, Handler[]> = {};
    vi.stubGlobal(
      "EventSource",
      class {
        close() {}
        addEventListener(type: string, handler: Handler) {
          (handlers[type] ||= []).push(handler);
        }
        removeEventListener() {}
      },
    );

    const spine = createWorkspaceFollowSpine({
      preferSse: true,
      pollMs: 60_000,
      snapshotReconcileMs: 0,
    });
    try {
      spine.start();
      await new Promise((r) => setTimeout(r, 25));
      const th = handlers["transcript"] || [];
      expect(th.length).toBeGreaterThan(0);
      const before = spine.getState().transcriptDirtySeq;
      for (const h of th) {
        h({
          data: JSON.stringify({
            hermes_session_id: "run_hint_1",
            phase: "waiting",
            revision: "run_hint_1|c1|leased|1",
            transport: "spine-refetch",
            content: "SMUGGLE_BODY",
            text: "nope",
            limitations: [
              "assistant_body_not_on_follow_spine",
              "not_provider_token_passthrough",
              "messages_bff_is_text_authority",
            ],
          }),
        } as MessageEvent);
      }
      const s = spine.getState();
      expect(s.transcriptDirtySeq).toBeGreaterThan(before);
      expect(s.transcriptHints).toHaveLength(1);
      expect(s.transcriptHints[0]?.hermes_session_id).toBe("run_hint_1");
      expect(s.transcriptHints[0]?.phase).toBe("waiting");
      expect(s.transcriptHints[0]?.transport).toBe("spine-refetch");
      expect((s.transcriptHints[0] as { content?: string }).content).toBeUndefined();
    } finally {
      spine.stop();
    }
  });

  it("rejects web_/wm_ transcript hints", async () => {
    fetchWorkspaceSnapshot.mockResolvedValue(
      baseSnapshot({ snapshot_workspace_cursor: 0 }),
    );
    type Handler = (ev: MessageEvent) => void;
    const handlers: Record<string, Handler[]> = {};
    vi.stubGlobal(
      "EventSource",
      class {
        close() {}
        addEventListener(type: string, handler: Handler) {
          (handlers[type] ||= []).push(handler);
        }
        removeEventListener() {}
      },
    );
    const spine = createWorkspaceFollowSpine({
      preferSse: true,
      pollMs: 60_000,
      snapshotReconcileMs: 0,
    });
    try {
      spine.start();
      await new Promise((r) => setTimeout(r, 25));
      for (const h of handlers["transcript"] || []) {
        h({
          data: JSON.stringify({
            hermes_session_id: "web_bad",
            phase: "waiting",
            revision: "x",
          }),
        } as MessageEvent);
        h({
          data: JSON.stringify({
            hermes_session_id: "wm_bad",
            phase: "waiting",
            revision: "y",
          }),
        } as MessageEvent);
      }
      expect(spine.getState().transcriptHints).toEqual([]);
    } finally {
      spine.stop();
    }
  });

  it("same revision does not re-bump dirty", async () => {
    fetchWorkspaceSnapshot.mockResolvedValue(
      baseSnapshot({ snapshot_workspace_cursor: 0 }),
    );
    type Handler = (ev: MessageEvent) => void;
    const handlers: Record<string, Handler[]> = {};
    vi.stubGlobal(
      "EventSource",
      class {
        close() {}
        addEventListener(type: string, handler: Handler) {
          (handlers[type] ||= []).push(handler);
        }
        removeEventListener() {}
      },
    );
    const spine = createWorkspaceFollowSpine({
      preferSse: true,
      pollMs: 60_000,
      snapshotReconcileMs: 0,
    });
    try {
      spine.start();
      await new Promise((r) => setTimeout(r, 25));
      const payload = {
        hermes_session_id: "run_dedupe",
        phase: "waiting",
        revision: "rev-same",
      };
      for (const h of handlers["transcript"] || []) {
        h({ data: JSON.stringify(payload) } as MessageEvent);
      }
      const mid = spine.getState().transcriptDirtySeq;
      for (const h of handlers["transcript"] || []) {
        h({ data: JSON.stringify(payload) } as MessageEvent);
      }
      expect(spine.getState().transcriptDirtySeq).toBe(mid);
      // new revision bumps again
      for (const h of handlers["transcript"] || []) {
        h({
          data: JSON.stringify({ ...payload, revision: "rev-next", phase: "final" }),
        } as MessageEvent);
      }
      expect(spine.getState().transcriptDirtySeq).toBeGreaterThan(mid);
      expect(spine.getState().transcriptHints[0]?.phase).toBe("final");
    } finally {
      spine.stop();
    }
  });
});
