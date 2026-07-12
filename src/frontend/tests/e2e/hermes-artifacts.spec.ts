import { expect, test } from "@playwright/test";

test.beforeEach(() => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");
});

test("Hermes renders all read-only artifact kinds and keeps Composer disabled", async ({
  page,
}) => {
  await page.goto("/zh/hermes");

  await expect(page.getByRole("heading", { name: "市场推演" })).toBeVisible();
  await expect(page.getByText("AAPL · flat", { exact: true })).toBeVisible();
  await expect(page.getByText("仅提案 · 待人工确认")).toBeVisible();

  await expect(page.getByRole("heading", { name: "预测 · AAPL" })).toBeVisible();
  await expect(page.getByText("up", { exact: true })).toBeVisible();
  await expect(page.getByText("结果收益", { exact: true })).toBeVisible();
  await expect(page.getByText("方向 Brier 分数", { exact: true })).toBeVisible();

  await expect(page.getByRole("heading", { name: "组合风险" })).toBeVisible();
  await expect(page.getByText("US$310.00", { exact: true })).toBeVisible();

  await expect(
    page.getByRole("textbox", { name: "Hermes 撰写区" }),
  ).toBeDisabled();
  await expect(page.getByRole("button", { name: /发送/ })).toBeDisabled();
});
