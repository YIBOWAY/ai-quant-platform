import { afterEach, describe, expect, it, vi } from "vitest";

import {
  __followSpineTestUtils,
  waitForCommandTerminalOnSpine,
  type FollowSpineListener,
  type FollowSpineState,
  type WorkspaceFollowSpine,
} from "./workspaceFollowSpine";
import type { WorkspaceCommandProjection } from "./workspaceClient";
import type { WorkspaceFollowEvent } from "./workspaceClient";

const { applyCommandEvent, emptyState } = __followSpineTestUtils;

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
