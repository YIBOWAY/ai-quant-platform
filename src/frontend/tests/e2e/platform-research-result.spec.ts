import { expect, test, type Page } from "@playwright/test";

import {
  collectBrowserErrors,
  expectNoBrowserErrors,
} from "./helpers/console-error-gate";

function evidence(operationId: string, sourceDigest: string) {
  const manifestDigest = "a".repeat(64);
  const href = `/api/assistant/remote/evidence/${operationId}/${manifestDigest}`;
  return {
    value: {
      manifest_digest: manifestDigest,
      href,
      candidate_code_digest: sourceDigest,
      candidate_code: "factor_id = 'verified_factor'",
      candidate_code_href: `${href}#candidate-code`,
      qlib_receipt_digest: "1".repeat(64),
      qlib_receipt_href: `${href}#qlib-receipt`,
      platform_receipt_digest: "2".repeat(64),
      platform_receipt_href: `${href}#platform-receipt`,
      comparison_digest: "3".repeat(64),
      comparison_href: `${href}#comparison`,
      comparison: {
        accepted: true,
        daily_return_correlation: 1,
        terminal_nav_difference_bps: 0,
        max_symbol_weight_difference_bps: 0,
      },
      cost_model: { commission_bps: 1, slippage_bps: 5 },
      dsr: { value: 1.1, passed: true },
      verification_gates: {
        dsr: { value: 1.1, passed: true },
        max_hung_correlation: null,
        cost_sensitivity: { passed: true },
      },
      performance: {
        total_return: 0.12,
        sharpe_annual: 1.4,
        max_drawdown: 0.08,
        turnover_period: 0.2,
        n_periods: 240,
        window_start: "2025-01-02",
        window_end: "2025-12-16",
      },
      failed_phase: null,
      failure_code: null,
    },
    provenance: {
      evidence_manifest_digest: manifestDigest,
      evidence_href: href,
    },
  };
}

test.beforeEach(() => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");
});

async function expectEnglishProductCopy(page: Page) {
  const bodyText = await page.locator("body").innerText();
  const targetLocaleLabel = await page
    .locator('a[aria-label="切换到中文"]')
    .innerText();
  expect(bodyText.replace(targetLocaleLabel, "")).not.toMatch(/\p{Script=Han}/u);
}

