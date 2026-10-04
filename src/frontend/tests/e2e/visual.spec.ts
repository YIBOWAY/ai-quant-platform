import { expect, test, type Page } from "@playwright/test";

const visualTestTime = new Date("2026-07-08T12:00:00Z");

const screenshotOptions = {
  animations: "disabled",
  maxDiffPixelRatio: 0.05,
} as const;

const desktopRoutes = [
  {
    path: "/data-explorer?provider=sample&symbol=SPY&start=2024-01-02&end=2024-02-15",
    snapshot: "data-explorer-desktop.png",
    title: "data explorer",
  },
  { path: "/backtest?include_sample=1", snapshot: "backtest-desktop.png", title: "backtest" },
  { path: "/strategies", snapshot: "strategies-desktop.png", title: "strategies" },
  {
    path: "/options-screener",
    snapshot: "options-screener-desktop.png",
    title: "options screener",
  },
  { path: "/paper-trading", snapshot: "paper-trading-desktop.png", title: "paper trading" },
  { path: "/position-map", snapshot: "position-map-desktop.png", title: "position map" },
  { path: "/hermes", snapshot: "hermes-desktop.png", title: "hermes" },
] as const;

test.beforeEach(() => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack visual checks.");
});

test.describe("desktop visual baselines", () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  for (const route of desktopRoutes) {
    test(`${route.title} desktop`, async ({ page }) => {
      await preparePage(page, route.path);
      await expect(page).toHaveScreenshot(route.snapshot, screenshotOptions);
    });
  }
});

test.describe("brief trial smoke", () => {
  test("brief renders the editorial trial columns and fits mobile width", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    // Pin locale in the path so a prior /zh cookie cannot flip English selectors.
    await preparePage(page, "/en/brief");

    await expect(page.getByRole("heading", { name: "Daily Brief" })).toBeVisible();
    await expect(page.getByText("THE ACCOUNT")).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Performance chart range" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "SPY", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "QQQ", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "SOXX", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "IGV", exact: true })).toBeVisible();
    await expect(
      page.getByText("-- Platform market note", { exact: true }),
    ).toBeVisible();
    await expect(page.getByText(/Platform market note:/i)).toBeVisible();
    await expect(page.getByText(/live trading never implied active/i)).toBeVisible();

    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollWidth).toBeLessThanOrEqual(390);
  });
});

test.describe("brief visual baseline", () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test("@brief-visual visual baseline: zh brief", async ({ page }, testInfo) => {
    // Prefer CTA absent (DB disabled in playwright.config) so snapshot stays hermetic.
    // page.clock only freezes browser time; SSR still uses server Date for the masthead
    // date strip and log timestamps — mask those volatile regions.
    await preparePage(page, "/zh/brief");
    await expect(page.getByRole("heading", { name: "量化日报" })).toBeVisible();

    // SSR display dates change across days even with the browser clock fixed.
    // Mask only precise date tokens in the masthead/byline/market-date copy;
    // do not change the runtime clock, prose, amounts, errors or missing-data text.
    const dateTokens = await page.getByRole("heading", { name: "量化日报" }).evaluate(heading => {
      const header = heading.closest("header")!;
      const content = header.parentElement!;
      const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT);
      const nodes: Text[] = [];
      while (walker.nextNode()) nodes.push(walker.currentNode as Text);
      const marked: Array<{ token: string; scope: string }> = [];
      for (const node of nodes) {
        const parent = node.parentElement;
        if (!parent || parent.closest("script, style, pre, code")) continue;
        const text = parent.textContent || "";
        const scope = header.contains(parent) ? "masthead" : /行情截至|Market bars through/.test(text) ? "market_date"
          : /根据已取得的账户、行情和新闻数据汇总|source=/.test(text) ? "source_display_time" : null;
        if (!scope) continue;
        const expression = /\d{4}年\d{1,2}月\d{1,2}日(?:\s*(?:周|星期)[一二三四五六日天])?|\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))?/g;
        const matches = [...node.data.matchAll(expression)];
        if (!matches.length) continue;
        const fragment = document.createDocumentFragment();
        let offset = 0;
        for (const match of matches) {
          fragment.append(document.createTextNode(node.data.slice(offset, match.index)));
          const span = document.createElement("span"); span.dataset.e2eBriefDate = scope; span.textContent = match[0];
          fragment.append(span); marked.push({ token: match[0], scope }); offset = match.index! + match[0].length;
        }
        fragment.append(document.createTextNode(node.data.slice(offset))); node.replaceWith(fragment);
      }
      return marked;
    });
    expect(dateTokens.some(item => item.scope === "masthead")).toBe(true);
    expect(dateTokens.every(item => /^\d{4}[-年]/.test(item.token))).toBe(true);
    await testInfo.attach("brief-visual-date-tokens.json", { body: JSON.stringify(dateTokens, null, 2), contentType: "application/json" });

    const volatileMasks = [
      page.locator("header .mt-5").first(),
      page.locator("section").filter({ hasText: "THE ACCOUNT" }).first(),
      page.locator("section").filter({ hasText: "ONE-WEEK PAPER RETURN" }).first(),
      page.locator("section").filter({ hasText: "THE MARKET" }).first(),
      page.locator("section").filter({ hasText: /THE LOG/ }).first(),
      page.locator("[data-e2e-brief-date]"),
    ];

    await page.screenshot({ path: testInfo.outputPath("brief-zh-candidate.png"), animations: "disabled", mask: volatileMasks });
    await expect(page).toHaveScreenshot("brief-zh.png", {
      ...screenshotOptions,
      mask: volatileMasks,
    });
  });
});

async function preparePage(page: Page, path: string) {
  await page.clock.setFixedTime(visualTestTime);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(path, { waitUntil: "domcontentloaded" });
  await page.addStyleTag({
    content: `
      *, *::before, *::after {
        animation-delay: 0s !important;
        animation-duration: 0s !important;
        scroll-behavior: auto !important;
        transition-delay: 0s !important;
        transition-duration: 0s !important;
      }
    `,
  });
  // networkidle / fonts are best-effort; callers must hard-assert a ready locator
  // before screenshot or interaction (heading/main) so partial loads fail loudly.
  await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => undefined);
  await page
    .evaluate(async () => {
      await document.fonts?.ready;
    })
    .catch(() => undefined);
}
