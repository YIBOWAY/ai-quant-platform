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
