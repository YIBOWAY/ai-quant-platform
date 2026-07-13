import { expect, test } from "@playwright/test";

test.beforeEach(() => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");
});

test("locale toggle preserves query and hash on Hermes", async ({ page }) => {
  await page.context().clearCookies();
  await page.goto("/en/hermes?source=bookmark&tag=a&tag=b#approval");
  await page.waitForLoadState("networkidle");

  await expect(page.getByRole("link", { name: "Hermes", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "切换到中文" }).click();

  await expect(page).toHaveURL(
    /\/zh\/hermes\?source=bookmark&tag=a&tag=b#approval$/,
  );
  await expect(page.getByRole("link", { name: "Hermes 工作台", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "切换到英文" })).toBeVisible();
});

test("locale-prefixed settings route renders Chinese shell", async ({ page }) => {
  await page.goto("/zh/settings", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("link", { name: "Hermes 工作台", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "设置", exact: true })).toBeVisible();
});

test("prediction-market controls keep the active Chinese route", async ({ page }) => {
  await page.goto("/zh/polymarket?provider=sample", { waitUntil: "domcontentloaded" });

  await page.getByRole("button", { name: "加载市场" }).click();

  await expect(page).toHaveURL(/\/zh\/polymarket\?/);
});
