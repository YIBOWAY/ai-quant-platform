import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CHAT_PROMPT_MAX_BYTES,
  PLATFORM_WORKSPACE_ID,
  PROVIDER_POLICY_DIGEST,
} from "./darkIdentity";
import {
  WorkspaceClientError,
  fetchHermesSessionMessages,
  fetchLatestAssistantText,
  fetchWorkspaceFollow,
  isTerminalCommandState,
  latestAssistantText,
  pollCommandUntilTerminal,
  preflightPrompt,
  previewAssistantText,
  readCsrfToken,
  sendComposerTurn,
  utf8ByteLength,
} from "./workspaceClient";

describe("workspaceClient preflight", () => {
  it("rejects empty / whitespace prompts", () => {
    expect(() => preflightPrompt("")).toThrow(WorkspaceClientError);
    expect(() => preflightPrompt("   ")).toThrow(/non-empty/);
  });

  it("rejects prompts over 16 KiB UTF-8 without truncating", () => {
    const oversized = "a".repeat(CHAT_PROMPT_MAX_BYTES + 1);
    expect(utf8ByteLength(oversized)).toBe(CHAT_PROMPT_MAX_BYTES + 1);
    expect(() => preflightPrompt(oversized)).toThrow(/16 KiB/);
  });

  it("accepts a prompt at the exact byte ceiling", () => {
    const exact = "b".repeat(CHAT_PROMPT_MAX_BYTES);
    expect(preflightPrompt(exact)).toBe(exact);
  });

  it("reads CSRF cookie by name", () => {
    expect(readCsrfToken("qs_aw_csrf=token-abc; other=1")).toBe("token-abc");
    expect(readCsrfToken("other=1")).toBeNull();
  });
});

