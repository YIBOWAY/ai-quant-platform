import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ensureRunStopAttempt,
  selectStoppableHermesRuns,
  shouldRetainRunStopAttemptAfterError,
} from "./runStopAttempt";
import {
  buildRequestRunStopAction,
  requestHermesRunStop,
  WorkspaceClientError,
  type WorkspaceCommandProjection,
} from "./workspaceClient";

function command(
  state: string,
  overrides: Partial<WorkspaceCommandProjection> = {},
): WorkspaceCommandProjection {
  return {
    command_id: `cmd-${state}`,
    kind: "conversation.turn",
    state,
    version: 1,
    hermes_run_id: `hermes-${state}`,
    updated_at: "2026-07-26T10:00:00.000000Z",
    ...overrides,
  };
}

describe("Web Run stop eligibility", () => {
  it("shows eligibility only for exact delivered/outcome_unknown Hermes runs", () => {
    const rows = [
      command("delivered"),
      command("outcome_unknown"),
      command("queued"),
      command("leased"),
      command("succeeded"),
      command("failed"),
      command("cancelled"),
      command("rejected"),
      command("timed_out"),
      command("delivered", {
        command_id: "cmd-no-run",
        hermes_run_id: null,
      }),
      command("delivered", {
        command_id: "cmd-invalid-run",
        hermes_run_id: "run id with spaces",
      }),
    ];

    expect(
      selectStoppableHermesRuns(rows, true).map((row) => row.runId),
    ).toEqual(["hermes-outcome_unknown", "hermes-delivered"]);
    expect(selectStoppableHermesRuns(rows, false)).toEqual([]);
  });

  it("renders no Stop eligibility for terminal runs", () => {
    for (const terminal of [
      "succeeded",
      "failed",
      "cancelled",
      "rejected",
      "timed_out",
    ]) {
      expect(selectStoppableHermesRuns([command(terminal)], true)).toEqual([]);
    }
  });

  it("lets a newer terminal fact suppress an older active duplicate", () => {
    const runId = "hermes-same-run";
    const active = command("delivered", {
      command_id: "cmd-old",
      hermes_run_id: runId,
      version: 2,
      updated_at: "2026-07-26T10:00:00.000000Z",
    });
    const terminal = command("succeeded", {
      command_id: "cmd-new",
      hermes_run_id: runId,
      version: 3,
      updated_at: "2026-07-26T10:01:00.000000Z",
    });

    expect(selectStoppableHermesRuns([active, terminal], true)).toEqual([]);
  });
});

describe("Web Run stop durable retry identity", () => {
  it("reuses the same client_action_id for unknown-outcome retry", () => {
    const first = ensureRunStopAttempt(
      null,
      "hermes-run-1",
      () => "stop-action-original",
    );
    const retry = ensureRunStopAttempt(
      first,
      "hermes-run-1",
      () => "must-not-be-called",
    );

    expect(retry).toBe(first);
    expect(retry).toEqual({
      runId: "hermes-run-1",
      clientActionId: "stop-action-original",
    });
  });

  it("mints a new identity only for a different exact run", () => {
    const first = ensureRunStopAttempt(null, "hermes-run-1", () => "stop-1");
    const next = ensureRunStopAttempt(first, "hermes-run-2", () => "stop-2");

    expect(next).toEqual({
      runId: "hermes-run-2",
      clientActionId: "stop-2",
    });
  });

  it("retains retry identity for unknown transport/5xx, not definitive rejection", () => {
    expect(shouldRetainRunStopAttemptAfterError(new TypeError("network"))).toBe(
      true,
    );
    expect(shouldRetainRunStopAttemptAfterError({ status: 503 })).toBe(true);
    expect(shouldRetainRunStopAttemptAfterError({ status: 409 })).toBe(false);
    expect(shouldRetainRunStopAttemptAfterError({ status: 422 })).toBe(false);
  });
});

