import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

const now = new Date();
const newYorkDate = new Intl.DateTimeFormat("en-CA", {
  day: "2-digit",
  month: "2-digit",
  timeZone: "America/New_York",
  year: "numeric",
}).format(now);
const runDate = newYorkDate;
const quoteSession = latestMarketSession(newYorkDate);
const quoteAsOf =
  quoteSession === newYorkDate
    ? new Date(now.getTime() - 60_000).toISOString().replace(/\.\d{3}Z$/, "Z")
    : `${quoteSession}T20:00:00Z`;
const expiry = addDays(quoteSession, 28);
const expiryCode = expiry.slice(2).replaceAll("-", "");
const manageAt = addDays(quoteSession, 7);
const legacyDate = addDays(runDate, -1);
let outputDir = "";
let generationDataPath = "";

function addDays(value: string, days: number) {
  const active = new Date(`${value}T12:00:00Z`);
  active.setUTCDate(active.getUTCDate() + days);
  return active.toISOString().slice(0, 10);
}

function latestWeekday(value: string) {
  let active = value;
  while ([0, 6].includes(new Date(`${active}T12:00:00Z`).getUTCDay())) {
    active = addDays(active, -1);
  }
  return active;
}

function latestMarketSession(value: string) {
  if (process.env.PW_E2E !== "1") {
    return latestWeekday(value);
  }
  const python = process.env.PW_PYTHON;
  if (!python) {
    throw new Error("PW_PYTHON is required for the Phase13 market-session fixture");
  }
  return execFileSync(
    python,
    [
      "-c",
      [
        "import sys",
        "from datetime import date",
        "from quant_system.options.seller_score import latest_us_market_session",
        "print(latest_us_market_session(date.fromisoformat(sys.argv[1])).isoformat())",
      ].join(";"),
      value,
    ],
    { encoding: "utf-8", env: process.env },
  ).trim();
}

function apiRecommendation(index: number) {
  const suffix = String(index).padStart(2, "0");
  return {
    ticker: `T${suffix}`,
    sector: "ETF",
    strategy: "sell_put",
    symbol: `US.T${suffix}${expiryCode}P00100000`,
    expiry,
    strike: 100,
    mid: 2.5,
    annualized_yield: 0.24,
    implied_volatility: 0.3,
    iv_rank: 55,
    iv_history_samples: 30,
    iv_rank_status: "ready",
    iv_measure: "atm30_straddle_iv_v1",
    delta: -0.25,
    open_interest: 800,
    spread_pct: 0.02,
    earnings_date: null,
    earnings_in_window: false,
    global_score: 8.75 - index * 0.01,
    market_regime: "Normal",
    market_regime_penalty: 0,
    days_to_expiry: 28,
    gross_annualized_yield: 0.24,
    pop: 0.75,
    otm_pct: 0.08,
    ex_dividend_date: null,
    ex_dividend_in_window: false,
    breakeven: 97.5,
    take_profit_50_price: 1.25,
    manage_at_21_dte: manageAt,
    expected_value: 0.64,
    excess_annualized_ev: 0.18,
    liquidity_factor: 0.92,
    recommendation_score: 0.1656 - index * 0.0001,
    recommendation_score_model: "seller_ev_liquidity_v1",
    hard_gate_passed: true,
    quote_as_of: quoteAsOf,
    extrinsic_value: 2.5,
    dividend_per_share: null,
  };
}

