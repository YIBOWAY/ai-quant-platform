import { expect, test } from "@playwright/test";

test.describe("phase14 buy-side options assistant smoke", () => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");

  test("buy-side assistant submits a thesis and renders recommendations", async ({ page }) => {
    await page.route("**/api/options/buy-side/assistant", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ticker: "AAPL",
          generated_at: "2026-05-04T00:00:00Z",
          thesis: {
            ticker: "AAPL",
            spot_price: 200,
            view_type: "short_term_conservative_bullish",
            target_price: 212,
            target_date: "2026-06-30",
            max_loss_budget: 1200,
            risk_preference: "balanced",
            allow_capped_upside: true,
            avoid_high_iv: true,
            volatility_view: "auto",
            event_risk: "none",
          },
          recommendations: [
            {
              strategy_type: "bull_call_spread",
              score: 82,
              rank: 1,
              one_line_summary: "Primary risk: volatility",
              key_reasons: ["Break-even is below the target price.", "Defined-risk structure lowers IV exposure."],
              key_risks: ["CAPPED_UPSIDE"],
              max_loss: 480,
              max_profit: 520,
              break_even: 204.8,
              required_move_pct: 2.4,
              theta_burn_7d_pct: 4.2,
              estimated_iv_crush_loss_pct: 6.5,
              liquidity_score: 88,
              risk_reward: 1.08,
              expected_move_pct: 7.9,
              target_vs_expected_move_ratio: 0.76,
              buyer_friendliness_score: 84,
              iv_crash_risk_score: 35,
              risk_attribution: { direction: 38, time: 42, volatility: 61, liquidity: 20 },
              primary_risk_source: "volatility",
              market_regime: "Normal",
              market_regime_penalty: 0,
              warnings: ["CAPPED_UPSIDE"],
              scenario_summary: {
                best_case_pnl: 520,
                worst_case_pnl: -480,
                flat_spot_iv_crush_pnl: -90,
                spot_up_iv_down_pnl: 180,
                theta_only_pnl: -28,
                probability_not_calculated: true,
              },
              scenario_ev: {
                expected_value: 92,
                contributions: [
                  { label: "bull", probability: 0.35, pnl: 280, weighted_pnl: 98 },
                  { label: "base", probability: 0.45, pnl: 20, weighted_pnl: 9 },
                  { label: "bear", probability: 0.2, pnl: -75, weighted_pnl: -15 },
                ],
              },
              demotion: null,
              legs: [
                {
                  action: "buy",
                  option_type: "call",
                  strike: 200,
                  expiration: "2026-06-19",
                  quantity: 1,
                  premium: 8,
                  contract_size: 100,
                },
                {
                  action: "sell",
                  option_type: "call",
                  strike: 210,
                  expiration: "2026-06-19",
                  quantity: 1,
                  premium: 3.2,
                  contract_size: 100,
                },
              ],
              net_debit: 4.8,
            },
            {
              strategy_type: "long_call",
              score: 74,
              rank: 2,
              one_line_summary: "Long Call is usable but has more IV exposure.",
              key_reasons: ["Uncapped upside remains aligned with the thesis."],
              key_risks: ["HIGH_IV_CRUSH_RISK"],
              max_loss: 800,
              max_profit: null,
              break_even: 208,
              required_move_pct: 4,
              theta_burn_7d_pct: 5.2,
              estimated_iv_crush_loss_pct: 9.5,
              liquidity_score: 80,
              risk_reward: null,
              expected_move_pct: 7.9,
              target_vs_expected_move_ratio: 0.76,
              buyer_friendliness_score: 72,
              iv_crash_risk_score: 48,
              risk_attribution: { direction: 42, time: 45, volatility: 70, liquidity: 22 },
              primary_risk_source: "volatility",
              market_regime: "Normal",
              market_regime_penalty: 0,
              warnings: ["HIGH_IV_CRUSH_RISK"],
              scenario_summary: {
                best_case_pnl: 900,
                worst_case_pnl: -800,
                flat_spot_iv_crush_pnl: -140,
                spot_up_iv_down_pnl: 260,
                theta_only_pnl: -42,
                probability_not_calculated: true,
              },
              scenario_ev: null,
              demotion: null,
              legs: [
                {
                  action: "buy",
                  option_type: "call",
                  strike: 200,
                  expiration: "2026-06-19",
                  quantity: 1,
                  premium: 8,
                  contract_size: 100,
                },
              ],
              net_debit: 8,
            },
          ],
          warnings: [],
          safety: {
            dry_run: true,
            paper_trading: true,
            live_trading_enabled: false,
            kill_switch: true,
            bind_address: "127.0.0.1",
          },
        }),
      });
    });

    await page.goto("/options-buyside");
    await page.waitForLoadState("networkidle");

    await expect(
      page.getByText(
        "This tool provides quantitative decision support only and is not financial advice. Options involve risk and may lose value rapidly due to time decay, volatility changes, liquidity, and adverse underlying price movement. Review official options risk disclosures before trading.",
      ),
    ).toBeVisible();
    await expect(page.locator("body")).not.toContainText(
      /buy this|guaranteed profit|safe strategy|best trade|risk-free/i,
    );
    await page.getByLabel("Ticker").fill("AAPL");
    await page.getByLabel("Target price").fill("212");
    await page.getByRole("button", { name: /Run Assistant/i }).click();

    await expect(page.getByRole("heading", { name: "Bull Call Spread" })).toBeVisible();
    await expect(page.getByText("Selected contracts").first()).toBeVisible();
    await page.getByRole("button", { name: /Details/i }).nth(1).click();
    await expect(page.getByText("Reasons")).toHaveCount(2);
    await expect(page.getByText(/Primary risk: volatility/i)).toBeVisible();
    await expect(page.getByText("Anti-Pitfall Checklist")).toBeVisible();
    await expect(page.getByText(/not a market-implied probability/i).first()).toBeVisible();
  });
});
