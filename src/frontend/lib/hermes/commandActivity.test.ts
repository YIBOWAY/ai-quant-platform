import { describe, expect, it } from "vitest";

import {
  commandStateLabel,
  isActiveCommandState,
  shortId,
  sortCommandsNewestFirst,
} from "./commandActivity";
import type { WorkspaceCommandProjection } from "./workspaceClient";

function cmd(
  partial: Partial<WorkspaceCommandProjection> & { command_id: string },
): WorkspaceCommandProjection {
  return {
    kind: "conversation_turn",
    state: "queued",
    version: 1,
    ...partial,
  };
}

describe("commandActivity (L4a)", () => {
  it("sorts newest first by updated_at", () => {
    const rows = sortCommandsNewestFirst([
      cmd({
        command_id: "c-old",
        updated_at: "2026-07-22T10:00:00.000Z",
      }),
      cmd({
        command_id: "c-new",
        updated_at: "2026-07-22T12:00:00.000Z",
      }),
      cmd({
        command_id: "c-mid",
        updated_at: "2026-07-22T11:00:00.000Z",
      }),
    ]);
    expect(rows.map((r) => r.command_id)).toEqual(["c-new", "c-mid", "c-old"]);
  });

  it("shortId truncates", () => {
    expect(shortId("abcdefghij")).toBe("abcdefgh…");
    expect(shortId("abc")).toBe("abc");
    expect(shortId(null)).toBe("");
  });

  it("labels states and active set", () => {
    expect(commandStateLabel("delivered")).toBe("Delivered");
    expect(commandStateLabel("delivered", true)).toBe("已送达");
    expect(commandStateLabel("succeeded")).toBe("Succeeded");
    expect(commandStateLabel("succeeded", true)).toBe("已成功");
    expect(isActiveCommandState("queued")).toBe(true);
    expect(isActiveCommandState("leased")).toBe(true);
    expect(isActiveCommandState("delivered")).toBe(false);
  });
});
