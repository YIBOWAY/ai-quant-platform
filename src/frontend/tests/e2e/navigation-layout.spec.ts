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
  await expect(page.getByRole("link", { name: "Hermes", exact: true })).toBeVisible();
});

test("Chinese sidebar uses the same grouped information architecture", async ({ page }) => {
  await page.goto("/zh");
  await page.waitForLoadState("networkidle");

  await expect(page.getByText("研究流水线", { exact: true })).toBeVisible();
  await expect(page.getByText("期权研究", { exact: true })).toBeVisible();
  await expect(page.getByText("市场与 AI", { exact: true })).toBeVisible();
  await expect(page.getByText("系统", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Hermes 工作台", exact: true })).toBeVisible();
});

test("app shell keeps a fixed viewport with a scrollable page region inside", async ({ page }) => {
  await page.goto("/backtest");
  await page.waitForLoadState("networkidle");

  const layout = await page.evaluate(() => {
    const shell = document.body.querySelector(":scope > main");
    const shellStyle = shell ? window.getComputedStyle(shell) : null;
    const hasScrollRegion = shell
      ? Array.from(shell.querySelectorAll("*")).some((node) => {
          const overflowY = window.getComputedStyle(node).overflowY;
          return (
            (overflowY === "auto" || overflowY === "scroll") &&
            node.scrollHeight > node.clientHeight
          );
        })
      : false;
    return {
      shellPosition: shellStyle?.position ?? null,
      hasScrollRegion,
    };
  });

  expect(layout.shellPosition).not.toBe("fixed");
  expect(layout.hasScrollRegion).toBe(true);
});

test("mobile shell gives the page full width and exposes navigation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/position-map");
  await page.waitForLoadState("networkidle");

  await expect(page.getByTestId("desktop-sidebar")).toBeHidden();
  const shellBox = await page.locator("body > main").boundingBox();
  expect(shellBox?.x ?? 999).toBeLessThan(2);
  expect(shellBox?.width ?? 0).toBeGreaterThanOrEqual(389);

  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("link", { name: "Paper Trading", exact: true })).toBeVisible();
});

test("backtest defaults are a useful first research run", async ({ page }) => {
  await page.goto("/backtest");
  await page.waitForLoadState("networkidle");

  await expect(page.getByRole("combobox", { name: /Universe/ })).toHaveValue("etf");
  await expect(page.getByRole("textbox", { name: /Custom Symbols/ })).toHaveValue("");
  await expect(page.getByRole("combobox", { name: /Data Source/ })).toHaveValue("futu");
  await expect(page.getByRole("textbox", { name: /End/ })).toHaveValue(
    new Date().toISOString().slice(0, 10),
  );
  await expect(page.getByRole("spinbutton", { name: /Top N/ })).toHaveValue("3");
  await expect(page.getByText("Sector cap", { exact: true })).toHaveCount(0);
});
