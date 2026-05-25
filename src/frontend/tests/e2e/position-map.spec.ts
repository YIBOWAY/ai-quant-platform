import { expect, test } from "@playwright/test";

test.describe("position map", () => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");

  test("renders latest backtest position exposure from real run output", async ({ page, request }) => {
    test.setTimeout(90_000);

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

    await page.goto("/position-map", { waitUntil: "domcontentloaded" });

    await expect(page.getByRole("heading", { name: "Position Map" })).toBeVisible();
    await expect(page.getByText("Portfolio Exposure")).toBeVisible();
    await expect(page.getByText("Exposure by Symbol")).toBeVisible();
    await expect(page.getByText("Latest Backtest Positions")).toBeVisible();
    await expect(page.getByText(/SPY|QQQ/).first()).toBeVisible();
  });
});