test("active-session Platform result survives a transcript read failure without becoming a Hermes message", async ({
  page,
}) => {
  const browserErrors = collectBrowserErrors(page, [
    {
      method: "GET",
      status: 503,
      url: `/api/hermes/sessions/web_${"a".repeat(40)}/messages`,
    },
    {
      failureText: "net::ERR_ABORTED",
      method: "GET",
      url: `/api/hermes/sessions/web_${"a".repeat(40)}/messages`,
    },
    {
      failureText: "net::ERR_ABORTED",
      method: "GET",
      responseStatus: 200,
      rscPathname: `/en/hermes/sessions/web_${"a".repeat(40)}`,
    },
  ]);
  await page.setViewportSize({ width: 390, height: 844 });
  const sessionId = `web_${"a".repeat(40)}`;
  const digest = "b".repeat(64);
  let remoteWrites = 0;
  page.on("request", (request) => {
    if (
      request.url().includes("/api/assistant/remote/") &&
      request.method() !== "GET"
    ) {
      remoteWrites += 1;
    }
  });

  await page.route("**/api/assistant/remote/book", async (route) => {
    expect(route.request().method()).toBe("GET");
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        candidates: [
          {
            candidate_id: "candidate-ready",
            factor_id: "factor_ready",
            objective: "English verified objective",
            source_digest: digest,
            status: "verified",
            sleeve_id: null,
            universe: ["US.AAPL"],
          },
          {
            candidate_id: "candidate-hung",
            factor_id: "factor_hung",
            objective: "English hung objective",
            source_digest: "7".repeat(64),
            status: "hung",
            sleeve_id: "sleeve-hung",
            universe: ["US.SPY"],
          },
          {
            candidate_id: "candidate-fossil",
            objective: "English fossil objective",
            source_digest: null,
            status: "hung",
            sleeve_id: "sleeve-fossil",
            universe: [],
            fossil: true,
            official_observation: false,
          },
        ],
        requests: [
          {
            request_id: "request-cccccccccccc",
            hermes_session_id: "web_other",
            operation_id: "c".repeat(64),
            material_digest: "d".repeat(64),
            job_id: "job-other",
            job_key: "job-key-other",
            outcome: "verified_candidate",
            status: "candidate_ready",
            terminal: true,
            candidate_id: "candidate-other",
            source_digest: digest,
            result_reply: {
              status: "candidate_ready",
              code: "candidate_verified",
              message: "Wrong session result",
              provenance: {
                operation_id: "c".repeat(64),
                material_digest: "d".repeat(64),
                job_id: "job-other",
                job_key: "job-key-other",
                candidate_id: "candidate-other",
                source_digest: digest,
              },
            },
          },
          {
            request_id: "request-eeeeeeeeeeee",
            hermes_session_id: sessionId,
            operation_id: "e".repeat(64),
            material_digest: "f".repeat(64),
            job_id: "job-active",
            job_key: "job-key-active",
            outcome: "verified_candidate",
            status: "candidate_ready",
            terminal: true,
            candidate_id: "candidate-active",
            source_digest: digest,
            evidence: evidence("e".repeat(64), digest).value,
            result_reply: {
              status: "candidate_ready",
              code: "candidate_verified",
              message: "Candidate verified for this conversation.",
              provenance: {
                operation_id: "e".repeat(64),
                material_digest: "f".repeat(64),
                job_id: "job-active",
                job_key: "job-key-active",
                candidate_id: "candidate-active",
                source_digest: digest,
                ...evidence("e".repeat(64), digest).provenance,
              },
            },
          },
        ],
      }),
      status: 200,
    });
  });
  await page.route("**/api/hermes/sessions/**/messages", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ detail: "transcript unavailable" }),
      status: 503,
    });
  });
  await page.route("**/api/hermes/sessions?*", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        read_status: "available",
        sessions: [
          {
            id: sessionId,
            title: "Current research session",
            preview: "Current research session",
            message_count: 2,
          },
        ],
      }),
      status: 200,
    });
  });
  await page.route("**/api/paper/strategy-sleeves/observation-calendar", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        yesterday: {
          date: "2026-08-23",
          status: "absent",
          label_zh: "昨日观察：缺席（未运行）",
          counts_as_observation_day: false,
          is_no_signal: false,
        },
        observation_day_count: 0,
      }),
      status: 200,
    });
  });
  await page.route("**/api/market-data/history?*", async (route) => {
    const url = new URL(route.request().url());
    const ticker = url.searchParams.get("ticker") ?? "SPY";
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        symbol: ticker,
        ticker,
        source: "futu",
        frequency: "1d",
        row_count: 2,
        rows: [
          { timestamp: "2026-08-21T00:00:00+00:00", close: 100 },
          { timestamp: "2026-08-22T00:00:00+00:00", close: 101 },
        ],
        metadata: { provider: "futu" },
      }),
      status: 200,
    });
  });
  await page.route("**/api/paper/strategy-sleeves/hung-effect", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        empty: false,
        observation_day_count: 2,
        hung_count: 1,
        covered_sleeve_count: 1,
        as_of: "2026-08-23",
        requested_as_of: "2026-08-23",
        allocated_cash: 10000,
        net_profit_usd: 25,
        return_method: "net_profit_over_allocated_capital",
        sleeve_equity_status: "available",
        sleeve_equity: 10025,
        sleeve_return_pct: 0.25,
        spy_status: "available",
        spy_return_pct: 0.1,
        turnover: 0.02,
        cost_drag_pct: 0.001,
        price_source: "futu",
      }),
      status: 200,
    });
  });

  // Compile the destination once so Next dev-mode HMR cannot replace the
  // client-navigation RSC request with a fallback document navigation.
  const detailWarmup = await page.request.get(`/en/hermes/sessions/${sessionId}`);
  expect(detailWarmup.status()).toBe(200);

  await page.goto(`/en/hermes?hermes_session_id=${sessionId}`);
  const openChat = page.getByRole("button", { name: "Open chat" });
  const rail = page.locator("#hermes-chat-rail");
  await expect(openChat).toHaveAttribute("aria-expanded", "false");
  await expect(rail).toBeHidden();
  await expect(rail).toHaveAttribute("inert", "");
  await expect(page.getByText("Yesterday's observation: absent (not run)")).toBeVisible();
  await expect(page.getByTestId("duty-market-tape")).toContainText(
    "Real Futu daily bars",
  );
  await expectEnglishProductCopy(page);
  await page.locator('[role="tab"]').nth(1).click();
  await expectEnglishProductCopy(page);
  await page.locator('[role="tab"]').nth(2).click();
  await expect(page.locator("[data-hung-effect]")).toContainText("Days with fills 2");
  await expect(page.locator("[data-hung-effect]")).toContainText("Covers 1/1 strategies");
  await expectEnglishProductCopy(page);
  await page.locator('[role="tab"]').nth(1).click();
  await openChat.click();
  await expect(page.locator(".dp-chat-toggle")).toHaveAttribute("aria-expanded", "true");
  const closeChat = page.getByRole("button", { name: "Close chat" });
  await expect(closeChat).toBeFocused();
  await expect(rail).toHaveAttribute("role", "dialog");
  await expect(rail).toHaveAttribute("aria-modal", "true");
  await expect(page.locator("#hermes-ledger-panel")).toHaveAttribute("inert", "");
  await page.keyboard.press("Shift+Tab");
  await expect(closeChat).not.toBeFocused();
  await page.keyboard.press("Tab");
  await expect(closeChat).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(openChat).toBeFocused();
  await expect(rail).toBeHidden();

  await openChat.click();
  await expect(closeChat).toBeFocused();
  const railBounds = await rail.boundingBox();
  expect(railBounds?.width ?? 0).toBeGreaterThanOrEqual(389);
  const card = page.locator("[data-platform-research-result]");
  await expect(card).toBeVisible();
  await expect(card).toContainText("Platform research result");
  await expect(card).toContainText("Candidate verified for this conversation.");
  await expect(card).toContainText("candidate-active");
  await expect(card.getByRole("link", { name: "Evidence receipt" })).toHaveAttribute(
    "href",
    evidence("e".repeat(64), digest).value.href,
  );
  const disclosure = card.getByRole("button", { name: "Show evidence" });
  await expect(disclosure).toHaveAttribute("aria-expanded", "false");
  await disclosure.click();
  await expect(card.getByRole("button", { name: "Hide evidence" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  await expect(card).toContainText("1bp + 5bp");
  await expect(card).toContainText("Recomputable performance");
  await expect(card).toContainText("factor_id = 'verified_factor'");
  await expect(card).not.toContainText("Wrong session result");
  await expect(card).not.toHaveAttribute("data-role", "hermes");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  expect(remoteWrites).toBe(0);

  await page.getByText("Recent chats", { exact: true }).click();
  const sessionLink = page.getByRole("link", { name: /Current research session/ });
  await Promise.all([
    page.waitForURL(`/en/hermes?hermes_session_id=${sessionId}`),
    sessionLink.click(),
  ]);
  // Recent chats are ordinary anchors: wait for their document assets before
  // deliberately opening the separately retained historical permalink.
  await page.waitForLoadState("networkidle");
  await page.goto(`/en/hermes/sessions/${sessionId}`, { waitUntil: "networkidle" });
  await expect(page.locator(`[data-hermes-session-detail="${sessionId}"]`)).toBeVisible();
  await expect(page.locator(".dp-topstrip")).not.toHaveAttribute("inert", "");
  await expect(page.locator(".dp-topstrip")).not.toHaveAttribute("aria-hidden", "true");
  await expect(page.locator(".dp-footer")).not.toHaveAttribute("inert", "");
  expectNoBrowserErrors(browserErrors);
});

test("remote book 503 is one physical read and never shown as running", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page, [
    { method: "GET", status: 503, url: "/api/assistant/remote/book" },
    {
      failureText: "net::ERR_ABORTED",
      method: "GET",
      url: `/api/hermes/sessions/web_${"9".repeat(40)}/messages`,
    },
  ]);
  await page.setViewportSize({ width: 390, height: 844 });
  const sessionId = `web_${"9".repeat(40)}`;
  let bookGets = 0;
  await page.route("**/api/assistant/remote/book", async (route) => {
    bookGets += 1;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ detail: { code: "remote_book_unavailable" } }),
      status: 503,
    });
  });
  await page.route("**/api/hermes/sessions/**/messages", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        read_status: "available",
        messages: [],
        omitted: 0,
      }),
      status: 200,
    });
  });
  await page.route("**/api/paper/strategy-sleeves/observation-calendar", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        yesterday: {
          date: "2026-08-23",
          status: "not_scheduled",
          label_zh: "",
          counts_as_observation_day: false,
          is_no_signal: false,
        },
        observation_day_count: 0,
      }),
      status: 200,
    });
  });
  await page.route("**/api/market-data/history?*", async (route) => {
    const url = new URL(route.request().url());
    const ticker = url.searchParams.get("ticker") ?? "SPY";
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        symbol: ticker,
        ticker,
        source: "futu",
        frequency: "1d",
        row_count: 1,
        rows: [{ timestamp: "2026-08-22T00:00:00+00:00", close: 100 }],
        metadata: { provider: "futu" },
      }),
      status: 200,
    });
  });

  await page.goto(`/en/hermes?hermes_session_id=${sessionId}`);
  await page.getByRole("button", { name: "Open chat" }).click();

  await expect(page.getByText(/research book is unavailable/i)).toBeVisible();
  await expect(page.getByText(/Research job is running/i)).toHaveCount(0);
  expect(bookGets).toBe(1);
  expectNoBrowserErrors(browserErrors);
});
