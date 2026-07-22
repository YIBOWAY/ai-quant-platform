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
      // @ts-expect-error intentional empty id
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
