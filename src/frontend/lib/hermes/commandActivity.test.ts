import { describe, expect, it } from "vitest";

import {
  activityToolLabel,
  activityStageLabel,
  activityTransportLabel,
  commandStateLabel,
  isActiveCommandState,
  selectChatCommand,
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

  it("selects the newest command for the active Hermes session", () => {
    const selected = selectChatCommand(
      [
        cmd({
          command_id: "other",
          hermes_session_id: "web_other",
          updated_at: "2026-08-27T10:02:00Z",
        }),
        cmd({
          command_id: "older",
          hermes_session_id: "web_active",
          updated_at: "2026-08-27T10:00:00Z",
        }),
        cmd({
          command_id: "newer",
          hermes_session_id: "web_active",
          updated_at: "2026-08-27T10:01:00Z",
        }),
      ],
      "web_active",
    );

    expect(selected?.command_id).toBe("newer");
    expect(selectChatCommand([], "web_active")).toBeNull();
    expect(selectChatCommand([cmd({ command_id: "x" })], null)).toBeNull();
  });

  it("maps activity and transport to user-facing Chinese without raw detail", () => {
    expect(activityStageLabel("using_tool", "delivered", true)).toBe(
      "正在使用本机工具",
    );
    expect(activityStageLabel(null, "delivered", true)).toBe("Hermes 正在处理");
    expect(activityStageLabel("succeeded", "delivered", true)).toBe(
      "正在整理回复",
    );
    expect(activityStageLabel(null, "failed", true)).toBe("处理失败");
    expect(activityStageLabel("running", "failed", true)).toBe("处理失败");
    expect(activityTransportLabel("sse", null, true)).toBe("实时连接");
    expect(activityTransportLabel("poll", null, true)).toBe("正在定时获取进度");
    expect(activityTransportLabel("sse", "secret socket detail", true)).toBe(
      "连接中断，任务可能仍在后台继续",
    );
    expect(
      activityToolLabel(
        {
          tool_state: "completed",
          tool_duration_seconds: 1.8,
        },
        true,
      ),
    ).toBe("本机工具完成 · 1.8 秒");
  });
});
