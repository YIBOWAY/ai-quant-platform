import { expect, test } from "@playwright/test";

async function installOptionsMarketFixtures(page: import("@playwright/test").Page) {
  const expiry = "2026-07-17";
  await page.route("**/api/options/snapshot/*", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        ticker: "AAPL",
        source: "playwright-fixture",
        price: 200,
        nearest_expiry: expiry,
        atm_iv: 0.28,
        hv_30d: 0.22,
        iv_rank: 55,
        iv_percentile: 60,
        iv_rank_source: "fixture",
        vrp: 0.06,
        vrp_level: "Normal",
        assumptions: ["Playwright fixture for local options-tool smoke tests."],
      }),
    });
  });
  await page.route("**/api/options/chain?**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ticker: "AAPL",
        source: "playwright-fixture",
        expiration: expiry,
        option_type: "ALL",
        contracts: [
          {
            symbol: "AAPL260717C00195000",
            option_type: "CALL",
            expiry,
            strike: 195,
            bid: 8.2,
            ask: 8.6,
            implied_volatility: 0.3,
            delta: 0.61,
            volume: 1200,
            open_interest: 5000,
          },
          {
            symbol: "AAPL260717C00200000",
            option_type: "CALL",
            expiry,
            strike: 200,
            bid: 5.2,
            ask: 5.6,
            implied_volatility: 0.28,
            delta: 0.52,
            volume: 1500,
            open_interest: 6200,
          },
          {
            symbol: "AAPL260717C00210000",
            option_type: "CALL",
            expiry,
            strike: 210,
            bid: 2.3,
            ask: 2.6,
            implied_volatility: 0.29,
            delta: 0.34,
            volume: 900,
            open_interest: 4100,
          },
          {
            symbol: "AAPL260717P00200000",
            option_type: "PUT",
            expiry,
            strike: 200,
            bid: 4.8,
            ask: 5.1,
            implied_volatility: 0.29,
            delta: -0.47,
            volume: 1100,
            open_interest: 5800,
          },
        ],
      }),
    });
  });
}

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

  test("backtest renders a strategy and benchmark line chart", async ({ page, request }) => {
    const response = await request.post("http://127.0.0.1:8765/api/backtests/run", {
      data: {
        symbols: ["SPY", "QQQ"],
        start: "2024-01-02",
        end: "2024-01-18",
        lookback: 3,
        top_n: 1,
        initial_cash: 100000,
        commission_bps: 1,
        slippage_bps: 5,
        provider: "sample",
      },
    });
    expect(response.status()).toBe(200);

    await page.goto("/backtest?include_sample=1", { waitUntil: "domcontentloaded" });

    await expect(page.getByTestId("equity-comparison-chart")).toBeVisible();
    await expect(page.getByText("Strategy", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Benchmark", { exact: true }).first()).toBeVisible();
  });

  test("options tools page exposes the local AlphaGBM toolbox", async ({ page }) => {
    await installOptionsMarketFixtures(page);
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
    await expect(page.getByText("Charm", { exact: true })).toBeVisible();

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
      page.waitForResponse((response) => response.url().includes("/api/options/tools/strategy/build")),
      page.getByRole("button", { name: "Build Strategy" }).click(),
    ]);
    await expect(page.getByText('"template_id"')).toBeVisible();
  });
});
