import { describe, expect, it } from "vitest";

import { __followSpineTestUtils } from "./workspaceFollowSpine";
import type { WorkspaceCommandProjection } from "./workspaceClient";
import type { WorkspaceFollowEvent } from "./workspaceClient";

const { applyCommandEvent } = __followSpineTestUtils;

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
});
