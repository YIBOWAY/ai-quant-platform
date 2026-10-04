import { expect, test } from "@playwright/test";

test.beforeEach(() => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");
});

test("watch aliases are exact 301 redirects for bare and localized routes", async ({
  request,
}) => {
  const aliases = [
    ["/data-explorer", "/watch?pane=quotes"],
    ["/market-cross-section", "/watch?pane=cross"],
    ["/asia-radar", "/watch?pane=radar"],
  ] as const;
  for (const prefix of ["", "/en", "/zh"] as const) {
    for (const [source, target] of aliases) {
      const response = await request.get(`${prefix}${source}`, {
        maxRedirects: 0,
      });
      expect(response.status(), `${prefix}${source}`).toBe(301);
      expect(response.headers().location).toBe(`${prefix}${target}`);
    }
  }
});

test("merged page aliases preserve old query while landing on their canonical owner", async ({
  page,
  request,
}) => {
  for (const [source, target] of [
    ["/position-map", "/paper-trading?view=map"],
    ["/hermes/sessions", "/hermes"],
  ] as const) {
    const response = await request.get(source, { maxRedirects: 0 });
    expect(response.status()).toBe(301);
    expect(response.headers().location).toBe(target);
  }

  await page.goto("/data-explorer?symbol=SPY&provider=sample");
  const redirected = new URL(page.url());
  expect(redirected.pathname).toBe("/watch");
  expect(Object.fromEntries(redirected.searchParams)).toEqual({
    symbol: "SPY",
    provider: "sample",
    pane: "quotes",
  });
  await expect(page.getByTestId("data-explorer-scroll-region")).toBeVisible();
});

test("Hermes chat rail owns the recent-session list and keeps detail as a deep link", async ({
  page,
}) => {
  await page.route("**/api/hermes/sessions?**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        read_status: "available",
        sessions: [
          {
            id: "session-op4",
            title: "OP4 retained transcript",
            message_count: 8,
          },
        ],
        limit: 12,
        offset: 0,
        has_more: false,
        warnings: [],
      }),
      status: 200,
    });
  });
  await page.route("**/api/assistant/remote/book", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ candidates: [], requests: [] }),
      status: 200,
    });
  });

  await page.goto("/hermes", { waitUntil: "domcontentloaded" });
  const disclosure = page.locator("[data-hermes-recent-sessions] summary");
  const disclosureBounds = await disclosure.boundingBox();
  expect(disclosureBounds?.height ?? 0).toBeGreaterThanOrEqual(44);
  await page.locator("[data-hermes-recent-sessions]").evaluate((node) => {
    (node as HTMLDetailsElement).open = true;
  });
  const sessionLink = page.getByRole("link", { name: /OP4 retained transcript/ });
  await expect(sessionLink).toHaveAttribute(
    "href",
    "/en/hermes?hermes_session_id=session-op4",
  );
  const linkBounds = await sessionLink.boundingBox();
  expect(linkBounds?.height ?? 0).toBeGreaterThanOrEqual(44);
});
