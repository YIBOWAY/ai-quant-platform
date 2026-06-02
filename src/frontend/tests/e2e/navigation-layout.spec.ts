import { expect, test } from "@playwright/test";

test.beforeEach(() => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");
});

test("sidebar groups the product areas instead of showing one flat list", async ({ page }) => {
  await page.goto("/");
  await page.waitForLoadState("networkidle");

  await expect(page.getByText("Research Pipeline", { exact: true })).toBeVisible();
  await expect(page.getByText("Options Research", { exact: true })).toBeVisible();
  await expect(page.getByText("Markets & AI", { exact: true })).toBeVisible();
  await expect(page.getByText("System", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Backtester" })).toBeVisible();
});

test("Chinese sidebar uses the same grouped information architecture", async ({ page }) => {
  await page.goto("/zh");
  await page.waitForLoadState("networkidle");

  await expect(page.getByText("研究流水线", { exact: true })).toBeVisible();
  await expect(page.getByText("期权研究", { exact: true })).toBeVisible();
  await expect(page.getByText("市场与 AI", { exact: true })).toBeVisible();
  await expect(page.getByText("系统", { exact: true })).toBeVisible();
});

test("app shell allows page-level scrolling instead of locking the viewport", async ({ page }) => {
  await page.goto("/backtest");
  await page.waitForLoadState("networkidle");

  const layout = await page.evaluate(() => {
    const shell = document.body.querySelector(":scope > main");
    const bodyStyle = window.getComputedStyle(document.body);
    const shellStyle = shell ? window.getComputedStyle(shell) : null;
    return {
      bodyOverflowY: bodyStyle.overflowY,
      shellPosition: shellStyle?.position ?? null,
      shellOverflowY: shellStyle?.overflowY ?? null,
    };
  });

  expect(layout.bodyOverflowY).not.toBe("hidden");
  expect(layout.shellPosition).not.toBe("fixed");
  expect(layout.shellOverflowY).not.toBe("hidden");
});

test("backtest defaults are a useful first research run", async ({ page }) => {
  await page.goto("/backtest");
  await page.waitForLoadState("networkidle");

  await expect(page.getByRole("combobox", { name: /Universe/ })).toHaveValue("etf");
  await expect(page.getByRole("textbox", { name: /Custom Symbols/ })).toHaveValue("");
  await expect(page.getByRole("combobox", { name: /Data Source/ })).toHaveValue("sample");
  await expect(page.getByRole("textbox", { name: /End/ })).toHaveValue("2024-06-28");
  await expect(page.getByRole("spinbutton", { name: /Top N/ })).toHaveValue("3");
});
