import { createHash } from "node:crypto";

import { expect, test, type Page } from "@playwright/test";

import {
  assertNoHorizontalOverflow,
  installLoopbackOnlyGuard,
} from "./helpers/hermes-page-gates";

const ACTIVE_SESSION_ID = `web_${"1".repeat(40)}`;
const ACTIVE_PLATFORM_SESSION_ID = `wm_${"1".repeat(32)}`;
const INITIAL_RUN_ID = "fixture-run-active-001";
const APPROVAL_ID = "fixture-approval-active-001";
const INITIAL_COMMAND_ID = "fixture-command-active-001";

const modeMatches =
  process.env.PW_E2E === "1" &&
  process.env.PW_HERMES_LIFECYCLE_FIXTURE === "1" &&
  process.env.PW_HERMES_WORKBENCH_FIXTURE === undefined;

type BrowserProblems = {
  console: string[];
  pageErrors: string[];
  http: string[];
};

function collectBrowserProblems(page: Page): BrowserProblems {
  const problems: BrowserProblems = {
    console: [],
    pageErrors: [],
    http: [],
  };
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      problems.console.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => {
    problems.pageErrors.push(error.message);
  });
  page.on("response", (response) => {
    if (response.status() >= 400) {
      problems.http.push(`${response.status()} ${response.request().method()} ${response.url()}`);
    }
  });
  return problems;
}

function expectCleanBrowser(
  externalRequests: string[],
  problems: BrowserProblems,
) {
  expect(externalRequests).toEqual([]);
  expect(problems.console).toEqual([]);
  expect(problems.pageErrors).toEqual([]);
  expect(problems.http).toEqual([]);
}

