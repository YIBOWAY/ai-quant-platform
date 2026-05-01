import { expect, test, type Page } from "@playwright/test";

test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");

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
];

for (const route of routes) {
  test(`route ${route} loads`, async ({ page }) => {
    await page.goto(route);
    await expect(page.locator("body")).toContainText(/paper-only/i);
  });
}

async function waitForEnabledButton(page: Page, name: string | RegExp) {
  const button = page.getByRole("button", { name });
  try {
    await expect(button).toBeEnabled({ timeout: 5_000 });
  } catch {
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(button).toBeEnabled({ timeout: 5_000 });
  }
  return button;
}

async function clickAndWaitForPost(page: Page, buttonName: string, urlPart: string) {
  const button = await waitForEnabledButton(page, buttonName);
  await page.waitForTimeout(2_000);
  const responsePromise = page.waitForResponse(
    (response) => response.url().includes(urlPart) && response.request().method() === "POST",
    { timeout: 15_000 },
  );
  await button.click();
  return responsePromise;
}

test("primary local workflow buttons are clickable", async ({ page }) => {
  test.setTimeout(120_000);

  await page.goto("/data-explorer");
  await page.getByRole("button", { name: "Load" }).click();
  await expect(page).toHaveURL(/data-explorer/);

  await page.goto("/backtest");
  expect((await clickAndWaitForPost(page, "Run Backtest", "/api/backtests/run")).status()).toBe(200);

  await page.goto("/factor-lab");
  await page.waitForTimeout(3_000);
  await page.getByRole("textbox", { name: "Symbols", exact: true }).fill("SPY,QQQ");
  await page.getByRole("textbox", { name: "Start", exact: true }).fill("2024-01-02");
  await page.getByRole("textbox", { name: "End", exact: true }).fill("2024-02-15");
  await page.getByRole("spinbutton", { name: "Lookback" }).fill("5");
  await page.getByRole("spinbutton", { name: "Quantiles" }).fill("5");
  expect((await clickAndWaitForPost(page, "Run Factor", "/api/factors/run")).status()).toBe(200);

  await page.goto("/paper-trading");
  const killSwitchButton = await waitForEnabledButton(page, "kill_switch enabled");
  await killSwitchButton.click();
  await expect(page.getByText(/the API will reject runs that disable it/i)).toBeVisible();
  await page.getByRole("button", { name: "Close" }).click();
  expect((await clickAndWaitForPost(page, "Run Paper Trading", "/api/paper/run")).status()).toBe(200);

  await page.goto("/agent-studio");
  expect((await clickAndWaitForPost(page, "Run task", "/api/agent/tasks")).status()).toBe(200);

  await page.goto("/order-book");
  await page.getByLabel("Provider").selectOption("sample");
  expect((await clickAndWaitForPost(page, "Run scanner", "/api/prediction-market/scan")).status()).toBe(200);
  expect((await clickAndWaitForPost(page, "Generate dry arbitrage", "/api/prediction-market/dry-arbitrage")).status()).toBe(200);
  expect((await clickAndWaitForPost(page, "Run quasi-backtest", "/api/prediction-market/backtest")).status()).toBe(200);
  await expect(page.getByText("Opportunities")).toBeVisible();
});