test.describe("phase13 options radar smoke", () => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");

  test.beforeAll(({}, testInfo) => {
    const run = testInfo.config.metadata.e2eRun as
      | { dataRoot?: unknown }
      | undefined;
    if (!run || typeof run.dataRoot !== "string" || !run.dataRoot.trim()) {
      throw new Error("Playwright e2eRun.dataRoot metadata is required");
    }
    outputDir = path.join(run.dataRoot, "options_scans");
    fs.mkdirSync(outputDir, { recursive: true });
    const dte = 28;
    // Fixed physical-lognormal payout for this fixture's price, strike,
    // min(IV, HV), drift and 28-day horizon.
    const expectedValue = 29.898409260491185;
    const grossAnnualizedYield = (30 / 450) * (365 / dte);
    const annualizedEv = (expectedValue / 450) * (365 / dte);
    const excessAnnualizedEv = annualizedEv - 0.0387;
    const liquidityFactor = 0.7;
    const candidate = {
      run_date: runDate,
      ticker: "SPY",
      sector: "ETF",
      strategy: "sell_put",
      iv_rank: 72.5,
      iv_history_samples: 30,
      iv_rank_status: "ready",
      iv_measure: "atm30_straddle_iv_v1",
      earnings_in_window: false,
      global_score: 77.95,
      market_regime: "Normal",
      market_regime_penalty: 0,
      gross_annualized_yield: grossAnnualizedYield,
      pop: 0.76,
      otm_pct: 0.1,
      ex_dividend_date: null,
      ex_dividend_in_window: false,
      dividend_per_share: null,
      extrinsic_value: 30,
      breakeven: 420,
      take_profit_50_price: 15,
      manage_at_21_dte: manageAt,
      expected_value: expectedValue,
      excess_annualized_ev: excessAnnualizedEv,
      liquidity_factor: liquidityFactor,
      recommendation_score: annualizedEv * liquidityFactor,
      recommendation_score_model: "seller_ev_liquidity_v1",
      hard_gate_passed: true,
      quote_as_of: quoteAsOf,
      candidate: {
        symbol: `US.SPY${expiryCode}P450000`,
        underlying: "US.SPY",
        strategy_type: "sell_put",
        option_type: "PUT",
        expiry,
        strike: 450,
        underlying_price: 500,
        bid: 29.5,
        ask: 30.5,
        mid: 30,
        volume: 100,
        open_interest: 500,
        implied_volatility: 0.32,
        historical_volatility: 0.18,
        hv_iv_ratio: 0.56,
        delta: -0.24,
        gamma: 0.02,
        theta: -0.01,
        vega: 0.1,
        premium_per_contract: 3000,
        moneyness: 0.9,
        distance_pct: 0.1,
        days_to_expiry: dte,
        annualized_yield: grossAnnualizedYield,
        spread_pct: 0.03333333333333333,
        trend_pass: true,
        hv_iv_pass: true,
        avg_daily_volume: 1000000,
        market_cap: 100000000000,
        iv_rank: 72.5,
        earnings_date: null,
        market_regime: "Normal",
        market_regime_penalty: 0,
        quote_as_of: quoteAsOf,
        rating: "Strong",
        notes: [],
        seller_score: {
          yield_score: 100,
          liquidity_score: 70,
          delta_safety_score: 76,
          iv_edge_score: 53.333333333333336,
          iv_rank_score: 72.5,
          composite: 77.95,
          weights_used: {
            yield: 0.3,
            liquidity: 0.25,
            delta_safety: 0.2,
            iv_edge: 0.15,
            iv_rank: 0.1,
          },
        },
      },
    };
    const data = `${JSON.stringify(candidate)}\n`;
    const generation = crypto.randomUUID().replaceAll("-", "");
    const dataFile = `${runDate}.${generation}.jsonl`;
    generationDataPath = path.join(outputDir, dataFile);
    fs.writeFileSync(generationDataPath, data);
    fs.writeFileSync(
      path.join(outputDir, `${runDate}_meta.json`),
      JSON.stringify(
        {
          contract_version: "options_recommendations/v3",
          snapshot_generation: generation,
          data_file: dataFile,
          data_sha256: crypto.createHash("sha256").update(data).digest("hex"),
          data_line_count: 1,
          run_date: runDate,
          started_at: new Date(now.getTime() - 120_000).toISOString(),
          finished_at: now.toISOString(),
          provider: "futu",
          as_of: quoteAsOf,
          status: "available",
          risk_free_rate: 0.0387,
          shortfall_count: 19,
          shortfall_reasons: { eligible_contracts_below_limit: 19 },
          universe_size: 1,
          expected_universe_size: 1,
          scanned_tickers: 1,
          failed_tickers: [],
          candidate_count: 1,
        },
        null,
        2,
      ),
    );
    fs.writeFileSync(path.join(outputDir, `${legacyDate}.jsonl`), "");
    fs.writeFileSync(
      path.join(outputDir, `${legacyDate}_meta.json`),
      JSON.stringify({
        contract_version: "options_recommendations/v1",
        run_date: legacyDate,
        started_at: now.toISOString(),
        finished_at: now.toISOString(),
        provider: "futu",
        as_of: quoteAsOf,
        status: "available",
        risk_free_rate: 0.0387,
        shortfall_count: 20,
        shortfall_reasons: {},
        universe_size: 34,
        scanned_tickers: 34,
        failed_tickers: [],
        candidate_count: 0,
      }),
    );
  });

  test.afterAll(() => {
    fs.rmSync(generationDataPath, { force: true });
    fs.rmSync(path.join(outputDir, `${runDate}_meta.json`), { force: true });
    fs.rmSync(path.join(outputDir, `${legacyDate}.jsonl`), { force: true });
    fs.rmSync(path.join(outputDir, `${legacyDate}_meta.json`), { force: true });
  });

  test("options radar page renders fixture and expands validated details", async ({ page }) => {
    const snapshotResponse = await page.request.get(
      `/api/options/daily-scan?date=${runDate}`,
    );
    expect(snapshotResponse.status()).toBe(200);
    const snapshot = await snapshotResponse.json();
    expect(snapshot.shortfall_reasons).toEqual({
      eligible_contracts_below_limit: 19,
    });
    expect(snapshot).toMatchObject({
      status: "available",
      provider: "futu",
    });
    expect(snapshot.candidates).toHaveLength(1);
    await page.goto(`/options-radar?date=${runDate}`);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText(/read-only research output/i)).toBeVisible();
    await expect(page.getByText("SPY")).toBeVisible();
    await expect(page.getByRole("button", { name: /Export CSV/i })).toBeEnabled();
    await page.getByRole("button", { name: /View scan details/i }).click();
    await expect(page.getByText(/eligible_contracts_below_limit/)).toBeVisible();
    await page.getByRole("button", { name: "Details", exact: true }).click();
    await expect(page.getByText(/score 78\.0/i)).toBeVisible();
    await expect(page.getByText(new RegExp(`manage at 21 DTE ${manageAt}`, "i"))).toBeVisible();
    await expect(page.getByText(/50% take-profit 15\.00/i)).toBeVisible();
    await expect(page.getByRole("link", { name: /Open Chain/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /Update Today's Recommendations Now/i })).toBeEnabled();
    await expect(page.getByText(/automatically at 22:00 every day/i)).toBeVisible();
  });

  test("Chinese sector filter distinguishes the two healthcare source labels", async ({ page }) => {
    await page.goto(`/zh/options-radar?date=${runDate}`, { waitUntil: "networkidle" });

    const sector = page.getByRole("combobox", { name: "行业" });
    await expect(sector.getByRole("option", { name: "医疗保健", exact: true })).toHaveCount(1);
    await expect(sector.getByRole("option", { name: "医疗健康", exact: true })).toHaveCount(1);
  });

  test("keeps the current recommendation visible while a filter refetches", async ({ page }) => {
    let releaseFilter = () => {};
    let markFilterStarted = () => {};
    const filterGate = new Promise<void>((resolve) => {
      releaseFilter = resolve;
    });
    const filterStarted = new Promise<void>((resolve) => {
      markFilterStarted = resolve;
    });
    await page.route("**/api/options/daily-scan?*", async (route) => {
      const url = new URL(route.request().url());
      if (url.searchParams.get("sector") === "Technology") {
        markFilterStarted();
        await filterGate;
      }
      await route.continue();
    });

    await page.goto(`/options-radar?date=${runDate}`, { waitUntil: "networkidle" });
    const candidate = page.locator("tbody tr").filter({ hasText: "SPY" }).first();
    await expect(candidate).toBeVisible();

    await page.getByRole("combobox", { name: "Sector" }).selectOption("Technology");
    await filterStarted;
    await expect(candidate).toBeVisible();
    await expect(page.locator(".motion-data-hold").first()).toHaveAttribute(
      "data-fetching",
      "true",
    );

    releaseFilter();
    await expect(candidate).toHaveCount(0);
  });

  test("options recommendations refresh event inputs but never overwrite the curated universe", async ({ page }) => {
    await page.route("**/api/options/refresh/**", async (route) => {
      const kind = route.request().url().split("/").pop() ?? "universe";
      expect(route.request().postDataJSON()).toMatchObject({ source: "public", top: 34 });
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          kind,
          source: "public",
          status: "refreshed",
          row_count: kind === "vix" ? 10 : 2,
          output_path: `data/options_universe/${kind}.csv`,
          fetched_at: now.toISOString(),
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
    await page.goto("/options-radar");
    await page.waitForLoadState("networkidle");

    // Manual refresh controls live behind the collapsed "Advanced data sources"
    // disclosure; retry the toggle until hydration makes it respond.
    const advancedToggle = page.getByRole("button", { name: "Advanced data sources" });
    await expect(async () => {
      await advancedToggle.click();
      await expect(page.getByRole("button", { name: "Refresh Earnings" })).toBeVisible({
        timeout: 1_000,
      });
    }).toPass({ timeout: 30_000 });

    await expect(page.getByLabel("Refresh source")).toHaveCount(0);
    await expect(page.getByText("Local sample", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Refresh Universe" })).toHaveCount(0);

    await page.getByRole("button", { name: "Refresh Earnings" }).click();
    await expect(page.getByText("Earnings refreshed")).toBeVisible();

    await page.getByRole("button", { name: "Refresh VIX" }).click();
    await expect(page.getByText("VIX refreshed")).toBeVisible();
  });

  test("options recommendations can start an update and poll progress without clearing the previous result", async ({ page }) => {
    let statusCalls = 0;
    let runCalls = 0;
    let scanCalls = 0;
    const safety = {
      dry_run: true,
      paper_trading: true,
      live_trading_enabled: false,
      kill_switch: true,
      bind_address: "127.0.0.1",
    };
    await page.clock.install({ time: now });
    await page.route(/\/api\/options\/daily-scan(?:\?.*)?$/, async (route) => {
      scanCalls += 1;
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          run_date: runDate,
          status: "available",
          provider: "futu",
          as_of: quoteAsOf,
          risk_free_rate: 0.0387,
          shortfall_count: 19,
          shortfall_reasons: { eligible_contracts_below_limit: 19 },
          universe_size: 34,
          scanned_tickers: 34,
          failed_tickers: [],
          is_stale: false,
          snapshot_age_days: 0,
          expired_candidate_count: 0,
          candidates: [apiRecommendation(scanCalls > 1 ? 1 : 0)],
          safety,
        }),
      });
    });
    await page.route("**/api/options/daily-scan/dates", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ dates: [runDate], safety }),
      });
    });
    await page.route("**/api/options/daily-scan/status", async (route) => {
      statusCalls += 1;
      const status = statusCalls === 1
        ? null
        : statusCalls < 3
          ? {
            status: "running",
            terminal: false,
            current_step: "scan",
            target_session: runDate,
            trigger: "manual",
            started_at: now.toISOString(),
            scanned_tickers: 12,
            total_tickers: 34,
          }
          : {
              status: "completed",
              terminal: true,
              current_step: "completed",
              target_session: runDate,
              trigger: "manual",
              started_at: now.toISOString(),
              finished_at: now.toISOString(),
              scanned_tickers: 34,
              total_tickers: 34,
            };
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ exists: status !== null, status_path: "daily_task_status.json", status, safety }),
      });
    });
    await page.route("**/api/options/daily-scan/run", async (route) => {
      runCalls += 1;
      expect(route.request().method()).toBe("POST");
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          status: "queued",
          terminal: false,
          current_step: "queued",
          target_session: runDate,
          trigger: "manual",
          queued_at: now.toISOString(),
          started_at: null,
          finished_at: null,
          scanned_tickers: 0,
          total_tickers: 34,
          safety,
        }),
      });
    });

    await page.goto(`/options-radar?date=${runDate}`, { waitUntil: "networkidle" });
    await expect(page.getByText("T00", { exact: true })).toBeVisible();
    await expect(page.getByText(/automatically at 22:00 every day/i)).toBeVisible();
    await page.getByRole("button", { name: /Update Today's Recommendations Now/i }).click();

    await expect(page.getByRole("button", { name: /Updating recommendations/i })).toBeDisabled();
    await expect(page.getByText(/Scanning options/)).toBeVisible({ timeout: 8_000 });
    await expect(page.getByText(`Target session ${runDate}`, { exact: true })).toBeVisible();
    await expect(page.getByText("Progress 12/34")).toBeVisible();
    await expect(page.getByText("Elapsed 0s", { exact: true })).toBeVisible();
    await page.clock.fastForward(1_100);
    await expect(page.locator('[aria-live="off"]')).toHaveText(/Elapsed [1-9]\d*s/);
    await expect(page.getByText("T00", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Advanced data sources" }).click();
    await expect(page.getByRole("button", { name: "Refresh Earnings" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Refresh VIX" })).toBeDisabled();
    expect(runCalls).toBe(1);
    expect(statusCalls).toBeGreaterThan(1);
    await page.clock.fastForward(4_000);
    await expect(page.getByText("T01", { exact: true })).toBeVisible({ timeout: 8_000 });
    await expect(page.getByRole("button", { name: /Update Today's Recommendations Now/i })).toBeEnabled();
    expect(scanCalls).toBeGreaterThan(1);
  });

  test("an already-open page discovers a new scheduled completion and loads its target session", async ({ page }) => {
    let statusCalls = 0;
    const safety = {
      dry_run: true,
      paper_trading: true,
      live_trading_enabled: false,
      kill_switch: true,
      bind_address: "127.0.0.1",
    };
    await page.clock.install({ time: new Date("2026-08-25T13:59:00Z") });
    await page.route(/\/api\/options\/daily-scan(?:\?.*)?$/, async (route) => {
      const requestedDate = new URL(route.request().url()).searchParams.get("date");
      const isNewSession = requestedDate === runDate;
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          run_date: requestedDate ?? legacyDate,
          status: "available",
          provider: "futu",
          as_of: quoteAsOf,
          risk_free_rate: 0.0387,
          shortfall_count: 19,
          shortfall_reasons: { eligible_contracts_below_limit: 19 },
          universe_size: 34,
          scanned_tickers: 34,
          failed_tickers: [],
          is_stale: false,
          snapshot_age_days: 0,
          expired_candidate_count: 0,
          candidates: [apiRecommendation(isNewSession ? 1 : 0)],
          safety,
        }),
      });
    });
    await page.route("**/api/options/daily-scan/dates", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ dates: [runDate, legacyDate], safety }),
      });
    });
    await page.route("**/api/options/daily-scan/status", async (route) => {
      statusCalls += 1;
      const isNewTerminal = statusCalls > 1;
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          exists: true,
          status_path: "daily_task_status.json",
          status: {
            status: "completed",
            terminal: true,
            current_step: "completed",
            target_session: isNewTerminal ? runDate : legacyDate,
            trigger: "scheduled",
            started_at: isNewTerminal ? "2026-08-25T14:00:00Z" : "2026-08-24T14:00:00Z",
            finished_at: isNewTerminal ? "2026-08-25T14:01:00Z" : "2026-08-24T14:01:00Z",
            scanned_tickers: 34,
            total_tickers: 34,
          },
          safety,
        }),
      });
    });

    await page.goto(`/options-radar?date=${legacyDate}`, { waitUntil: "networkidle" });
    await expect(page.getByText("T00", { exact: true })).toBeVisible();
    expect(statusCalls).toBe(1);

    await page.clock.fastForward(60_000);

    await expect(page.getByText("T01", { exact: true })).toBeVisible();
    await expect(page.getByRole("combobox", { name: /Scan date/i })).toHaveValue(runDate);
    expect(statusCalls).toBeGreaterThan(1);
  });

  test("recommendations request Top 20 and never start an update during page load", async ({ page }) => {
    const requestedTops: string[] = [];
    let manualPostCount = 0;
    const safety = {
      dry_run: true,
      paper_trading: true,
      live_trading_enabled: false,
      kill_switch: true,
      bind_address: "127.0.0.1",
    };

    await page.route(/\/api\/options\/daily-scan(?:\?.*)?$/, async (route) => {
      const url = new URL(route.request().url());
      requestedTops.push(url.searchParams.get("top") ?? "");
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          run_date: runDate,
          status: "available",
          provider: "futu",
          as_of: quoteAsOf,
          risk_free_rate: 0.0387,
          shortfall_count: 0,
          shortfall_reasons: {},
          universe_size: 34,
          scanned_tickers: 34,
          failed_tickers: [],
          is_stale: false,
          snapshot_age_days: 0,
          expired_candidate_count: 0,
          candidates: Array.from({ length: 21 }, (_, index) => apiRecommendation(index)),
          safety,
        }),
      });
    });
    await page.route("**/api/options/daily-scan/dates", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ dates: [runDate], safety }),
      });
    });
    await page.route("**/api/options/daily-scan/status", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ exists: false, status_path: "", status: null, safety }),
      });
    });
    await page.route("**/api/options/daily-scan/run", async (route) => {
      manualPostCount += 1;
      await route.abort();
    });

    await page.goto(`/options-radar?date=${runDate}`, { waitUntil: "networkidle" });

    await expect(page.getByRole("heading", { name: "Options Recommendations" }).first()).toBeVisible();
    await expect(page.locator("tbody > tr")).toHaveCount(20);
    await expect(page.getByText("T19", { exact: true })).toBeVisible();
    await expect(page.getByText("T20", { exact: true })).toHaveCount(0);
    await expect(page.getByText(quoteAsOf, { exact: true })).toBeVisible();
    await expect(page.getByText("futu", { exact: true }).first()).toBeVisible();
    await expect(page.getByLabel("Top N")).toHaveCount(0);
    await expect(page.getByRole("link", { name: /Open Chain/i }).first()).toHaveAttribute(
      "href",
      /\/options-radar\/T00\?/,
    );
    expect(requestedTops.every((value) => value === "20")).toBe(true);
    await expect(page.getByRole("button", { name: /Update Today's Recommendations Now/i })).toBeEnabled();
    expect(manualPostCount).toBe(0);
    expect(requestedTops.every((value) => value === "20")).toBe(true);
  });

  test("options radar can drill into a symbol detail page", async ({ page }) => {
    await page.goto(`/options-radar/SPY?date=${runDate}&expiry=${expiry}&option_type=PUT`, {
      waitUntil: "domcontentloaded",
    });

    await expect(page.getByRole("heading", { name: /SPY Recommendation Detail/i })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Saved Recommendations", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText(`US.SPY${expiryCode}P450000`),
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: "Live Option Chain" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Load Live Chain/i })).toBeVisible();
  });

  test("legacy main snapshot offers one actionable update state", async ({ page }, testInfo) => {
    await page.goto(`/options-radar?date=${legacyDate}`, {
      waitUntil: "domcontentloaded",
    });

    await expect(page.getByText(/This is a legacy snapshot/)).toBeVisible();
    await expect(page.getByRole("button", { name: /Update Today's Recommendations Now/i })).toBeEnabled();
    await expect(page.getByText(/legacy_snapshot_contract/)).toHaveCount(0);
    await page.getByRole("button", { name: /View scan details/i }).click();
    await expect(page.getByText(/legacy snapshot format/i)).toBeVisible();
    await testInfo.attach("options-unavailable-desktop", {
      body: await page.screenshot({ fullPage: true }),
      contentType: "image/png",
    });
  });

  test("symbol detail surfaces unavailable provider and reason", async ({ page }, testInfo) => {
    await page.goto(`/options-radar/SPY?date=${legacyDate}`, {
      waitUntil: "domcontentloaded",
    });

    await expect(
      page.locator("[data-options-recommendation-unavailable] h2"),
    ).toHaveText("Saved recommendations unavailable");
    await expect(page.getByText(/Provider: futu/)).toBeVisible();
    await expect(page.getByText(/legacy_snapshot_contract: 1/)).toBeVisible();
    await expect(page.getByText("US.SPY", { exact: false })).toHaveCount(0);
    await testInfo.attach("symbol-unavailable-desktop", {
      body: await page.screenshot({ fullPage: true }),
      contentType: "image/png",
    });
  });
});
