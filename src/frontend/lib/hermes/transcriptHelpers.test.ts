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
  createQuietRefetchScheduler,
} from "./transcriptHelpers";

describe("transcriptHelpers (L3a + L3b)", () => {
  it("accepts Hermes-managed web session ids and rejects platform-only markers", () => {
    expect(isUsableHermesApiSessionId("run_127dd275e6964abc")).toBe(true);
    expect(isUsableHermesApiSessionId("agent:main:l2a")).toBe(true);
    expect(isUsableHermesApiSessionId("  run_abc  ")).toBe(true);
    expect(
      isUsableHermesApiSessionId(
        "web_0123456789abcdef0123456789abcdef01234567",
      ),
    ).toBe(true);
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
        {
          command_id: "c1",
          state: "succeeded",
          hermes_session_id: "web_real",
        },
        { command_id: "c2", state: "succeeded", hermes_session_id: "wm_y" },
      ]),
    ).toEqual({ hermesSessionId: "web_real", commandId: "c1" });
    expect(
      pickLatestHermesSessionId([
        {
          command_id: "c1",
          state: "succeeded",
          hermes_session_id: "run_old",
        },
        {
          command_id: "c2",
          state: "delivered",
          hermes_session_id: "web_unfinished",
        },
        {
          command_id: "c3",
          state: "succeeded",
          hermes_session_id: "run_new",
        },
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

  it("TC-TS-08 succeeded + assistant → final", () => {
    expect(
      deriveAssistantPhase({
        hasActiveSession: true,
        commandState: "succeeded",
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

  it("delivered without replay-backed success stays waiting", () => {
    expect(
      deriveAssistantPhase({
        hasActiveSession: true,
        commandState: "delivered",
        assistantContentLength: 0,
        submitAccepted: true,
        priorPhase: "waiting",
      }),
    ).toBe("waiting");
  });

  it("outcome_unknown remains recoverable rather than terminal", () => {
    expect(
      deriveAssistantPhase({
        hasActiveSession: true,
        commandState: "outcome_unknown",
        assistantContentLength: 0,
        priorPhase: "waiting",
      }),
    ).toBe("waiting");
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

  it("TC-TS-06 sanitize accepts Hermes web_* and rejects platform wm_*", () => {
    const managed = sanitizeTranscriptHint({
      hermes_session_id: "web_x",
      phase: "waiting",
      revision: "1",
    });
    expect(managed).not.toBeNull();
    expect(managed!.hermes_session_id).toBe("web_x");
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

describe("createQuietRefetchScheduler (V8-M2 GAP-09)", () => {
  async function drain(times = 20) {
    for (let i = 0; i < times; i += 1) {
      await Promise.resolve();
    }
  }

  function installFakeTimers() {
    const queue: Array<{ id: number; fn: () => void; ms: number; due: number }> =
      [];
    let now = 0;
    let nextId = 1;
    const setTimer = (fn: () => void, ms: number) => {
      const id = nextId++;
      queue.push({ id, fn, ms, due: now + ms });
      return id as unknown as ReturnType<typeof setTimeout>;
    };
    const clearTimer = (id: ReturnType<typeof setTimeout>) => {
      const n = id as unknown as number;
      const idx = queue.findIndex((q) => q.id === n);
      if (idx >= 0) queue.splice(idx, 1);
    };
    const flush = async (ms: number) => {
      now += ms;
      // Multi-pass: timers may enqueue more timers + microtasks.
      for (let pass = 0; pass < 10; pass += 1) {
        const due = queue
          .filter((q) => q.due <= now)
          .sort((a, b) => a.due - b.due || a.id - b.id);
        if (!due.length) {
          await drain(5);
          const more = queue.filter((q) => q.due <= now);
          if (!more.length) break;
          continue;
        }
        for (const t of due) {
          const idx = queue.findIndex((q) => q.id === t.id);
          if (idx >= 0) queue.splice(idx, 1);
          t.fn();
        }
        await drain(10);
      }
    };
    return { setTimer, clearTimer, flush, queue };
  }

  it("coalesces bursts into one fetch", async () => {
    const clock = installFakeTimers();
    const calls: string[] = [];
    let release!: () => void;
    const gate = new Promise<void>((r) => {
      release = r;
    });
    const sched = createQuietRefetchScheduler({
      coalesceMs: 200,
      setTimer: clock.setTimer,
      clearTimer: clock.clearTimer,
      fetch: async (sid) => {
        calls.push(sid);
        await gate;
      },
    });
    sched.schedule("s1");
    sched.schedule("s1");
    sched.schedule("s1");
    await clock.flush(200);
    expect(calls).toEqual(["s1"]);
    expect(sched.isInFlight()).toBe(true);
    release();
    await drain(20);
    expect(sched.isInFlight()).toBe(false);
    expect(calls).toEqual(["s1"]);
    sched.dispose();
  });

  it("pending-bit fires exactly one follow-up after in-flight settles", async () => {
    const clock = installFakeTimers();
    const calls: string[] = [];
    let releaseFirst!: () => void;
    const firstGate = new Promise<void>((r) => {
      releaseFirst = r;
    });
    let fetchCount = 0;
    const sched = createQuietRefetchScheduler({
      coalesceMs: 200,
      setTimer: clock.setTimer,
      clearTimer: clock.clearTimer,
      fetch: async (sid) => {
        fetchCount += 1;
        calls.push(`${sid}:${fetchCount}`);
        if (fetchCount === 1) await firstGate;
      },
    });
    sched.schedule("s1");
    await clock.flush(200);
    expect(sched.isInFlight()).toBe(true);
    expect(calls).toEqual(["s1:1"]);
    // Dirty bumps during flight → pending, not a retry chain.
    sched.schedule("s1");
    sched.schedule("s1");
    expect(sched.isPending()).toBe(true);
    // No coalesce timers while in-flight (pending bit only).
    expect(clock.queue.length).toBe(0);
    releaseFirst();
    await drain(20);
    // Follow-up scheduled via coalesce timer after settle.
    expect(sched.isInFlight()).toBe(false);
    expect(clock.queue.length).toBe(1);
    await clock.flush(200);
    await drain(20);
    expect(calls).toEqual(["s1:1", "s1:2"]);
    expect(sched.isPending()).toBe(false);
    expect(sched.isInFlight()).toBe(false);
    sched.dispose();
  });

  it("dispose drops pending and cancels coalesce timer", async () => {
    const clock = installFakeTimers();
    const calls: string[] = [];
    const sched = createQuietRefetchScheduler({
      coalesceMs: 200,
      setTimer: clock.setTimer,
      clearTimer: clock.clearTimer,
      fetch: async (sid) => {
        calls.push(sid);
      },
    });
    sched.schedule("s1");
    sched.dispose();
    await clock.flush(500);
    expect(calls).toEqual([]);
  });

  it("does not spin timers while a hung fetch stays in-flight", async () => {
    const clock = installFakeTimers();
    const calls: string[] = [];
    const hung = new Promise<void>(() => {
      /* never settles */
    });
    const sched = createQuietRefetchScheduler({
      coalesceMs: 200,
      setTimer: clock.setTimer,
      clearTimer: clock.clearTimer,
      fetch: async (sid) => {
        calls.push(sid);
        await hung;
      },
    });
    sched.schedule("s1");
    await clock.flush(200);
    expect(calls).toEqual(["s1"]);
    // Interval-like nudges while hung.
    for (let i = 0; i < 10; i += 1) {
      sched.schedule("s1");
      await clock.flush(200);
    }
    // Still exactly one fetch; pending bit set; no timer storm.
    expect(calls).toEqual(["s1"]);
    expect(sched.isPending()).toBe(true);
    expect(clock.queue.length).toBe(0);
    sched.dispose();
  });
});
