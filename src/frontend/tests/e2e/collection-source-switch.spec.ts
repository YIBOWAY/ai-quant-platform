import { expect, test } from "@playwright/test";

test.beforeEach(() => {
  test.skip(process.env.PW_E2E !== "1", "Uses the isolated application backend.");
});

test("switching from multi-object template sources to a factor removes the previous sources", async ({ page }) => {
  await page.goto("/zh/collection");
  await page.getByRole("button", { name: /^策略模板/ }).click();
  await page.getByRole("button", { name: /^短期反转 \/ 长期动量 / }).click();
  const template = page.getByRole("article", { name: "详情 短期反转 / 长期动量", exact: true });
  await template.getByText("源码与原始记录", { exact: true }).click();
  await expect(template.getByText("build_reversal_momentum_replication", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: /^因子组件/ }).click();
  const factor = page.getByRole("article", { name: "详情 动量", exact: true });
  const sources = factor.locator("details").filter({ has: page.getByText("源码与原始记录", { exact: true }) });
  // The new detail may begin collapsed; only open it if it is not already open.
  if ((await sources.getAttribute("open")) === null) {
    await sources.getByText("源码与原始记录", { exact: true }).click();
  }
  await expect(factor.getByText("MomentumFactor", { exact: true })).toBeVisible();
  await expect(factor.getByText("build_reversal_momentum_replication", { exact: true })).toHaveCount(0);
  await expect(factor.getByText("_signal_frame", { exact: true })).toHaveCount(0);
  await expect(factor.getByText("_long_short_returns", { exact: true })).toHaveCount(0);
});
