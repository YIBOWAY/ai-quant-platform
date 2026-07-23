import { describe, expect, it } from "vitest";

import {
  assistantContentLength,
  assistantTextGrew,
  deriveAssistantPhase,
  displayableTranscriptMessages,
  isNearBottom,
  isUsableHermesApiSessionId,
  mergePendingUserMessage,
  pickLatestHermesSessionId,
  sanitizeTranscriptHint,
} from "./transcriptHelpers";

describe("transcriptHelpers (L3a + L3b)", () => {
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

describe("Plan-V6-Token-Stream-M1 phase helpers", () => {
  it("TC-TS-07 accept → waiting", () => {
    expect(
      deriveAssistantPhase({
        hasActiveSession: false,
        submitAccepted: true,
      }),
    ).toBe("waiting");
  });

  it("TC-TS-08 delivered + assistant → final", () => {
    expect(
      deriveAssistantPhase({
        hasActiveSession: true,
        commandState: "delivered",
        assistantContentLength: 8,
      }),
    ).toBe("final");
  });

  it("TC-TS-09 messages unavailable → unavailable", () => {
    expect(
      deriveAssistantPhase({
        hasActiveSession: true,
        messagesReadStatus: "unavailable",
      }),
    ).toBe("unavailable");
  });

  it("partial when assistant grows before terminal", () => {
    expect(
      deriveAssistantPhase({
        hasActiveSession: true,
        commandState: "leased",
        assistantContentLength: 4,
      }),
    ).toBe("partial");
  });

  it("assistantContentLength and growth", () => {
    const a = [
      { id: "1", role: "user" as const, content: "hi" },
      { id: "2", role: "assistant" as const, content: "ab" },
    ];
    const b = [
      { id: "1", role: "user" as const, content: "hi" },
      { id: "2", role: "assistant" as const, content: "abcd" },
    ];
    expect(assistantContentLength(a)).toBe(2);
    expect(assistantContentLength(b)).toBe(4);
    expect(assistantTextGrew(a, b)).toBe(true);
    expect(assistantTextGrew(b, a)).toBe(false);
  });

  it("TC-V8-M2-11 delivered without assistant growth → final (no fake partial)", () => {
    expect(
      deriveAssistantPhase({
        hasActiveSession: true,
        commandState: "delivered",
        assistantContentLength: 0,
        submitAccepted: true,
        priorPhase: "waiting",
      }),
    ).toBe("final");
  });

  it("TC-V8-M2-11 running without assistant growth stays waiting (no fake typing)", () => {
    expect(
      deriveAssistantPhase({
        hasActiveSession: true,
        commandState: "running",
        assistantContentLength: 0,
        submitAccepted: true,
      }),
    ).toBe("waiting");
    expect(
      deriveAssistantPhase({
        hasActiveSession: true,
        commandState: "running",
        assistantContentLength: 0,
        priorPhase: "waiting",
      }),
    ).not.toBe("partial");
  });

  it("TC-TS-06 sanitize rejects web_/wm_", () => {
    expect(
      sanitizeTranscriptHint({
        hermes_session_id: "web_x",
        phase: "waiting",
        revision: "1",
      }),
    ).toBeNull();
    expect(
      sanitizeTranscriptHint({
        hermes_session_id: "wm_x",
        phase: "waiting",
        revision: "1",
      }),
    ).toBeNull();
    const ok = sanitizeTranscriptHint({
      hermes_session_id: "run_ok",
      phase: "waiting",
      revision: "r1",
      content: "SMUGGLE",
      text: "nope",
    });
    expect(ok).not.toBeNull();
    expect(ok!.hermes_session_id).toBe("run_ok");
    expect((ok as { content?: string }).content).toBeUndefined();
  });

  it("TC-TS-19 limitations default honesty", () => {
    const ok = sanitizeTranscriptHint({
      hermes_session_id: "run_ok",
      phase: "final",
      revision: 2,
    });
    expect(ok!.limitations).toEqual(
      expect.arrayContaining([
        "not_provider_token_passthrough",
        "messages_bff_is_text_authority",
        "assistant_body_not_on_follow_spine",
      ]),
    );
    expect(ok!.transport).toBe("spine-refetch");
  });
});
