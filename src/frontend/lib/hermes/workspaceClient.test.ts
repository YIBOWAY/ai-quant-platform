import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CHAT_PROMPT_MAX_BYTES,
  PLATFORM_WORKSPACE_ID,
  PROVIDER_POLICY_DIGEST,
} from "./darkIdentity";
import {
  WorkspaceClientError,
  ensureManagedSession,
  ensureOwnerSession,
  fetchHermesSessionMessages,
  fetchLatestAssistantText,
  fetchWorkspaceFollow,
  forkHermesSessionToManaged,
  isTerminalCommandState,
  latestManagedSessionProjection,
  latestAssistantText,
  pollCommandUntilTerminal,
  preflightPrompt,
  previewAssistantText,
  readCsrfToken,
  sendComposerTurn,
  submitTurn,
  utf8ByteLength,
  waitForManagedSessionReady,
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
    let managedSessionCreated = false;
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
      prompt: vi.fn(() => "t".repeat(40)),
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
          return new Response(
            JSON.stringify({ detail: { code: "auth", message: "no" } }),
            {
              status: 401,
              headers: { "content-type": "application/json" },
            },
          );
        }
        if (url.endsWith("/api/auth/owner/bootstrap")) {
          expect(JSON.parse(String(init?.body))).toEqual({
            bootstrap_token: "t".repeat(40),
          });
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
          expect(body.action.provider_policy_digest).toBe(
            PROVIDER_POLICY_DIGEST,
          );
          expect(body.action.prompt).toBeUndefined();
          managedSessionCreated = true;
          return new Response(
            JSON.stringify({
              status: "accepted",
              client_action_id: body.action.client_action_id,
              platform_session_id: "wm_managed_1",
              session_ref: "session:wm_managed_1",
              mutation_enabled: true,
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }
        if (url.includes("/api/workspace/") && url.endsWith("/snapshot")) {
          return new Response(
            JSON.stringify({
              workspace: { workspace_id: PLATFORM_WORKSPACE_ID },
              authority_health: { session_registry: "ready" },
              managed_sessions: managedSessionCreated
                ? [
                    {
                      platform_session_id: "wm_managed_1",
                      session_ref: "session:wm_managed_1",
                      hermes_session_id: "web_" + "a".repeat(40),
                      provision_state: "ready",
                      web_writable: true,
                      attempt_count: 1,
                      lease_until: null,
                      retry_at: null,
                      last_error_code: null,
                      provisioned_at: "2026-07-24T12:00:00.000000Z",
                      parent_session_ref: null,
                      fork_point: null,
                      created_at: "2026-07-24T11:59:59.000000Z",
                      updated_at: "2026-07-24T12:00:00.000000Z",
                    },
                  ]
                : [],
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }
        if (url.endsWith("/api/agent/workspace/submit-turn")) {
          const headers = new Headers(init?.headers as HeadersInit);
          expect(headers.get("X-CSRF-Token")).toBe("csrf-live-token");
          const body = JSON.parse(String(init?.body)) as Record<
            string,
            unknown
          >;
          expect(Object.keys(body).sort()).toEqual([
            "client_action_id",
            "managed_session_ref",
            "prompt",
            "workspace_id",
          ]);
          expect(body.workspace_id).toBe(PLATFORM_WORKSPACE_ID);
          expect(body.managed_session_ref).toBe("session:wm_managed_1");
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
    expect(receipt.hermes_session_id).toBe("web_" + "a".repeat(40));
    expect(receipt.payload_ref).toMatch(/^payload:sha256:/);
    expect(receipt).not.toHaveProperty("prompt");

    const paths = calls.map(
      (c) => new URL(c.url, "http://127.0.0.1:3001").pathname,
    );
    expect(paths).toEqual([
      "/api/auth/owner/session",
      "/api/auth/owner/bootstrap",
      `/api/workspace/${PLATFORM_WORKSPACE_ID}/snapshot`,
      `/api/workspace/${PLATFORM_WORKSPACE_ID}/act`,
      `/api/workspace/${PLATFORM_WORKSPACE_ID}/snapshot`,
      "/api/agent/workspace/submit-turn",
    ]);
  });

  it("recovers the latest ready server managed session without duplicate creation", async () => {
    const memory = new Map<string, string>();
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect((init?.method ?? "GET").toUpperCase()).toBe("GET");
      return new Response(
        JSON.stringify({
          authority_health: { session_registry: "ready" },
          managed_sessions: [
            {
              platform_session_id: "wm_older",
              session_ref: "session:wm_older",
              hermes_session_id: "web_" + "1".repeat(40),
              provision_state: "ready",
              web_writable: true,
              attempt_count: 1,
              created_at: "2026-07-24T10:00:00.000000Z",
            },
            {
              platform_session_id: "wm_newest",
              session_ref: "session:wm_newest",
              hermes_session_id: "web_" + "2".repeat(40),
              provision_state: "ready",
              web_writable: true,
              attempt_count: 1,
              created_at: "2026-07-24T11:00:00.000000Z",
            },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    });
    vi.stubGlobal("window", {
      sessionStorage: {
        getItem: (key: string) => memory.get(key) ?? null,
        setItem: (key: string, value: string) => memory.set(key, value),
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    const managed = await ensureManagedSession();

    expect(managed.platform_session_id).toBe("wm_newest");
    expect(managed.hermes_session_id).toBe("web_" + "2".repeat(40));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(
      memory.get("qs.hermes.l2a.managed_session_ref:" + PLATFORM_WORKSPACE_ID),
    ).toBe("session:wm_newest");
  });

  it("fails closed on an inconsistent latest managed projection", () => {
    expect(() =>
      latestManagedSessionProjection({
        managed_sessions: [
          {
            platform_session_id: "wm_latest",
            session_ref: "session:wm_different",
            hermes_session_id: "web_" + "3".repeat(40),
            provision_state: "ready",
            web_writable: true,
            attempt_count: 1,
          },
        ],
      }),
    ).toThrowError(
      expect.objectContaining({
        code: "managed_session_projection_invalid",
        status: 503,
      }),
    );
  });

  it("waits through pending provisioning before the first submit", async () => {
    let snapshots = 0;
    const calls: string[] = [];
    vi.stubGlobal("document", { cookie: "qs_aw_csrf=csrf-wait-token" });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        calls.push(url);
        if (url.endsWith("/api/agent/workspace/submit-turn")) {
          expect(snapshots).toBe(2);
          expect(
            new Headers(init?.headers as HeadersInit).get("X-CSRF-Token"),
          ).toBe("csrf-wait-token");
          return new Response(
            JSON.stringify({
              status: "accepted",
              client_action_id: "turn-after-ready",
              command_id: "cmd-after-ready",
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }
        if (!url.endsWith("/snapshot")) {
          throw new Error(`unexpected ${url}`);
        }
        snapshots += 1;
        const ready = snapshots >= 2;
        return new Response(
          JSON.stringify({
            managed_sessions: [
              {
                platform_session_id: "wm_pending",
                session_ref: "session:wm_pending",
                hermes_session_id: "web_" + "b".repeat(40),
                provision_state: ready ? "ready" : "pending",
                web_writable: ready,
                attempt_count: ready ? 1 : 0,
                lease_until: null,
                retry_at: null,
                last_error_code: null,
                provisioned_at: ready ? "2026-07-24T12:00:00.000000Z" : null,
                parent_session_ref: null,
                fork_point: null,
                created_at: "2026-07-24T11:59:59.000000Z",
                updated_at: "2026-07-24T12:00:00.000000Z",
              },
            ],
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }),
    );

    const receipt = await submitTurn({
      prompt: "first turn waits",
      clientActionId: "turn-after-ready",
      managedSessionRef: "session:wm_pending",
    });

    expect(receipt.status).toBe("accepted");
    expect(receipt.hermes_session_id).toBe("web_" + "b".repeat(40));
    expect(calls.filter((url) => url.endsWith("/snapshot"))).toHaveLength(2);
    expect(calls.at(-1)).toBe("/api/agent/workspace/submit-turn");
  });

  it("does not recreate a stored lineage session when observation is missing", async () => {
    const memory = new Map<string, string>([
      [
        "qs.hermes.l2a.managed_session_ref:" + PLATFORM_WORKSPACE_ID,
        "session:wm_child",
      ],
    ]);
    vi.stubGlobal("window", {
      sessionStorage: {
        getItem: (key: string) => memory.get(key) ?? null,
        setItem: (key: string, value: string) => memory.set(key, value),
      },
    });
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL) =>
        new Response(JSON.stringify({ managed_sessions: [] }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      ensureManagedSession({
        provisionTimeoutMs: 5,
        provisionInitialIntervalMs: 1,
      }),
    ).rejects.toMatchObject({
      code: "managed_session_not_observed",
      status: 503,
    });
    expect(
      memory.get("qs.hermes.l2a.managed_session_ref:" + PLATFORM_WORKSPACE_ID),
    ).toBe("session:wm_child");
    expect(
      fetchMock.mock.calls.every(([url]) => String(url).endsWith("/snapshot")),
    ).toBe(true);
  });

  it("surfaces failed and retryable provisioning without treating it as writable", async () => {
    let state: "failed" | "retryable" = "failed";
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              managed_sessions: [
                {
                  platform_session_id: "wm_bad",
                  session_ref: "session:wm_bad",
                  hermes_session_id: "web_" + "c".repeat(40),
                  provision_state: state,
                  web_writable: false,
                  attempt_count: 3,
                  retry_at:
                    state === "retryable"
                      ? "2026-07-24T12:01:00.000000Z"
                      : null,
                  last_error_code: "gateway_timeout",
                },
              ],
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          ),
      ),
    );

    await expect(
      waitForManagedSessionReady({
        sessionRef: "session:wm_bad",
        timeoutMs: 100,
        initialIntervalMs: 1,
      }),
    ).rejects.toMatchObject({
      code: "managed_session_provision_failed",
    });

    state = "retryable";
    await expect(
      waitForManagedSessionReady({
        sessionRef: "session:wm_bad",
        timeoutMs: 5,
        initialIntervalMs: 1,
      }),
    ).rejects.toMatchObject({
      code: "managed_session_provision_retryable",
    });
  });

  it("honors AbortSignal while waiting for provisioning", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              managed_sessions: [
                {
                  platform_session_id: "wm_abort",
                  session_ref: "session:wm_abort",
                  hermes_session_id: "web_" + "d".repeat(40),
                  provision_state: "pending",
                  web_writable: false,
                  attempt_count: 0,
                },
              ],
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          ),
      ),
    );
    const controller = new AbortController();
    setTimeout(() => controller.abort(), 1);
    await expect(
      waitForManagedSessionReady({
        sessionRef: "session:wm_abort",
        timeoutMs: 1_000,
        initialIntervalMs: 20,
        signal: controller.signal,
      }),
    ).rejects.toMatchObject({ name: "AbortError" });
  });

  it("fails closed on empty prompt before any network", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(sendComposerTurn({ prompt: "  " })).rejects.toThrow(
      /non-empty/,
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not bootstrap or disclose a token when the operator cancels", async () => {
    vi.stubGlobal("window", { prompt: vi.fn(() => null) });
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ detail: { code: "auth", message: "no" } }),
            {
              status: 401,
              headers: { "content-type": "application/json" },
            },
          ),
      ),
    );

    await expect(ensureOwnerSession()).rejects.toMatchObject({
      code: "owner_bootstrap_required",
      status: 401,
    });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

describe("forkHermesSessionToManaged", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("rejects a normalized or invented cursor before owner/network access", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      forkHermesSessionToManaged({
        hermesSessionId: "agent:main:discord",
        clientActionId: "fork-attempt-invalid",
        forkPoint: " message:42",
      }),
    ).rejects.toMatchObject({
      code: "validation",
      status: 400,
    });
    await expect(
      forkHermesSessionToManaged({
        hermesSessionId: "agent:main:discord",
        clientActionId: "fork-attempt-invalid",
        forkPoint: "message:display-id",
      }),
    ).rejects.toMatchObject({
      code: "validation",
      status: 400,
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends only the immutable attempt fields and waits on the receipt session", async () => {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    const memory = new Map<string, string>();
    const childRef = "session:wm_" + "f".repeat(32);
    const childHermesId = "web_" + "a".repeat(40);

    vi.stubGlobal("document", { cookie: "qs_aw_csrf=csrf-fork-token" });
    vi.stubGlobal("window", {
      sessionStorage: {
        getItem: (key: string) => memory.get(key) ?? null,
        setItem: (key: string, value: string) => memory.set(key, value),
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        calls.push({ url, init: init ?? {} });
        const method = (init?.method ?? "GET").toUpperCase();
        if (url === "/api/auth/owner/session" && method === "GET") {
          return new Response(
            JSON.stringify({ session_id: "owner-session", mutation_enabled: true }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }
        if (
          url ===
            "/api/hermes/sessions/agent%3Amain%3Adiscord/forks-to-managed" &&
          method === "POST"
        ) {
          expect(new Headers(init?.headers).get("X-CSRF-Token")).toBe(
            "csrf-fork-token",
          );
          expect(init?.credentials).toBe("same-origin");
          expect(JSON.parse(String(init?.body))).toEqual({
            client_action_id: "fork-attempt-0001",
            fork_point: "message:42",
          });
          return new Response(
            JSON.stringify({
              status: "accepted",
              client_action_id: "fork-attempt-0001",
              action_digest: "d".repeat(64),
              workspace: { workspace_id: PLATFORM_WORKSPACE_ID },
              mutation_enabled: true,
              platform_session_id: childRef.slice("session:".length),
              session_ref: childRef,
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }
        if (
          url === `/api/workspace/${PLATFORM_WORKSPACE_ID}/snapshot` &&
          method === "GET"
        ) {
          return new Response(
            JSON.stringify({
              managed_sessions: [
                {
                  platform_session_id: childRef.slice("session:".length),
                  session_ref: childRef,
                  hermes_session_id: childHermesId,
                  provision_state: "ready",
                  web_writable: true,
                  attempt_count: 1,
                  parent_session_ref: "session:ext_" + "b".repeat(32),
                  fork_point: "message:42",
                },
              ],
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }
        throw new Error(`unexpected fetch ${method} ${url}`);
      }),
    );

    const result = await forkHermesSessionToManaged({
      hermesSessionId: "agent:main:discord",
      clientActionId: "fork-attempt-0001",
      forkPoint: "message:42",
      provisionInitialIntervalMs: 1,
    });

    expect(result.receipt.status).toBe("accepted");
    expect(result.managedSession).toMatchObject({
      session_ref: childRef,
      hermes_session_id: childHermesId,
      fork_point: "message:42",
    });
    expect(
      memory.get(
        "qs.hermes.l2a.managed_session_ref:" + PLATFORM_WORKSPACE_ID,
      ),
    ).toBe(childRef);
    expect(calls.map(({ url }) => url)).toEqual([
      "/api/auth/owner/session",
      "/api/hermes/sessions/agent%3Amain%3Adiscord/forks-to-managed",
      `/api/workspace/${PLATFORM_WORKSPACE_ID}/snapshot`,
    ]);
  });

  it("reconciles by waiting on the same receipt session without creating another lineage", async () => {
    const childRef = "session:wm_" + "9".repeat(32);
    const childHermesId = "web_" + "9".repeat(40);
    let snapshots = 0;
    const onReceipt = vi.fn();

    vi.stubGlobal("document", { cookie: "qs_aw_csrf=csrf-fork-token" });
    vi.stubGlobal("window", {
      sessionStorage: {
        getItem: () => null,
        setItem: vi.fn(),
      },
    });
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = (init?.method ?? "GET").toUpperCase();
        if (url === "/api/auth/owner/session" && method === "GET") {
          return new Response(JSON.stringify({ session_id: "owner-session" }), {
            status: 200,
            headers: { "content-type": "application/json" },
          });
        }
        if (url.endsWith("/forks-to-managed") && method === "POST") {
          return new Response(
            JSON.stringify({
              status: "reconciling",
              client_action_id: "fork-attempt-reconcile",
              action_digest: "e".repeat(64),
              workspace: { workspace_id: PLATFORM_WORKSPACE_ID },
              mutation_enabled: true,
              platform_session_id: childRef.slice("session:".length),
              session_ref: childRef,
              recovery_action: "follow_workspace",
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }
        if (url.endsWith("/snapshot") && method === "GET") {
          snapshots += 1;
          return new Response(
            JSON.stringify({
              managed_sessions: [
                {
                  platform_session_id: childRef.slice("session:".length),
                  session_ref: childRef,
                  hermes_session_id: childHermesId,
                  provision_state: snapshots === 1 ? "pending" : "ready",
                  web_writable: snapshots > 1,
                  attempt_count: snapshots,
                  parent_session_ref: "session:ext_" + "8".repeat(32),
                  fork_point: "message:88",
                },
              ],
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }
        throw new Error(`unexpected fetch ${method} ${url}`);
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await forkHermesSessionToManaged({
      hermesSessionId: "agent:main:discord",
      clientActionId: "fork-attempt-reconcile",
      forkPoint: "message:88",
      provisionInitialIntervalMs: 1,
      onReceipt,
    });

    expect(onReceipt).toHaveBeenCalledWith(
      expect.objectContaining({
        status: "reconciling",
        session_ref: childRef,
      }),
    );
    expect(result.managedSession.session_ref).toBe(childRef);
    expect(snapshots).toBe(2);
    expect(
      fetchMock.mock.calls.filter(([url]) =>
        String(url).endsWith("/forks-to-managed"),
      ),
    ).toHaveLength(1);
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).endsWith("/act")),
    ).toBe(false);
  });
});

describe("isTerminalCommandState", () => {
  it("recognizes terminal lifecycle states only", () => {
    expect(isTerminalCommandState("delivered")).toBe(false);
    expect(isTerminalCommandState("succeeded")).toBe(true);
    expect(isTerminalCommandState("failed")).toBe(true);
    expect(isTerminalCommandState("rejected")).toBe(true);
    expect(isTerminalCommandState("cancelled")).toBe(true);
    expect(isTerminalCommandState("timed_out")).toBe(true);
    expect(isTerminalCommandState("outcome_unknown")).toBe(false);
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

  it("continues beyond delivered until authoritative succeeded", async () => {
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
          if (calls === 2) {
            return new Response(
              JSON.stringify({
                events: [
                  {
                    event_id: 2,
                    type: "command.delivered",
                    command_id: "cmd-aa",
                    state: "delivered",
                    hermes_run_id: "run_abc",
                    hermes_session_id: "web_" + "a".repeat(40),
                  },
                ],
                after_cursor: 1,
                next_cursor: 2,
                resync_required: false,
              }),
              { status: 200, headers: { "content-type": "application/json" } },
            );
          }
          return new Response(
            JSON.stringify({
              events: [
                {
                  event_id: 3,
                  type: "command.succeeded",
                  command_id: "cmd-aa",
                  state: "succeeded",
                  hermes_run_id: "run_abc",
                  hermes_session_id: "web_" + "a".repeat(40),
                },
              ],
              after_cursor: 2,
              next_cursor: 3,
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
    expect(result.state).toBe("succeeded");
    expect(result.hermesRunId).toBe("run_abc");
    expect(result.hermesSessionId).toBe("web_" + "a".repeat(40));
    expect(result.cursor).toBe(3);
    expect(result.events.length).toBeGreaterThanOrEqual(3);
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
                  state: "succeeded",
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
    expect(result.state).toBe("succeeded");
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

  it("fetchHermesSessionMessages accepts Hermes-managed web_* sessions", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe("/api/hermes/sessions/web_abc/messages");
      return new Response(
        JSON.stringify({
          read_status: "available",
          session_id: "web_abc",
          messages: [{ id: "1", role: "assistant", content: "managed" }],
          omitted_message_count: 0,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchHermesSessionMessages("web_abc")).resolves.toMatchObject({
      read_status: "available",
      session_id: "web_abc",
    });
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("fetchHermesSessionMessages rejects wm_/unsafe/empty without network", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(fetchHermesSessionMessages("wm_abc")).rejects.toMatchObject({
      status: 400,
      code: "validation",
    });
    await expect(fetchHermesSessionMessages("../escape")).rejects.toMatchObject(
      {
        status: 400,
        code: "validation",
      },
    );
    await expect(fetchHermesSessionMessages("   ")).rejects.toMatchObject({
      status: 400,
      code: "validation",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fetchLatestAssistantText returns null on unavailable without throwing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
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