describe("sendComposerTurn", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("bootstraps owner, creates session, then submit-turn with four fields + CSRF", async () => {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    let csrfCookie = "";
    const memory = new Map<string, string>();

    // Node vitest env: stub minimal browser globals used by the client.
    vi.stubGlobal("crypto", {
      randomUUID: () => "11111111-1111-4111-8111-111111111111",
    });
    vi.stubGlobal("document", {
      get cookie() {
        return csrfCookie;
      },
    });
    vi.stubGlobal("window", {
      sessionStorage: {
        getItem: (key: string) => memory.get(key) ?? null,
        setItem: (key: string, value: string) => {
          memory.set(key, value);
        },
        clear: () => memory.clear(),
      },
    });

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        calls.push({ url, init: init ?? {} });
        const method = (init?.method ?? "GET").toUpperCase();

        if (url.endsWith("/api/auth/owner/session") && method === "GET") {
          return new Response(JSON.stringify({ detail: { code: "auth", message: "no" } }), {
            status: 401,
            headers: { "content-type": "application/json" },
          });
        }
        if (url.endsWith("/api/auth/owner/bootstrap-token/issue")) {
          return new Response(
            JSON.stringify({ bootstrap_token: "t".repeat(40) }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }
        if (url.endsWith("/api/auth/owner/bootstrap")) {
          csrfCookie = "qs_aw_csrf=csrf-live-token";
          return new Response(
            JSON.stringify({
              session_id: "sess-1",
              csrf_token: "csrf-live-token",
              mutation_enabled: true,
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }
        if (url.includes("/api/workspace/") && url.endsWith("/act")) {
          const headers = new Headers(init?.headers as HeadersInit);
          expect(headers.get("X-CSRF-Token")).toBe("csrf-live-token");
          expect(init?.credentials).toBe("same-origin");
          const body = JSON.parse(String(init?.body)) as {
            action: Record<string, unknown>;
          };
          expect(body.action.kind).toBe("managed_session.create");
          expect(body.action.provider_policy_digest).toBe(PROVIDER_POLICY_DIGEST);
          expect(body.action.prompt).toBeUndefined();
          return new Response(
            JSON.stringify({
              status: "accepted",
              client_action_id: body.action.client_action_id,
              platform_session_id: "managed-1",
              session_ref: "session:managed-1",
              mutation_enabled: true,
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }
        if (url.endsWith("/api/agent/workspace/submit-turn")) {
          const headers = new Headers(init?.headers as HeadersInit);
          expect(headers.get("X-CSRF-Token")).toBe("csrf-live-token");
          const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
          expect(Object.keys(body).sort()).toEqual([
            "client_action_id",
            "managed_session_ref",
            "prompt",
            "workspace_id",
          ]);
          expect(body.workspace_id).toBe(PLATFORM_WORKSPACE_ID);
          expect(body.managed_session_ref).toBe("session:managed-1");
          expect(body.prompt).toBe("Reply with exactly: L2a-pong");
          return new Response(
            JSON.stringify({
              status: "accepted",
              client_action_id: body.client_action_id,
              command_id: "00000000-0000-4000-8000-0000000000aa",
              payload_ref: "payload:sha256:" + "a".repeat(64),
              payload_digest: "a".repeat(64),
              kind: "conversation.turn",
              mutation_enabled: true,
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }
        throw new Error(`unexpected fetch ${method} ${url}`);
      }),
    );

    const receipt = await sendComposerTurn({
      prompt: "Reply with exactly: L2a-pong",
      clientActionId: "intent-fe-0001",
    });

    expect(receipt.status).toBe("accepted");
    expect(receipt.command_id).toBeTruthy();
    expect(receipt.payload_ref).toMatch(/^payload:sha256:/);
    expect(receipt).not.toHaveProperty("prompt");

    const paths = calls.map((c) => new URL(c.url, "http://127.0.0.1:3001").pathname);
    expect(paths).toEqual([
      "/api/auth/owner/session",
      "/api/auth/owner/bootstrap-token/issue",
      "/api/auth/owner/bootstrap",
      `/api/workspace/${PLATFORM_WORKSPACE_ID}/act`,
      "/api/agent/workspace/submit-turn",
    ]);
  });

  it("fails closed on empty prompt before any network", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(sendComposerTurn({ prompt: "  " })).rejects.toThrow(/non-empty/);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("isTerminalCommandState", () => {
  it("recognizes terminal lifecycle states only", () => {
    expect(isTerminalCommandState("delivered")).toBe(true);
    expect(isTerminalCommandState("failed")).toBe(true);
    expect(isTerminalCommandState("rejected")).toBe(true);
    expect(isTerminalCommandState("cancelled")).toBe(true);
    expect(isTerminalCommandState("timed_out")).toBe(true);
    expect(isTerminalCommandState("outcome_unknown")).toBe(true);
    expect(isTerminalCommandState("queued")).toBe(false);
    expect(isTerminalCommandState("leased")).toBe(false);
    expect(isTerminalCommandState(null)).toBe(false);
    expect(isTerminalCommandState(undefined)).toBe(false);
  });
});

describe("fetchWorkspaceFollow", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("GETs follow with after_cursor and returns event page", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        expect(url).toContain(`/api/workspace/${PLATFORM_WORKSPACE_ID}/follow`);
        expect(url).toContain("after_cursor=3");
        expect((init?.method ?? "GET").toUpperCase()).toBe("GET");
        expect(init?.credentials).toBe("same-origin");
        return new Response(
          JSON.stringify({
            events: [
              {
                event_id: 4,
                type: "command.leased",
                command_id: "cmd-1",
                state: "leased",
              },
            ],
            after_cursor: 3,
            next_cursor: 4,
            resync_required: false,
            mutation_enabled: true,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }),
    );

    const page = await fetchWorkspaceFollow({ afterCursor: 3 });
    expect(page.resync_required).toBe(false);
    expect(page.next_cursor).toBe(4);
    expect(page.events).toHaveLength(1);
    expect(page.events[0].type).toBe("command.leased");
    expect(page.events[0].command_id).toBe("cmd-1");
  });
});

describe("pollCommandUntilTerminal", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("advances through lifecycle events until delivered", async () => {
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/follow")) {
          calls += 1;
          if (calls === 1) {
            return new Response(
              JSON.stringify({
                events: [
                  {
                    event_id: 1,
                    type: "command.queued",
                    command_id: "cmd-aa",
                    state: "queued",
                  },
                ],
                after_cursor: 0,
                next_cursor: 1,
                resync_required: false,
              }),
              { status: 200, headers: { "content-type": "application/json" } },
            );
          }
          return new Response(
            JSON.stringify({
              events: [
                {
                  event_id: 2,
                  type: "command.delivered",
                  command_id: "cmd-aa",
                  state: "delivered",
                  hermes_run_id: "run_abc",
                  hermes_session_id: "agent:main:l2a",
                },
              ],
              after_cursor: 1,
              next_cursor: 2,
              resync_required: false,
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }
        throw new Error(`unexpected ${url}`);
      }),
    );

    const result = await pollCommandUntilTerminal({
      commandId: "cmd-aa",
      afterCursor: 0,
      maxAttempts: 5,
      intervalMs: 1,
    });
    expect(result.state).toBe("delivered");
    expect(result.hermesRunId).toBe("run_abc");
    expect(result.hermesSessionId).toBe("agent:main:l2a");
    expect(result.cursor).toBe(2);
    expect(result.events.length).toBeGreaterThanOrEqual(2);
    expect(result.resyncRequired).toBe(false);
  });

  it("resnapshots on resync_required then exits when terminal in snapshot", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/follow")) {
          return new Response(
            JSON.stringify({
              events: [],
              after_cursor: 99,
              next_cursor: null,
              resync_required: true,
              recovery_action: "resnapshot_workspace",
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }
        if (url.includes("/snapshot")) {
          return new Response(
            JSON.stringify({
              snapshot_workspace_cursor: 5,
              commands: [
                {
                  command_id: "cmd-bb",
                  kind: "conversation_turn",
                  state: "delivered",
                  version: 2,
                  hermes_run_id: "run_bb",
                  hermes_session_id: "agent:main:bb",
                },
              ],
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }
        throw new Error(`unexpected ${url}`);
      }),
    );

    const result = await pollCommandUntilTerminal({
      commandId: "cmd-bb",
      afterCursor: 99,
      maxAttempts: 3,
      intervalMs: 1,
    });
    expect(result.state).toBe("delivered");
    expect(result.hermesRunId).toBe("run_bb");
    expect(result.hermesSessionId).toBe("agent:main:bb");
    expect(result.resyncRequired).toBe(true);
  });

  it("stops early when abort signal fires", async () => {
    const controller = new AbortController();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        controller.abort();
        return new Response(
          JSON.stringify({
            events: [
              {
                event_id: 1,
                type: "command.queued",
                command_id: "cmd-cc",
                state: "queued",
              },
            ],
            after_cursor: 0,
            next_cursor: 1,
            resync_required: false,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }),
    );

    const result = await pollCommandUntilTerminal({
      commandId: "cmd-cc",
      afterCursor: 0,
      maxAttempts: 10,
      intervalMs: 1,
      signal: controller.signal,
    });
    // Aborted before terminal; last observed may be queued or null.
    expect(result.state === null || result.state === "queued").toBe(true);
    expect(isTerminalCommandState(result.state)).toBe(false);
  });
});

describe("assistant observe helpers (L2b-M2)", () => {
  it("picks the latest non-empty assistant message", () => {
    expect(
      latestAssistantText({
        messages: [
          { id: "1", role: "user", content: "hi" },
          { id: "2", role: "assistant", content: "first" },
          { id: "3", role: "assistant", content: "  " },
          { id: "4", role: "assistant", content: " L2a-pong " },
        ],
      }),
    ).toBe("L2a-pong");
    expect(latestAssistantText({ messages: [] })).toBeNull();
    expect(
      latestAssistantText({
        messages: [{ id: "1", role: "user", content: "only user" }],
      }),
    ).toBeNull();
  });

  it("previews assistant text with whitespace collapse and ellipsis", () => {
    expect(previewAssistantText("  hello\nworld  ")).toBe("hello world");
    expect(previewAssistantText("abcdefghij", 5)).toBe("abcd…");
    expect(previewAssistantText("short", 160)).toBe("short");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("fetchHermesSessionMessages uses same-origin path with encoded id", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      expect(url).toBe("/api/hermes/sessions/agent%3Amain%3Al2a/messages");
      return new Response(
        JSON.stringify({
          read_status: "available",
          session_id: "agent:main:l2a",
          messages: [
            { id: "1", role: "user", content: "ping" },
            { id: "2", role: "assistant", content: "L2a-pong" },
          ],
          omitted_message_count: 0,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const envelope = await fetchHermesSessionMessages("agent:main:l2a");
    expect(envelope.read_status).toBe("available");
    expect(latestAssistantText(envelope)).toBe("L2a-pong");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/hermes/sessions/agent%3Amain%3Al2a/messages",
      expect.objectContaining({
        method: "GET",
        credentials: "same-origin",
      }),
    );
  });

  it("fetchLatestAssistantText returns null on unavailable without throwing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            read_status: "unavailable",
            session_id: "agent:x",
            messages: [],
            warnings: [{ code: "gateway_client_unavailable" }],
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      ),
    );
    await expect(
      fetchLatestAssistantText({ hermesSessionId: "agent:x" }),
    ).resolves.toBeNull();
  });

  it("fetchLatestAssistantText returns null on network error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("network down");
      }),
    );
    await expect(
      fetchLatestAssistantText({ hermesSessionId: "agent:x" }),
    ).resolves.toBeNull();
  });
});
