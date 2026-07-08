import { expect, test, type Page } from "@playwright/test";

const visualTestTime = new Date("2026-07-08T12:00:00Z");

const screenshotOptions = {
  animations: "disabled",
  maxDiffPixelRatio: 0.05,
} as const;

const desktopRoutes = [
  { path: "/", snapshot: "home-desktop.png", title: "home" },
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

test.describe("mobile shell visual baseline", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("home mobile", async ({ page }) => {
    await preparePage(page, "/");
    await expect(page).toHaveScreenshot("home-mobile.png", screenshotOptions);
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
  await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => undefined);
  await page.evaluate(async () => {
    await document.fonts?.ready;
  }).catch(() => undefined);
}
