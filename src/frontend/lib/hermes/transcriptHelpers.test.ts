import { describe, expect, it } from "vitest";

import {
  displayableTranscriptMessages,
  isUsableHermesApiSessionId,
  pickLatestHermesSessionId,
} from "./transcriptHelpers";

describe("transcriptHelpers (L3a)", () => {
  it("accepts Hermes API session ids and rejects registry/workspace markers", () => {
    expect(isUsableHermesApiSessionId("run_127dd275e6964abc")).toBe(true);
    expect(isUsableHermesApiSessionId("agent:main:l2a")).toBe(true);
    expect(isUsableHermesApiSessionId("  run_abc  ")).toBe(true);
    expect(isUsableHermesApiSessionId("web_abc")).toBe(false);
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
        { command_id: "c1", hermes_session_id: "web_x" },
        { command_id: "c2", hermes_session_id: "wm_y" },
      ]),
    ).toBeNull();
    expect(
      pickLatestHermesSessionId([
        { command_id: "c1", hermes_session_id: "run_old" },
        { command_id: "c2", hermes_session_id: "web_skip" },
        { command_id: "c3", hermes_session_id: "run_new" },
      ]),
    ).toEqual({ hermesSessionId: "run_new", commandId: "c3" });
  });
});
