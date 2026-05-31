import { expect, test } from "@playwright/test";

test.beforeEach(() => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");
});

test("locale toggle switches the visible shell without a manual reload", async ({ page }) => {
  await page.context().clearCookies();
  await page.goto("/en");
  await page.waitForLoadState("networkidle");

  await expect(page.getByRole("link", { name: "Dashboard" })).toBeVisible();
  await page.getByRole("link", { name: "切换到中文" }).click();

  await expect(page).toHaveURL(/\/zh$/);
  await expect(page.getByRole("link", { name: "仪表盘" })).toBeVisible();
  await expect(page.getByRole("link", { name: "切换到英文" })).toBeVisible();
});

test("locale-prefixed settings route renders Chinese shell", async ({ page }) => {
  await page.goto("/zh/settings", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("link", { name: "仪表盘" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "设置", exact: true })).toBeVisible();
});