async function fixtureAudit(page: Page) {
  return page.evaluate(async () => {
    const response = await fetch("/api/hermes/fixture-audit", {
      credentials: "same-origin",
      headers: { accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(`fixture audit failed: ${response.status}`);
    }
    return (await response.json()) as {
      events: Array<Record<string, unknown>>;
      sse_client_count: number;
      sse_connection_sequence: number;
      sse_connections: Array<{
        after_cursor: number;
        connection_sequence: number;
      }>;
      workspace_cursor: number;
    };
  });
}

async function fixtureSnapshot(page: Page) {
  const response = await page.request.get(
    "/api/workspace/ws-local-main/snapshot",
  );
  expect(response.ok()).toBe(true);
  return (await response.json()) as {
    approvals: Array<Record<string, unknown>>;
    attempts: string[];
    commands: Array<Record<string, unknown>>;
    gates: Array<Record<string, unknown>>;
    results: Array<Record<string, unknown>>;
    runs: string[];
    tasks: string[];
  };
}

function actionFromRequest(request: {
  postDataJSON(): unknown;
}): Record<string, unknown> {
  const payload = request.postDataJSON() as {
    action?: Record<string, unknown>;
  };
  expect(payload.action).toBeTruthy();
  return payload.action!;
}

function sha256(value: string) {
  return createHash("sha256").update(value).digest("hex");
}

function expectExactAuthorities(
  snapshot: Awaited<ReturnType<typeof fixtureSnapshot>>,
  expected: {
    approvalStatus: string;
    initialCommandState: string;
  },
) {
  expect(snapshot.tasks).toEqual(["task:fixture-research"]);
  expect(snapshot.attempts).toEqual(["attempt:fixture-attempt-1"]);
  expect(snapshot.runs).toEqual([`run:${INITIAL_RUN_ID}`]);
  expect(
    snapshot.commands.map((row) => ({
      command_id: row.command_id,
      hermes_run_id: row.hermes_run_id,
      state: row.state,
    })),
  ).toEqual([
    {
      command_id: "fixture-command-turn-002",
      hermes_run_id: "fixture-run-turn-002",
      state: "succeeded",
    },
    {
      command_id: "fixture-command-turn-001",
      hermes_run_id: "fixture-run-turn-001",
      state: "succeeded",
    },
    {
      command_id: INITIAL_COMMAND_ID,
      hermes_run_id: INITIAL_RUN_ID,
      state: expected.initialCommandState,
    },
  ]);
  expect(
    snapshot.approvals.map((row) => ({
      approval_id: row.approval_id,
      status: row.status,
    })),
  ).toEqual([
    {
      approval_id: APPROVAL_ID,
      status: expected.approvalStatus,
    },
  ]);
  expect(
    snapshot.gates.map((row) => ({
      gate_id: row.gate_id,
      gate_kind: row.gate_kind,
      status: row.status,
    })),
  ).toEqual([
    {
      gate_id: "fixture-gate-1",
      gate_kind: "gate1",
      status: "confirmed",
    },
    {
      gate_id: "fixture-gate-2",
      gate_kind: "gate2",
      status: "pending",
    },
    {
      gate_id: "fixture-gate-3",
      gate_kind: "gate3",
      status: "prepared",
    },
  ]);
  expect(
    snapshot.results.map((row) => ({
      result_id: row.result_id,
      run_id: row.run_id,
      status: row.status,
    })),
  ).toEqual([
    {
      result_id: "fixture-result-terminal-001",
      run_id: INITIAL_RUN_ID,
      status: "completed",
    },
  ]);
}

if (modeMatches) {
  test.describe("@lifecycle-fixture Hermes active lifecycle", () => {
  test.describe.configure({ mode: "serial" });

  test("renders an explicit transcript loading state before messages resolve", async ({
    page,
  }) => {
    const externalRequests = await installLoopbackOnlyGuard(page);
    const problems = collectBrowserProblems(page);
    let releaseMessages = () => {};
    const messageGate = new Promise<void>((resolve) => {
      releaseMessages = resolve;
    });
    await page.route(
      `**/api/hermes/sessions/${ACTIVE_SESSION_ID}/messages`,
      async (route) => {
        await messageGate;
        await route.continue();
      },
    );

    await page.goto(
      `/en/hermes?hermes_session_id=${encodeURIComponent(ACTIVE_SESSION_ID)}`,
      { waitUntil: "domcontentloaded" },
    );
    await expect(page.locator("[data-hermes-active-grid]")).toBeVisible();
    await expect(
      page.locator("[data-hermes-transcript-loading]"),
    ).toContainText("Fetching session messages");

    releaseMessages();
    await expect(page.locator("[data-hermes-transcript-scroll]")).toBeVisible();
    await expect(
      page.locator("[data-hermes-transcript-loading]"),
    ).toHaveCount(0);
    expectCleanBrowser(externalRequests, problems);
  });

  test("submits multiple turns and reconnects to the exact managed session", async ({
    page,
  }) => {
    const externalRequests = await installLoopbackOnlyGuard(page);
    const problems = collectBrowserProblems(page);
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(
      `/en/hermes?hermes_session_id=${encodeURIComponent(ACTIVE_SESSION_ID)}`,
      { waitUntil: "domcontentloaded" },
    );

    await expect(page.locator("[data-hermes-active-grid]")).toBeVisible();
    await expect(page.locator("[data-hermes-transcript-scroll]")).toBeVisible();
    await expect(page.getByText("Fixture answer 28:")).toBeVisible();
    const composer = page.getByRole("textbox", { name: "Talk with Hermes" });
    const send = page.getByRole("button", { name: "Send", exact: true });
    await expect(composer).toBeEnabled();
    await expect(send).toBeEnabled();
    const baselineAudit = await fixtureAudit(page);
    const baselineEventCount = baselineAudit.events.length;

    const firstPrompt = "First deterministic lifecycle turn";
    await composer.fill(firstPrompt);
    const firstRequestPromise = page.waitForRequest(
      (request) =>
        request.method() === "POST" &&
        request.url().endsWith("/api/agent/workspace/submit-turn"),
    );
    await send.click();
    const firstRequest = await firstRequestPromise;
    const firstBody = firstRequest.postDataJSON() as {
      client_action_id: string;
      managed_session_ref: string;
      prompt: string;
    };
    expect(firstBody).toMatchObject({
      managed_session_ref: `session:${ACTIVE_PLATFORM_SESSION_ID}`,
      prompt: firstPrompt,
    });
    expect(firstBody.client_action_id).toMatch(/^[0-9a-f-]{36}$/);
    await expect(page.getByText(firstPrompt, { exact: true })).toBeVisible();
    await expect(
      page.getByText(`Fixture reply 1: ${firstPrompt}`, { exact: true }),
    ).toBeVisible();

    const secondPrompt = "Second deterministic lifecycle turn";
    await composer.fill(secondPrompt);
    const secondRequestPromise = page.waitForRequest(
      (request) =>
        request.method() === "POST" &&
        request.url().endsWith("/api/agent/workspace/submit-turn"),
    );
    await send.click();
    const secondRequest = await secondRequestPromise;
    const secondBody = secondRequest.postDataJSON() as {
      client_action_id: string;
      managed_session_ref: string;
      prompt: string;
    };
    expect(secondBody).toMatchObject({
      managed_session_ref: `session:${ACTIVE_PLATFORM_SESSION_ID}`,
      prompt: secondPrompt,
    });
    expect(secondBody.client_action_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(secondBody.client_action_id).not.toBe(firstBody.client_action_id);
    await expect(page.getByText(secondPrompt, { exact: true })).toBeVisible();
    await expect(
      page.getByText(`Fixture reply 2: ${secondPrompt}`, { exact: true }),
    ).toBeVisible();

    const expectedTurnEvents = [
      {
        sequence: baselineEventCount + 1,
        kind: "conversation.turn",
        client_action_id: firstBody.client_action_id,
        command_id: "fixture-command-turn-001",
        managed_session_ref: `session:${ACTIVE_PLATFORM_SESSION_ID}`,
        prompt_sha256: sha256(firstPrompt),
      },
      {
        sequence: baselineEventCount + 2,
        kind: "conversation.turn",
        client_action_id: secondBody.client_action_id,
        command_id: "fixture-command-turn-002",
        managed_session_ref: `session:${ACTIVE_PLATFORM_SESSION_ID}`,
        prompt_sha256: sha256(secondPrompt),
      },
    ];
    await expect
      .poll(async () => {
        const audit = await fixtureAudit(page);
        return audit.events.slice(baselineEventCount);
      })
      .toEqual(expectedTurnEvents);
    await expect
      .poll(async () => {
        const audit = await fixtureAudit(page);
        const connectedAtAuthoritativeCursor = audit.sse_connections.some(
          (connection) => connection.after_cursor === audit.workspace_cursor,
        );
        return connectedAtAuthoritativeCursor ? audit : null;
      })
      .not.toBeNull();
    const reconnectBaseline = await fixtureAudit(page);
    expect(
      reconnectBaseline.sse_connections.some(
        (connection) =>
          connection.after_cursor === reconnectBaseline.workspace_cursor,
      ),
    ).toBe(true);

    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.locator("[data-hermes-active-grid]")).toBeVisible();
    await expect(page.getByText(firstPrompt, { exact: true })).toBeVisible();
    await expect(page.getByText(secondPrompt, { exact: true })).toBeVisible();
    await expect(page).toHaveURL(
      new RegExp(
        `/en/hermes\\?hermes_session_id=${ACTIVE_SESSION_ID.replace(
          /[.*+?^${}()|[\]\\]/g,
          "\\$&",
        )}$`,
      ),
    );
    await assertNoHorizontalOverflow(page, 1280);

    await expect
      .poll(async () => {
        const audit = await fixtureAudit(page);
        return audit.sse_connections.some(
          (connection) =>
            connection.connection_sequence >
              reconnectBaseline.sse_connection_sequence &&
            connection.after_cursor === reconnectBaseline.workspace_cursor,
        );
      })
      .toBe(true);
    const audit = await fixtureAudit(page);
    expect(audit.events.slice(baselineEventCount)).toEqual(expectedTurnEvents);
    expect(audit.events.slice(baselineEventCount)).not.toContainEqual(
      expect.objectContaining({ prompt: expect.anything() }),
    );
    expectCleanBrowser(externalRequests, problems);
  });

  test("forks one exact historical cursor and preserves immutable lineage", async ({
    page,
  }) => {
    const externalRequests = await installLoopbackOnlyGuard(page);
    const problems = collectBrowserProblems(page);
    const auditBaselineResponse = await page.request.get(
      "/api/hermes/fixture-audit",
    );
    expect(auditBaselineResponse.ok()).toBe(true);
    const auditBaseline = (await auditBaselineResponse.json()) as {
      events: Array<Record<string, unknown>>;
    };
    const baselineEventCount = auditBaseline.events.length;
    await page.goto("/en/hermes/sessions/fixture-long-session", {
      waitUntil: "domcontentloaded",
    });

    // Wait for the owner-ready client boundary before selecting; otherwise
    // its one-time shell transition can remount the server-rendered controller.
    await expect(page.locator("[data-hermes-active-grid]")).toBeVisible();
    await expect(
      page.getByRole("textbox", { name: "Talk with Hermes" }),
    ).toBeDisabled();
    await expect(
      page.getByRole("button", { name: "Send", exact: true }),
    ).toBeDisabled();
    const auditBeforeExplicitFork = await fixtureAudit(page);
    expect(
      auditBeforeExplicitFork.events.slice(baselineEventCount),
    ).toEqual([]);

    const exactFork = page.locator(
      '[data-hermes-message-fork-select][data-hermes-fork-point="message:42"]',
    );
    await expect(exactFork).toBeVisible();
    await exactFork.click();
    await page
      .locator("[data-hermes-session-fork-policy-confirmation] input")
      .check();
    const forkRequestPromise = page.waitForRequest(
      (request) =>
        request.method() === "POST" &&
        request.url().endsWith(
          "/api/hermes/sessions/fixture-long-session/forks-to-managed",
        ),
    );
    await page.locator("[data-hermes-session-fork-confirm-action]").click();
    const forkRequest = await forkRequestPromise;
    const forkBody = forkRequest.postDataJSON() as {
      client_action_id: string;
      fork_point: string;
      new_provider_policy_digest: string;
    };
    expect(forkBody).toMatchObject({ fork_point: "message:42" });
    expect(forkBody.client_action_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(forkBody.new_provider_policy_digest).toMatch(/^[0-9a-f]{64}$/);

    await expect(page).toHaveURL(
      /\/en\/hermes\?hermes_session_id=web_[0-9a-f]{40}$/,
    );
    await expect(
      page.getByText("Historical read-only answer", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Continue from this exact historical message", {
        exact: true,
      }),
    ).toHaveCount(0);

    const audit = await fixtureAudit(page);
    const postBaselineEvents = audit.events.slice(baselineEventCount);
    const forkedSessionId = new URL(page.url()).searchParams.get(
      "hermes_session_id",
    );
    expect(forkedSessionId).toMatch(/^web_[0-9a-f]{40}$/);
    expect(postBaselineEvents).toEqual([
      {
        sequence: baselineEventCount + 1,
        kind: "managed_session.fork",
        client_action_id: forkBody.client_action_id,
        fork_point: "message:42",
        hermes_session_id: forkedSessionId,
        new_provider_policy_digest: forkBody.new_provider_policy_digest,
        source_session_id: "fixture-long-session",
      },
    ]);
    expectCleanBrowser(externalRequests, problems);
  });

  test("keeps stop, command approval, Gates, and typed results separate", async ({
    page,
  }) => {
    const externalRequests = await installLoopbackOnlyGuard(page);
    const problems = collectBrowserProblems(page);
    await page.goto(
      `/en/hermes?hermes_session_id=${encodeURIComponent(ACTIVE_SESSION_ID)}`,
      { waitUntil: "domcontentloaded" },
    );
    const baselineAudit = await fixtureAudit(page);
    const baselineEventCount = baselineAudit.events.length;
    const beforeAuthorities = await fixtureSnapshot(page);
    expectExactAuthorities(beforeAuthorities, {
      approvalStatus: "pending",
      initialCommandState: "delivered",
    });

    const stopRow = page.locator(
      `[data-hermes-run-stop-row][data-hermes-run-id="${INITIAL_RUN_ID}"]`,
    );
    await expect(stopRow).toBeVisible();
    const stopRequestPromise = page.waitForRequest(
      (request) =>
        request.method() === "POST" &&
        request.url().endsWith("/api/workspace/ws-local-main/act"),
    );
    await stopRow.locator("[data-hermes-run-stop-button]").click();
    const stopAction = actionFromRequest(await stopRequestPromise);
    expect(stopAction).toMatchObject({
      kind: "run.stop.request",
      run_ref: `run:${INITIAL_RUN_ID}`,
    });
    expect(stopAction.client_action_id).toMatch(/^[0-9a-f-]{36}$/);
    await expect(
      page.locator('[data-hermes-run-stop-status="success"]'),
    ).toBeVisible();
    await expect(stopRow).toHaveCount(0);

    const approval = page.locator(
      `[data-hermes-approval-row][data-hermes-approval-id="${APPROVAL_ID}"]`,
    );
    await expect(approval).toHaveAttribute(
      "data-hermes-approval-decidable",
      "true",
    );
    const approvalRequestPromise = page.waitForRequest(
      (request) =>
        request.method() === "POST" &&
        request.url().endsWith("/api/workspace/ws-local-main/act"),
    );
    await approval.locator("[data-hermes-approval-deny]").click();
    const approvalAction = actionFromRequest(await approvalRequestPromise);
    expect(approvalAction).toMatchObject({
      approval_ref: `approval:${APPROVAL_ID}`,
      decision: "deny",
      kind: "hermes.command_approval.decide",
      run_ref: `run:${INITIAL_RUN_ID}`,
    });
    expect(approvalAction.client_action_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(approvalAction.client_action_id).not.toBe(
      stopAction.client_action_id,
    );
    await expect(page.locator("[data-hermes-approvals-receipt]")).toContainText(
      "deny:accepted:",
    );
    await expect(
      approval.locator("[data-hermes-approval-status]"),
    ).toContainText("denied");
    await expect(
      approval.locator(
        "[data-hermes-approval-allow-once], [data-hermes-approval-deny]",
      ),
    ).toHaveCount(0);

    await expect(
      page.locator(
        '[data-hermes-gate-row][data-hermes-gate-kind="gate1"][data-hermes-gate-status="confirmed"]',
      ),
    ).toHaveCount(1);
    await expect(
      page.locator(
        '[data-hermes-gate-row][data-hermes-gate-kind="gate2"][data-hermes-gate-status="pending"]',
      ),
    ).toHaveCount(1);
    await expect(
      page.locator(
        '[data-hermes-gate-row][data-hermes-gate-kind="gate3"][data-hermes-gate-status="prepared"]',
      ),
    ).toHaveCount(1);
    await expect(
      page.locator(
        '[data-hermes-typed-result-row][data-hermes-result-kind="backtest"][data-hermes-result-sample="sample"]',
      ),
    ).toContainText("completed");
    await expect(
      page.locator("[data-hermes-typed-result-row] [data-hermes-result-exact-links]"),
    ).toContainText("run: run:fixture-run-active-001");

    const audit = await fixtureAudit(page);
    expect(audit.events.slice(baselineEventCount)).toEqual([
      {
        sequence: baselineEventCount + 1,
        kind: "run.stop.request",
        client_action_id: stopAction.client_action_id,
        approval_ref: null,
        decision: null,
        run_ref: `run:${INITIAL_RUN_ID}`,
      },
      {
        sequence: baselineEventCount + 2,
        kind: "hermes.command_approval.decide",
        client_action_id: approvalAction.client_action_id,
        approval_ref: `approval:${APPROVAL_ID}`,
        decision: "deny",
        run_ref: `run:${INITIAL_RUN_ID}`,
      },
    ]);
    const afterAuthorities = await fixtureSnapshot(page);
    expectExactAuthorities(afterAuthorities, {
      approvalStatus: "denied",
      initialCommandState: "cancelled",
    });
    expect(afterAuthorities.gates).toEqual(beforeAuthorities.gates);
    expect(afterAuthorities.results).toEqual(beforeAuthorities.results);
    expect(afterAuthorities.tasks).toEqual(beforeAuthorities.tasks);
    expect(afterAuthorities.attempts).toEqual(beforeAuthorities.attempts);
    expect(afterAuthorities.runs).toEqual(beforeAuthorities.runs);
    expectCleanBrowser(externalRequests, problems);
  });

  test("does not hijack a reader's scroll position when a transcript hint refetches", async ({
    page,
  }) => {
    const externalRequests = await installLoopbackOnlyGuard(page);
    const problems = collectBrowserProblems(page);
    const baselineResponse = await page.request.get(
      "/api/hermes/fixture-audit",
    );
    expect(baselineResponse.ok()).toBe(true);
    const baseline = (await baselineResponse.json()) as {
      events: Array<Record<string, unknown>>;
      sse_connection_sequence: number;
      workspace_cursor: number;
    };
    const baselineEventCount = baseline.events.length;
    await page.goto(
      `/en/hermes?hermes_session_id=${encodeURIComponent(ACTIVE_SESSION_ID)}`,
      { waitUntil: "domcontentloaded" },
    );
    const scroll = page.locator("[data-hermes-transcript-scroll]");
    await expect(scroll).toBeVisible();
    const before = await scroll.evaluate((element) => {
      element.scrollTop = Math.max(1, element.scrollHeight - element.clientHeight - 260);
      return {
        scrollTop: element.scrollTop,
        text: element.textContent ?? "",
      };
    });
    expect(before.scrollTop).toBeGreaterThan(0);
    expect(before.text).not.toContain("Later streamed fixture update");
    await expect
      .poll(async () => {
        const audit = await fixtureAudit(page);
        return audit.sse_connections.some(
          (connection) =>
            connection.connection_sequence >
              baseline.sse_connection_sequence &&
            connection.after_cursor === audit.workspace_cursor,
        );
      })
      .toBe(true);

    await page.evaluate(async () => {
      const token = document.cookie
        .split(";")
        .map((part) => part.trim())
        .find((part) => part.startsWith("qs_aw_csrf="))
        ?.slice("qs_aw_csrf=".length);
      if (!token) throw new Error("fixture CSRF cookie missing");
      const response = await fetch("/api/hermes/fixture-append-assistant", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          accept: "application/json",
          "content-type": "application/json",
          "x-csrf-token": decodeURIComponent(token),
        },
        body: "{}",
      });
      if (!response.ok) {
        throw new Error(`fixture append failed: ${response.status}`);
      }
    });

    await expect(
      page.getByText(/Later streamed fixture update:/),
    ).toBeVisible();
    const after = await scroll.evaluate((element) => element.scrollTop);
    expect(Math.abs(after - before.scrollTop)).toBeLessThanOrEqual(1);
    const audit = await fixtureAudit(page);
    expect(audit.events.slice(baselineEventCount)).toEqual([
      {
        sequence: baselineEventCount + 1,
        kind: "fixture.transcript.append",
        hermes_session_id: ACTIVE_SESSION_ID,
      },
    ]);
    expect(audit.workspace_cursor).toBe(baseline.workspace_cursor + 1);
    expectCleanBrowser(externalRequests, problems);
  });
  });
}
