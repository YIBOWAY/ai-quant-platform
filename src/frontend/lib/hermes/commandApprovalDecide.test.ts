/**
 * V7a-Hermes-Approval-Decide-M1 FE contracts.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildDecideApprovalAction,
  decideHermesCommandApproval,
  PLATFORM_WORKSPACE_ID,
  WorkspaceClientError,
} from "@/lib/hermes/workspaceClient";

const DIGEST = "a".repeat(64);

describe("buildDecideApprovalAction", () => {
  it("builds exact hermes.command_approval.decide document", () => {
    const action = buildDecideApprovalAction({
      approvalId: "challenge.1",
      runId: "hermes.1",
      commandDigest: DIGEST,
      expectedExpiresAt: "2026-07-22T12:00:00.000000Z",
      decision: "allow_once",
      clientActionId: "act-decide-1",
      workspaceId: "ws-local-main",
    });
    expect(action).toEqual({
      schema_version: 1,
      kind: "hermes.command_approval.decide",
      client_action_id: "act-decide-1",
      workspace: { workspace_id: "ws-local-main" },
      approval_ref: "approval:challenge.1",
      run_ref: "run:hermes.1",
      command_digest: DIGEST,
      expected_status: "pending",
      expected_expires_at: "2026-07-22T12:00:00.000000Z",
      decision: "allow_once",
    });
  });

  it("strips existing approval:/run: prefixes", () => {
    const action = buildDecideApprovalAction({
      approvalId: "approval:challenge.2",
      runId: "run:hermes.2",
      commandDigest: DIGEST,
      expectedExpiresAt: "2026-07-22T12:00:00Z",
      decision: "deny",
      clientActionId: "act-2",
      workspaceId: "ws",
    });
    expect(action.approval_ref).toBe("approval:challenge.2");
    expect(action.run_ref).toBe("run:hermes.2");
    expect(action.decision).toBe("deny");
  });

  it("rejects non-hex digest and illegal decision", () => {
    expect(() =>
      buildDecideApprovalAction({
        approvalId: "c1",
        runId: "r1",
        commandDigest: "ZZ",
        expectedExpiresAt: "2026-07-22T12:00:00Z",
        decision: "allow_once",
        clientActionId: "a",
        workspaceId: "ws",
      }),
    ).toThrow(WorkspaceClientError);
    expect(() =>
      buildDecideApprovalAction({
        approvalId: "c1",
        runId: "r1",
        commandDigest: DIGEST,
        expectedExpiresAt: "2026-07-22T12:00:00Z",
        // @ts-expect-error intentional
        decision: "always",
        clientActionId: "a",
        workspaceId: "ws",
      }),
    ).toThrow(WorkspaceClientError);
  });
});

describe("decideHermesCommandApproval network", () => {
  const originalFetch = globalThis.fetch;
  let csrfCookie = "qs_aw_csrf=csrf-v7a-token";

  beforeEach(() => {
    csrfCookie = "qs_aw_csrf=csrf-v7a-token";
    vi.stubGlobal("document", {
      get cookie() {
        return csrfCookie;
      },
      set cookie(value: string) {
        csrfCookie = value;
      },
    });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.unstubAllGlobals();
  });

  it("POSTs /act with CSRF and exact action kind", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      calls.push({ url, init });
      if (url.includes("/api/auth/owner/session") && method === "GET") {
        return new Response(
          JSON.stringify({
            session_id: "sess-v7a",
            csrf_token: "csrf-v7a-token",
            mutation_enabled: true,
            security_ready: true,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }
      if (url.includes("/act")) {
        return new Response(
          JSON.stringify({
            status: "accepted",
            client_action_id: "act-decide-net",
            action_digest: "b".repeat(64),
            mutation_enabled: true,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }
      throw new Error(`unexpected fetch ${method} ${url}`);
    }) as typeof fetch;

    const receipt = await decideHermesCommandApproval({
      approvalId: "challenge.9",
      runId: "run.9",
      commandDigest: DIGEST,
      expectedExpiresAt: "2026-12-01T00:00:00.000000Z",
      decision: "deny",
      clientActionId: "act-decide-net",
      workspaceId: PLATFORM_WORKSPACE_ID,
    });
    expect(receipt.status).toBe("accepted");
    const actCall = calls.find((c) => c.url.includes("/act"));
    expect(actCall).toBeTruthy();
    expect(actCall!.init?.method).toBe("POST");
    const headers = new Headers(actCall!.init?.headers as HeadersInit);
    expect(headers.get("X-CSRF-Token") || headers.get("X-QS-AW-CSRF")).toBeTruthy();
    const body = JSON.parse(String(actCall!.init?.body));
    expect(body.action.kind).toBe("hermes.command_approval.decide");
    expect(body.action.decision).toBe("deny");
    expect(body.action.expected_status).toBe("pending");
    expect(body.action.command_digest).toBe(DIGEST);
    expect(body.action.approval_ref).toBe("approval:challenge.9");
    expect(body.action.run_ref).toBe("run:run.9");
  });
});

describe("V7a panel source contracts", () => {
  it("panel marks v7a decide and only allow_once|deny", () => {
    const src = readFileSync(
      path.join(
        process.cwd(),
        "components/hermes/approvals/WorkbenchCommandApprovalsPanel.tsx",
      ),
      "utf8",
    );
    expect(src).toContain('data-hermes-approval-decide="v7a-m1"');
    expect(src).toContain("data-hermes-approval-allow-once");
    expect(src).toContain("data-hermes-approval-deny");
    expect(src).toContain("decideHermesCommandApproval");
    expect(src).toContain('"allow_once"');
    expect(src).toContain('"deny"');
    // Ban real always-allow decision wiring (not the "no always-allow" copy).
    expect(src).not.toMatch(/decision:\s*["']always/i);
    expect(src).not.toMatch(/["']allow_permanently["']/i);
    expect(src).not.toMatch(/["']allow_always["']/i);
    expect(src).not.toMatch(/gate1|gate2|gate3|CandidateApproval/i);
  });
});

describe("V7d filterApprovalsForPanel (consumedIds vs decided)", () => {
  it("hides consumed id only while still pending; keeps decided with decision", async () => {
    const { filterApprovalsForPanel } = await import(
      "@/components/hermes/approvals/WorkbenchCommandApprovalsPanel"
    );
    const pending = {
      approval_id: "a1",
      run_id: "run.1",
      digest: "a".repeat(64),
      expires_at: "2099-01-01T00:00:00.000000Z",
      status: "pending",
      kind: "hermes.command_approval",
    };
    const decided = {
      ...pending,
      status: "denied",
      decision: "deny" as const,
      decided_at: "2026-07-22T00:00:00.000000Z",
    };
    const consumed = { a1: true as const };

    // Still pending + consumed → hidden (optimistic).
    expect(filterApprovalsForPanel([pending], consumed)).toEqual([]);

    // Spine projects decided fact → visible, decision present, not decidable.
    const shown = filterApprovalsForPanel([decided], consumed);
    expect(shown).toHaveLength(1);
    expect(shown[0].status).toBe("denied");
    expect(shown[0].decision).toBe("deny");

    // Unconsumed pending still visible.
    expect(filterApprovalsForPanel([pending], {})).toHaveLength(1);
  });
});
