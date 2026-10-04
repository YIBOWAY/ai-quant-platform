import { expect, test } from "@playwright/test";

import {
  collectBrowserErrors,
  expectNoBrowserErrors,
} from "./helpers/console-error-gate";

test.beforeEach(() => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");
});

test("candidate book 503 performs exactly one physical read", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page, [
    { method: "GET", status: 503, url: "/api/assistant/remote/book" },
  ]);
  let bookGets = 0;
  await page.route("**/api/assistant/remote/book", async (route) => {
    bookGets += 1;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ detail: { code: "remote_book_unavailable" } }),
      status: 503,
    });
  });

  await page.clock.install();
  await page.goto("/en/library");
  await expect(page.getByText(/verified-candidate book is unavailable/i)).toBeVisible();
  await page.clock.fastForward(2_500);

  expect(bookGets).toBe(1);
  expectNoBrowserErrors(browserErrors);
});

test("candidate library stays read-only until the digest-bound paper action", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  const digest = "a".repeat(64);
  let bookGets = 0;
  let hangPosts = 0;

  await page.route("**/api/assistant/remote/book", async (route) => {
    expect(route.request().method()).toBe("GET");
    bookGets += 1;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        candidates: [
          {
            candidate_id: "verified-ready",
            factor_id: "momentum_20d",
            objective: "Cross-sectional momentum",
            source_digest: digest,
            status: "verified",
            sleeve_id: null,
            universe: ["US.NVDA", "US.AAPL"],
            activation_eligibility: { eligible: true, reason: null },
          },
          {
            candidate_id: "already-bound",
            source_digest: digest,
            status: "verified",
            sleeve_id: "paper-existing",
          },
          {
            candidate_id: "not-verified",
            source_digest: digest,
            status: "candidate_ready",
            sleeve_id: null,
          },
          {
            candidate_id: "invalid-digest",
            source_digest: "abc",
            status: "verified",
            sleeve_id: null,
          },
        ],
      }),
      status: 200,
    });
  });
  await page.route("**/api/auth/owner/session", async (route) => {
    expect(route.request().method()).toBe("GET");
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        mutation_enabled: true,
        security_ready: true,
        session_id: "owner-library",
      }),
      status: 200,
    });
  });
  await page.route("**/api/assistant/remote/hang", async (route) => {
    hangPosts += 1;
    expect(route.request().method()).toBe("POST");
    expect(route.request().postDataJSON()).toEqual({
      candidate_id: "verified-ready",
      expected_source_digest: digest,
    });
    expect(route.request().headers()["x-csrf-token"]).toBe("csrf-library");
    await new Promise((resolve) => setTimeout(resolve, 100));
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        already_hung: true,
        candidate_id: "verified-ready",
        sleeve_id: "paper-sleeve-1",
        source_digest: digest,
        status: "hung",
      }),
      status: 200,
    });
  });

  await page.clock.install();
  await page.goto("/en/library");
  await page.context().addCookies([
    {
      name: "qs_aw_csrf",
      url: new URL(page.url()).origin,
      value: "csrf-library",
    },
  ]);
  await expect(page.getByText("verified-ready", { exact: true })).toBeHidden();
  await page.getByText("Technical details", { exact: true }).click();
  await expect(page.getByText("verified-ready", { exact: true })).toBeVisible();
  await expect(page.getByText("already-bound", { exact: true })).toHaveCount(0);
  await expect(page.getByText("not-verified", { exact: true })).toHaveCount(0);
  await expect(page.getByText("invalid-digest", { exact: true })).toHaveCount(0);

  const searchbox = page.getByRole("searchbox", { name: "Search verified candidates" });
  const searchBoxBounds = await searchbox.boundingBox();
  expect(searchBoxBounds?.height ?? 0).toBeGreaterThanOrEqual(44);
  await searchbox.fill("NVDA");
  await expect(page.getByText("verified-ready", { exact: true })).toBeVisible();
  await page.getByRole("searchbox", { name: "Search verified candidates" }).fill("missing");
  await expect(page.getByText("No verified candidate matches this search.")).toBeVisible();
  expect(hangPosts).toBe(0);

  const initialGets = bookGets;
  await page.clock.fastForward(15_100);
  await expect.poll(() => bookGets).toBeGreaterThan(initialGets);
  expect(hangPosts).toBe(0);

  await page.getByRole("searchbox", { name: "Search verified candidates" }).fill("");
  const hangButton = page.getByRole("button", { name: /Enable simulated running:/ });
  const hangButtonBounds = await hangButton.boundingBox();
  expect(hangButtonBounds?.height ?? 0).toBeGreaterThanOrEqual(44);
  expect(hangButtonBounds?.width ?? 0).toBeGreaterThanOrEqual(44);
  await hangButton.click();
  await expect(page.locator('[data-hang-state="pending"]')).toBeVisible();
  await expect(
    page.getByRole("status").filter({ hasText: "Enabling" }),
  ).toBeAttached();
  await expect(page.locator('[data-hang-state="already_hung"]')).toContainText(
    "Simulated run active",
  );
  await expect(page.getByText(/paper-sleeve-1/)).toBeHidden();
  await page.locator('[data-hang-state="already_hung"] + details summary').click();
  await expect(page.getByText(/paper-sleeve-1/)).toBeVisible();
  expect(hangPosts).toBe(1);
  expectNoBrowserErrors(browserErrors);
});

