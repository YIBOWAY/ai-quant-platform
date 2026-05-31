import { expect, test } from "@playwright/test";

test.beforeEach(() => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");
});

test("locale toggle switches the visible shell without a manual reload", async ({ page }) => {
  await page.context().clearCookies();
  await page.goto("/");
  await page.waitForLoadState("networkidle");

  await expect(page.getByRole("link", { name: "Dashboard" })).toBeVisible();
  await page.getByRole("button", { name: "Switch to Chinese" }).click();

  await expect(page.getByRole("link", { name: "仪表盘" })).toBeVisible();
  await expect(page.getByRole("button", { name: "切换到英文" })).toBeVisible();
});
