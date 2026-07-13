import { expect, test } from "@playwright/test";
import {
  assertFullPageTargetsAndFocus,
  assertNoHorizontalOverflow,
  assertReducedMotion,
  installLoopbackOnlyGuard,
} from "./helpers/hermes-page-gates";

test.beforeEach(() => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");
});

test("@combined-fixture Hermes workbench shell keeps a single safety strip and disabled composer", async ({
  page,
}) => {
  const externalRequests = await installLoopbackOnlyGuard(page);
  await page.goto("/zh/hermes");

  await expect(page.getByTestId("global-safety-strip")).toHaveCount(1);
  await expect(page.getByRole("status").filter({ hasText: "仅模拟" })).toHaveCount(1);
  await expect(
    page.locator("main").getByText("仅模拟 · 不存在实盘路径", { exact: true }),
  ).toHaveCount(0);
  await expect(page.locator("main [data-global-safety-strip]")).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "Hermes 工作台" })).toBeVisible();
  await expect(page.getByRole("link", { name: "今日" })).toBeVisible();
  await expect(page.getByText("本交付未连接 Hermes 写入能力")).toBeVisible();
  await expect(page.getByTestId("hermes-capability-notice")).toHaveAttribute(
    "data-delivery-state",
    "blocked_in_this_slice",
  );
  await expect(page.getByRole("textbox", { name: "和 Hermes 对话" })).toBeDisabled();
  await assertFullPageTargetsAndFocus(page);
  await assertReducedMotion(page);
  await assertNoHorizontalOverflow(page, page.viewportSize()!.width);
  expect(externalRequests).toEqual([]);
});

test("@combined-fixture Hermes Today hierarchy matches the active combined fixture", async ({
  page,
}) => {
  const fixture = process.env.PW_HERMES_WORKBENCH_FIXTURE ?? "normal";
  const externalRequests = await installLoopbackOnlyGuard(page);
  await page.goto("/zh/hermes");

  await expect(page.locator("[data-hermes-today]")).toBeVisible();
  await expect(page.locator("[data-hermes-automation-summary]")).toHaveCount(1);
  await expect(page.getByRole("textbox", { name: "和 Hermes 对话" })).toBeDisabled();
  await expect(page.getByTestId("global-safety-strip")).toHaveCount(1);

  if (fixture === "normal") {
    await expect(page.getByText("自动化 4/4 正常")).toBeVisible();
    await expect(page.getByText("研究审批项")).toBeVisible();
    await expect(
      page.locator(
        '[data-hermes-attention-id="factor-momentum_20d_reversal-323b045e4b"]',
      ),
    ).toBeVisible();
    await expect(page.locator("[data-hermes-automation-exception]")).toHaveCount(0);
  } else if (fixture === "degraded") {
    await expect(page.getByText("自动化 3/4 正常")).toBeVisible();
    await expect(page.locator("[data-hermes-automation-exception]")).toHaveCount(1);
    await expect(page.locator('[data-hermes-automation-exception="weekly"]')).toBeVisible();
    await expect(
      page.locator('[data-hermes-automation-exception="weekly"] details[open]'),
    ).toHaveCount(1);
  }

  expect(externalRequests).toEqual([]);
});