describe("run.stop.request workspace action", () => {
  it("submits exact run_ref with every optional layer explicitly null", () => {
    expect(
      buildRequestRunStopAction({
        runId: "run:hermes.active-1",
        clientActionId: "stop-action-1",
        workspaceId: "ws-local-main",
      }),
    ).toEqual({
      schema_version: 1,
      kind: "run.stop.request",
      client_action_id: "stop-action-1",
      workspace: { workspace_id: "ws-local-main" },
      run_ref: "run:hermes.active-1",
      task_ref: null,
      attempt_ref: null,
      platform_job_ref: null,
    });
  });

  it("rejects an empty or malformed run id before network I/O", () => {
    expect(() =>
      buildRequestRunStopAction({
        runId: "run:",
        clientActionId: "stop-action-1",
        workspaceId: "ws-local-main",
      }),
    ).toThrow(WorkspaceClientError);
    expect(() =>
      buildRequestRunStopAction({
        runId: "bad run",
        clientActionId: "stop-action-1",
        workspaceId: "ws-local-main",
      }),
    ).toThrow(WorkspaceClientError);
  });

  const originalFetch = globalThis.fetch;
  let csrfCookie = "qs_aw_csrf=csrf-run-stop-token";

  beforeEach(() => {
    csrfCookie = "qs_aw_csrf=csrf-run-stop-token";
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

  it("POSTs the exact stop action through owner+CSRF BFF", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        calls.push({ url, init });
        if (url === "/api/auth/owner/session") {
          return new Response(
            JSON.stringify({
              session_id: "owner-stop",
              mutation_enabled: true,
              security_ready: true,
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }
        if (url === "/api/workspace/ws-local-main/act") {
          return new Response(
            JSON.stringify({
              status: "outcome_unknown",
              client_action_id: "stop-action-network",
              run_id: "hermes.active-network",
              reason_code: "transport_error",
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }
        throw new Error(`unexpected fetch ${url}`);
      },
    ) as typeof fetch;

    const receipt = await requestHermesRunStop({
      runId: "hermes.active-network",
      clientActionId: "stop-action-network",
    });

    expect(receipt.status).toBe("outcome_unknown");
    const call = calls.find(
      ({ url }) => url === "/api/workspace/ws-local-main/act",
    );
    expect(call?.init?.method).toBe("POST");
    const headers = new Headers(call?.init?.headers);
    expect(
      headers.get("X-CSRF-Token") || headers.get("X-QS-AW-CSRF"),
    ).toBe("csrf-run-stop-token");
    const body = JSON.parse(String(call?.init?.body));
    expect(body.action).toMatchObject({
      kind: "run.stop.request",
      client_action_id: "stop-action-network",
      run_ref: "run:hermes.active-network",
      task_ref: null,
      attempt_ref: null,
      platform_job_ref: null,
    });
  });

  it("fails closed when a receipt drifts from the immutable stop identity", async () => {
    globalThis.fetch = vi.fn(
      async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/auth/owner/session") {
          return new Response(
            JSON.stringify({
              session_id: "owner-stop",
              mutation_enabled: true,
              security_ready: true,
            }),
            {
              status: 200,
              headers: { "content-type": "application/json" },
            },
          );
        }
        return new Response(
          JSON.stringify({
            status: "accepted",
            client_action_id: "different-action",
            run_id: "hermes.active-network",
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      },
    ) as typeof fetch;

    await expect(
      requestHermesRunStop({
        runId: "hermes.active-network",
        clientActionId: "stop-action-network",
      }),
    ).rejects.toMatchObject({
      code: "stop_receipt_identity_mismatch",
      status: 503,
    });
  });
});

describe("Run stop panel source contracts", () => {
  it("owns the accessible button, honest states, and shared-spine refresh", () => {
    const source = readFileSync(
      path.join(
        process.cwd(),
        "components/hermes/run-control/WorkbenchRunStopPanel.tsx",
      ),
      "utf8",
    );

    expect(source).toContain("selectStoppableHermesRuns");
    expect(source).toContain("data-hermes-run-stop-button");
    expect(source).toContain("aria-label=");
    expect(source).toContain('aria-live="polite"');
    expect(source).toContain("requestHermesRunStop");
    expect(source).toContain("spine.resyncNow()");
    expect(source).toContain("data-hermes-run-stop-status");
    expect(source).not.toMatch(/taskId|attemptId|platformJobId/);
  });
});
