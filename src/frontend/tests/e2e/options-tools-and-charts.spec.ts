import { expect, test } from "@playwright/test";

test.describe("options tools and real chart surfaces", () => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");

  test("data explorer renders a real candlestick chart", async ({ page }) => {
    await page.goto("/data-explorer?provider=sample&symbol=SPY&start=2024-01-02&end=2024-02-15", {
      waitUntil: "domcontentloaded",
    });

    const chart = page.getByTestId("ohlcv-candlestick-chart");
    await expect(chart).toBeVisible();
    await expect(chart.locator("canvas").first()).toBeVisible();
    expect(await chart.locator("canvas").count()).toBeGreaterThan(0);
    await expect(page.getByTestId("ohlcv-candlestick-chart").getByText("Volume")).toBeVisible();
  });

  test("data explorer initial load uses the backend default source", async ({ page }) => {
    await page.goto("/data-explorer", { waitUntil: "domcontentloaded" });

    await expect(page.getByLabel("Source")).toHaveValue(/^(futu|sample|tiingo)$/);
    await expect(page.getByTestId("ohlcv-candlestick-chart")).toBeVisible();
    await expect(page.getByText("Rows returned")).toBeVisible();
    await expect(page.getByText("Quality report not connected")).toHaveCount(0);
  });

  test("backtest renders a strategy and benchmark line chart", async ({ page }) => {
    await page.goto("/backtest", { waitUntil: "domcontentloaded" });

    await expect(page.getByTestId("equity-comparison-chart")).toBeVisible();
    await expect(page.getByText("Strategy", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Benchmark", { exact: true }).first()).toBeVisible();
  });

  test("options tools page exposes the local AlphaGBM toolbox", async ({ page }) => {
    await page.goto("/options-tools", { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("heading", { name: "Options Tools" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Greeks" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Strategy Rank" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Score Contracts" })).toBeVisible();

    await page.getByRole("tab", { name: "Greeks" }).click();
    await Promise.all([
      page.waitForResponse((response) => response.url().includes("/api/options/tools/greeks")),
      page.getByRole("button", { name: "Calculate Greeks" }).click(),
    ]);
    await expect(page.getByText("Delta")).toBeVisible();

    await page.getByRole("tab", { name: "Strategy Rank" }).click();
    await Promise.all([
      page.waitForResponse((response) => response.url().includes("/api/options/tools/strategy/rank")),
      page.getByRole("button", { name: "Rank Strategies" }).click(),
    ]);
    await expect(page.getByText("Bull Call Spread")).toBeVisible();

    await page.getByRole("tab", { name: "Signals" }).click();
    await Promise.all([
      page.waitForResponse((response) => response.url().includes("/api/options/tools/fear-score")),
      page.getByRole("button", { name: "Fear Score", exact: true }).click(),
    ]);
    await expect(page.getByText('"fear_score"')).toBeVisible();
    await Promise.all([
      page.waitForResponse((response) => response.url().includes("/api/options/tools/implied-volatility")),
      page.getByRole("button", { name: "Implied Volatility" }).click(),
    ]);
    await expect(page.getByText('"implied_volatility"')).toBeVisible();

    await page.getByRole("tab", { name: "Research Ops" }).click();
    await Promise.all([
      page.waitForResponse((response) => response.url().includes("/api/options/tools/strategy/templates")),
      page.getByRole("button", { name: "Strategy Templates" }).click(),
    ]);
    await expect(page.getByText('"templates"')).toBeVisible();
    await Promise.all([
      page.waitForResponse((response) => response.url().includes("/api/options/tools/health-check")),
      page.getByRole("button", { name: "Health Check" }).click(),
    ]);
    await expect(page.getByText('"health_score"')).toBeVisible();
  });
});
