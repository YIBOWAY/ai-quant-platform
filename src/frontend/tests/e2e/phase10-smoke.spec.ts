import { expect, test, type Page } from "@playwright/test";

test.beforeEach(() => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");
});

const routes = [
  "/",
  "/data-explorer",
  "/factor-lab",
  "/backtest",
  "/experiments",
  "/paper-trading",
  "/agent-studio",
  "/order-book",
  "/position-map",
  "/settings",
  "/options-screener?lang=zh",
];

for (const route of routes) {
  test(`route ${route} loads`, async ({ page }) => {
    await page.goto(route);
    await page.waitForLoadState("networkidle");
    await expect(page.locator("body")).toContainText(/paper-only/i);
  });
}

async function waitForEnabledButton(page: Page, name: string | RegExp) {
  await page.waitForLoadState("networkidle");
  const button = page.getByRole("button", { name });
  try {
    await expect(button).toBeVisible({ timeout: 5_000 });
    await expect(button).toBeEnabled({ timeout: 5_000 });
  } catch {
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle");
    await expect(button).toBeVisible({ timeout: 5_000 });
    await expect(button).toBeEnabled({ timeout: 5_000 });
  }
  return button;
}

async function clickAndWaitForPost(page: Page, buttonName: string, urlPart: string) {
  const button = await waitForEnabledButton(page, buttonName);
  const [response] = await Promise.all([
    page.waitForResponse(
      (candidate) => candidate.url().includes(urlPart) && candidate.request().method() === "POST",
      { timeout: 45_000 },
    ),
    button.click(),
  ]);
  return response;
}

async function expectRunIdVisible(page: Page, runId: string) {
  await page.waitForLoadState("networkidle");
  await expect(page.getByText(runId)).toBeVisible({ timeout: 45_000 });
}

// The replay form lives behind the "Historical Replay" tab; retry the click
// until hydration makes the tab respond (aria-selected flips client-side).
async function openTab(page: Page, name: string | RegExp) {
  const tab = page.getByRole("tab", { name });
  await expect(async () => {
    await tab.click();
    await expect(tab).toHaveAttribute("aria-selected", "true", { timeout: 1_000 });
  }).toPass({ timeout: 30_000 });
}

test("data explorer and backtest workflow buttons submit", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/data-explorer");
  await page.getByRole("button", { name: "Load" }).click();
  await expect(page).toHaveURL(/data-explorer/);

  await page.goto("/backtest");
  const backtestResponse = await clickAndWaitForPost(page, "Run Backtest", "/api/backtests/run");
  expect(backtestResponse.status()).toBe(200);
  const backtestPayload = (await backtestResponse.json()) as { run_id: string };
  await expectRunIdVisible(page, backtestPayload.run_id);
  await expect(page.getByText("Trade Blotter")).toBeVisible();
});

test("factor lab renders its research panels", async ({ page }) => {
  await page.goto("/factor-lab");
  await expect(page.getByRole("heading", { name: "Factor Lab" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Cross-Sectional Health" })).toBeVisible();
  await openTab(page, "Single-Ticker Timing");
  await expect(page.getByText("QQQ Timing Diagnostics")).toBeVisible();
  // The factor research form is mounted in the sidebar (previously dead code).
  await expect(page.getByRole("button", { name: "Run Factor" })).toBeVisible();
});

test("paper replay safety lock disables submit and shows safety copy", async ({ page }) => {
  await page.goto("/paper-trading");
  await openTab(page, "Historical Replay");
  const killSwitchButton = await waitForEnabledButton(page, "kill_switch enabled");
  await killSwitchButton.click();
  await expect(page.getByText(/the API will reject runs that disable it/i)).toBeVisible();
  await page.getByRole("button", { name: "Close" }).click();
  await expect(page.getByRole("button", { name: "Run Paper Trading" })).toBeDisabled();
});

test("agent task workflow submits and renders candidate details", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/agent-studio");
  const agentResponse = await clickAndWaitForPost(page, "Run task", "/api/agent/tasks");
  expect(agentResponse.status()).toBe(200);
  const agentPayload = (await agentResponse.json()) as { candidate_id: string };
  await expectRunIdVisible(page, agentPayload.candidate_id);
  await expect(page.getByRole("heading", { name: "Source Preview" })).toBeVisible();
});

test("prediction market workflow buttons submit", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/order-book");
  await page.getByLabel("Provider").first().selectOption("sample");
  expect((await clickAndWaitForPost(page, "Run scanner", "/api/prediction-market/scan")).status()).toBe(200);
  expect((await clickAndWaitForPost(page, "Generate dry arbitrage", "/api/prediction-market/dry-arbitrage")).status()).toBe(200);
  expect((await clickAndWaitForPost(page, "Run quasi-backtest", "/api/prediction-market/backtest")).status()).toBe(200);
  await expect(page.getByText("Opportunities")).toBeVisible();
  expect((await clickAndWaitForPost(page, "Collect snapshots", "/api/prediction-market/collect")).status()).toBe(200);
  const timeseriesResponse = await clickAndWaitForPost(
    page,
    "Run historical replay",
    "/api/prediction-market/timeseries-backtest",
  );
  expect(timeseriesResponse.status()).toBe(200);
  await expect(page.getByText("Historical Snapshot Replay")).toBeVisible();
  await expect(page.getByText("Estimated profit", { exact: true })).toBeVisible();
  await expect(page.getByAltText("Daily Opportunity Count")).toBeVisible();
});

test("options screener scans the DTE window without manual expiration selection", async ({ page }) => {
  test.setTimeout(90_000);

  await page.goto("/options-screener?lang=zh");
  await page.waitForLoadState("networkidle");
  await expect(page.locator('select[name="expiration"]')).toHaveCount(0);
  await expect(page.getByText("期权链预览")).toHaveCount(0);
  const responsePromise = page.waitForResponse(
    (response) => response.url().includes("/api/options/screener") && response.request().method() === "POST",
    { timeout: 45_000 },
  );
  await page.getByRole("button", { name: "开始分析" }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  await expect(page.getByText("扫描到期日")).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText("候选合约", { exact: true })).toBeVisible();
});

test("factor lab and strategy catalog render Chinese labels", async ({ page }) => {
  await page.goto("/zh/factor-lab");
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("heading", { name: "因子实验室" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "横截面体检" })).toBeVisible();

  await page.goto("/zh/replications");
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("heading", { name: "策略目录" })).toBeVisible();
  await expect(page.getByLabel("策略")).toBeVisible();
});