const unknownScenarios = [
  {
    name: "resolved hung",
    candidates: (digest: string) => [
      {
        candidate_id: "verified-unknown",
        factor_id: "factor_unknown",
        source_digest: digest,
        status: "hung",
        sleeve_id: "paper-resolved",
      },
    ],
    message: "exact candidate is running in simulation",
  },
  {
    name: "still verified",
    candidates: (digest: string) => [
      {
        candidate_id: "verified-unknown",
        factor_id: "factor_unknown",
        source_digest: digest,
        status: "verified",
        sleeve_id: null,
      },
    ],
    message: "candidate is research-verified but not enabled",
  },
  {
    name: "still unknown",
    candidates: (_digest: string) => [],
    message: "still cannot be resolved",
  },
] as const;

for (const scenario of unknownScenarios) {
  test(`uncertain hang resolves as ${scenario.name} without a second mutation`, async ({
    page,
  }) => {
    const browserErrors = collectBrowserErrors(page, [
      {
        failureText: "net::ERR_CONNECTION_RESET",
        method: "POST",
        url: "/api/assistant/remote/hang",
      },
    ]);
    const digest = "d".repeat(64);
    let bookGets = 0;
    let hangPosts = 0;
    await page.route("**/api/assistant/remote/book", async (route) => {
      bookGets += 1;
      const candidates =
        bookGets === 1
          ? [
              {
                candidate_id: "verified-unknown",
                factor_id: "factor_unknown",
                source_digest: digest,
                status: "verified",
                sleeve_id: null,
                activation_eligibility: { eligible: true, reason: null },
              },
            ]
          : scenario.candidates(digest);
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ candidates }),
        status: 200,
      });
    });
    await page.route("**/api/auth/owner/session", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          mutation_enabled: true,
          security_ready: true,
          session_id: "owner-library",
        }),
        status: 200,
      });
    });
    await page.route("**/api/assistant/remote/hang", async (route) => {
      hangPosts += 1;
      await route.abort("connectionreset");
    });

    await page.goto("/en/library");
    await page.context().addCookies([
      {
        name: "qs_aw_csrf",
        url: new URL(page.url()).origin,
        value: "csrf-library",
      },
    ]);
    const hangButton = page.getByRole("button", { name: /Enable simulated running:/ });
    await hangButton.click();

    await expect(page.getByText(/Activation outcome unknown/)).toBeVisible();
    await expect(hangButton).toBeDisabled();
    expect(hangPosts).toBe(1);
    const beforeRefresh = bookGets;
    const refreshButton = page.getByRole("button", { name: "Refresh candidate book" });
    const refreshBounds = await refreshButton.boundingBox();
    expect(refreshBounds?.height ?? 0).toBeGreaterThanOrEqual(44);
    await refreshButton.click();
    await expect.poll(() => bookGets).toBeGreaterThan(beforeRefresh);
    await expect(page.getByText(new RegExp(scenario.message, "i"))).toBeVisible();
    expect(hangPosts).toBe(1);
    expectNoBrowserErrors(browserErrors);
  });
}
