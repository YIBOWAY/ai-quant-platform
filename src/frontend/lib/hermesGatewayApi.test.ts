import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getHermesGatewayStatus,
  getHermesSessionDetail,
  getHermesSessionMessages,
  getHermesSessions,
} from "./api";

describe("Hermes persisted-session API reads", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses only the platform BFF and never sends an Hermes credential", async () => {
    const payloads = [
      {
        read_status: "available",
        connected: true,
        model: "codex-local",
        session_api_available: true,
        chat_write_ready: false,
        features: { session_resources: true },
        blockers: ["run_submission_not_idempotent"],
        warnings: [],
      },
      {
        read_status: "available",
        sessions: [],
        limit: 5,
        offset: 10,
        has_more: false,
        warnings: [],
      },
      { read_status: "available", session: { id: "agent:main:api" }, warnings: [] },
      {
        read_status: "available",
        session_id: "agent:main:api",
        messages: [],
        omitted_message_count: 0,
        warnings: [],
      },
    ];
    const fetchMock = vi.fn().mockImplementation(async () =>
      new Response(JSON.stringify(payloads.shift()), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getHermesGatewayStatus();
    await getHermesSessions(5, 10);
    await getHermesSessionDetail("agent:main:api");
    await getHermesSessionMessages("agent:main:api");

    const calls = fetchMock.mock.calls.map(([url, init]) => ({
      url: new URL(String(url)),
      init: init as RequestInit,
    }));
    expect(calls.map(({ url }) => `${url.pathname}${url.search}`)).toEqual([
      "/api/hermes/gateway",
      "/api/hermes/sessions?limit=5&offset=10",
      "/api/hermes/sessions/agent%3Amain%3Aapi",
      "/api/hermes/sessions/agent%3Amain%3Aapi/messages",
    ]);
    for (const { init } of calls) {
      expect(JSON.stringify(init.headers).toLowerCase()).not.toContain("authorization");
      expect(JSON.stringify(init.headers).toLowerCase()).not.toContain("api_key");
    }
  });

  it("returns an honest unavailable fallback without enabling chat", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));

    const gateway = await getHermesGatewayStatus();
    const sessions = await getHermesSessions();

    expect(gateway).toMatchObject({
      read_status: "unavailable",
      connected: false,
      chat_write_ready: false,
    });
    expect(sessions).toMatchObject({ read_status: "unavailable", sessions: [] });
  });
});
