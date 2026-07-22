import { describe, expect, it } from "vitest";

import {
  displayableTranscriptMessages,
  isNearBottom,
  isUsableHermesApiSessionId,
  mergePendingUserMessage,
  pickLatestHermesSessionId,
} from "./transcriptHelpers";

describe("transcriptHelpers (L3a + L3b)", () => {
  it("accepts canonical managed Hermes ids and rejects platform registry ids", () => {
    expect(isUsableHermesApiSessionId("run_127dd275e6964abc")).toBe(true);
    expect(isUsableHermesApiSessionId("agent:main:l2a")).toBe(true);
    expect(isUsableHermesApiSessionId("  run_abc  ")).toBe(true);
    expect(isUsableHermesApiSessionId("web_abc")).toBe(true);
    expect(isUsableHermesApiSessionId("wm_local")).toBe(false);
    expect(isUsableHermesApiSessionId("")).toBe(false);
    expect(isUsableHermesApiSessionId("   ")).toBe(false);
    expect(isUsableHermesApiSessionId(null)).toBe(false);
    expect(isUsableHermesApiSessionId(undefined)).toBe(false);
  });

  it("filters to non-empty user/assistant messages only", () => {
    const rows = displayableTranscriptMessages([
      { id: "1", role: "system", content: "nope" },
      { id: "2", role: "user", content: "  hi  " },
      { id: "3", role: "assistant", content: "" },
      { id: "4", role: "assistant", content: "L2a-pong" },
      { id: "5", role: "tool", content: "{}" },
    ]);
    expect(rows.map((r) => r.id)).toEqual(["2", "4"]);
  });

  it("picks latest usable hermes_session_id from commands", () => {
    expect(pickLatestHermesSessionId([])).toBeNull();
    expect(
      pickLatestHermesSessionId([
        { command_id: "c1", state: "delivered", hermes_session_id: "web_x" },
        { command_id: "c2", hermes_session_id: "wm_y" },
      ]),
    ).toBeNull();
    expect(
      pickLatestHermesSessionId([
        { command_id: "c1", state: "succeeded", hermes_session_id: "run_old" },
        { command_id: "c2", state: "delivered", hermes_session_id: "web_skip" },
        { command_id: "c3", state: "succeeded", hermes_session_id: "web_new" },
      ]),
    ).toEqual({ hermesSessionId: "web_new", commandId: "c3" });
  });

  it("isNearBottom respects threshold", () => {
    expect(
      isNearBottom({ scrollHeight: 1000, scrollTop: 900, clientHeight: 100 }, 80),
    ).toBe(true);
    expect(
      isNearBottom({ scrollHeight: 1000, scrollTop: 100, clientHeight: 100 }, 80),
    ).toBe(false);
    expect(isNearBottom(null)).toBe(true);
  });

  it("mergePendingUserMessage appends until server has same user text", () => {
    const withPending = mergePendingUserMessage(
      [{ id: "a1", role: "assistant", content: "hi" }],
      "  hello  ",
    );
    expect(withPending.map((m) => m.id)).toEqual(["a1", "local-pending-user"]);
    expect(withPending[1]?.content).toBe("hello");

    const already = mergePendingUserMessage(
      [
        { id: "u1", role: "user", content: "hello" },
        { id: "a1", role: "assistant", content: "pong" },
      ],
      "hello",
    );
    expect(already.map((m) => m.id)).toEqual(["u1", "a1"]);

    expect(mergePendingUserMessage([], null)).toEqual([]);
    expect(mergePendingUserMessage([], "   ")).toEqual([]);
  });
});
