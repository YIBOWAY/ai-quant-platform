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

  const prediction = page.getByRole("article", { name: "预测 · AAPL" });
  await expect(prediction.getByRole("heading", { name: "预测 · AAPL" })).toBeVisible();
  await expect(prediction.getByText("up", { exact: true })).toBeVisible();
  await expect(prediction.getByText("结果收益", { exact: true })).toBeVisible();
  await expect(prediction.getByText("方向 Brier 分数", { exact: true })).toBeVisible();

  await expect(page.getByRole("heading", { name: "组合风险" })).toBeVisible();
  await expect(page.getByText("US$310.00", { exact: true })).toBeVisible();

  await expect(
    page.getByRole("heading", { name: "周报复盘 · 2026-W27" }),
  ).toBeVisible();
  await expect(page.getByText("暂无已评分预测", { exact: true })).toBeVisible();

  await expect(page.getByRole("heading", { name: "机会复盘" })).toBeVisible();
  await expect(page.getByText("错过机会", { exact: true }).first()).toBeVisible();

  // F2 compresses automation into AutomationSummary (not a full "自动化状态" card).
  await expect(page.locator("[data-hermes-automation-summary]")).toBeVisible();
  await expect(page.getByText("自动化 0/4 正常", { exact: true })).toBeVisible();
  await expect(page.getByText("已降级 · 需要检查", { exact: true })).toBeVisible();
  await expect(page.getByText("从未运行", { exact: true }).first()).toBeVisible();

  await expect(
    page.getByRole("textbox", { name: "和 Hermes 对话" }),
  ).toBeDisabled();
  await expect(page.getByRole("button", { name: /发送/ })).toBeDisabled();
});
