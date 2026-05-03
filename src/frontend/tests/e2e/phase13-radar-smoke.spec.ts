import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

const repoRoot = findRepoRoot(process.cwd());
const outputDir = path.join(repoRoot, "data", "options_scans");
const runDate = "2099-01-02";

function findRepoRoot(start: string) {
  let current = path.resolve(start);
  while (true) {
    if (
      fs.existsSync(path.join(current, "pyproject.toml")) &&
      fs.existsSync(path.join(current, "src", "frontend", "package.json"))
    ) {
      return current;
    }
    const parent = path.dirname(current);
    if (parent === current) {
      throw new Error(`Unable to locate repository root from ${start}`);
    }
    current = parent;
  }
}

test.describe("phase13 options radar smoke", () => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");

  test.beforeAll(() => {
    fs.mkdirSync(outputDir, { recursive: true });
    const candidate = {
      run_date: runDate,
      ticker: "SPY",
      sector: "ETF",
      strategy: "sell_put",
      iv_rank: 72.5,
      earnings_in_window: false,
      global_score: 142.5,
      market_regime: "Normal",
      market_regime_penalty: 0,
      candidate: {
        symbol: "US.SPY990102P450000",
        underlying: "US.SPY",
        strategy_type: "sell_put",
        option_type: "PUT",
        expiry: "2099-01-16",
        strike: 450,
        underlying_price: 500,
        bid: 2.1,
        ask: 2.2,
        mid: 2.15,
        volume: 100,
        open_interest: 500,
        implied_volatility: 0.32,
        historical_volatility: 0.18,
        hv_iv_ratio: 0.56,
        delta: -0.24,
        gamma: 0.02,
        theta: -0.01,
        vega: 0.1,
        premium_per_contract: 215,
        moneyness: 0.9,
        distance_pct: 0.1,
        days_to_expiry: 14,
        annualized_yield: 0.12,
        spread_pct: 0.046,
        trend_pass: true,
        hv_iv_pass: true,
        avg_daily_volume: 1000000,
        market_cap: 100000000000,
        iv_rank: 72.5,
        earnings_date: null,
        rating: "Strong",
        notes: ["fixture candidate"],
      },
    };
    fs.writeFileSync(path.join(outputDir, `${runDate}.jsonl`), `${JSON.stringify(candidate)}\n`);
    fs.writeFileSync(
      path.join(outputDir, `${runDate}_meta.json`),
      JSON.stringify(
        {
          run_date: runDate,
          started_at: "2099-01-02T00:00:00Z",
          finished_at: "2099-01-02T00:00:01Z",
          universe_size: 1,
          scanned_tickers: 1,
          failed_tickers: [],
          candidate_count: 1,
        },
        null,
        2,
      ),
    );
  });

  test.afterAll(() => {
    fs.rmSync(path.join(outputDir, `${runDate}.jsonl`), { force: true });
    fs.rmSync(path.join(outputDir, `${runDate}_meta.json`), { force: true });
  });

  test("options radar page renders fixture and expands notes", async ({ page }) => {
    await page.goto("/options-radar");
    await page.waitForLoadState("networkidle");

    await expect(page.getByText(/read-only research output/i)).toBeVisible();
    await expect(page.getByText("SPY")).toBeVisible();
    await expect(page.getByRole("button", { name: /Export CSV/i })).toBeEnabled();
    await page.getByRole("button", { name: /Details/i }).click();
    await expect(page.getByText("fixture candidate")).toBeVisible();
  });
});
