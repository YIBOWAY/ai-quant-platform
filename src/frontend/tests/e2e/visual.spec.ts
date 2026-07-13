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

    await expect(page.getByRole("heading", { name: "Daily Morning Brief" })).toBeVisible();
    await expect(page.getByText("THE ACCOUNT")).toBeVisible();
    await expect(page.getByText("ONE-WEEK PAPER RETURN")).toBeVisible();
    await expect(page.getByRole("heading", { name: "SPY" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "QQQ" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "SOXX" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "IGV" })).toBeVisible();
    await expect(
      page.getByText("-- Hermes note · editor's margin", { exact: true }),
    ).toBeVisible();
    await expect(page.getByText(/Morning brief printed|lede prepared by Hermes/i)).toBeVisible();
    await expect(page.getByText(/live trading never implied active/i)).toBeVisible();

    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollWidth).toBeLessThanOrEqual(390);
  });
});

test.describe("brief visual baseline", () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test("visual baseline: zh brief", async ({ page }) => {
    // Prefer CTA absent (DB disabled in playwright.config) so snapshot stays hermetic.
    // page.clock only freezes browser time; SSR still uses server Date for the masthead
    // date strip and log timestamps — mask those volatile regions.
    await preparePage(page, "/zh/brief");
    await expect(page.getByRole("heading", { name: "每日晨报" })).toBeVisible();

    const volatileMasks = [
      page.locator("header .mt-5").first(),
      page.locator("section").filter({ hasText: "THE ACCOUNT" }).first(),
      page.locator("section").filter({ hasText: "ONE-WEEK PAPER RETURN" }).first(),
      page.locator("section").filter({ hasText: "THE MARKET" }).first(),
      page.locator("section").filter({ hasText: /THE LOG/ }).first(),
    ];

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
