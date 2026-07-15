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

/**
 * Data-agnostic smoke against the isolated real temporary platform FastAPI
 * process. Never substitutes for combined-fixture candidate/approval assertions.
 */
test("@real-backend-smoke Hermes shell renders safety chrome and disabled composer", async ({
  page,
}) => {
  test.skip(
    Boolean(process.env.PW_HERMES_WORKBENCH_FIXTURE),
    "Real temporary-backend smoke must not use combined fixtures.",
  );

  const externalRequests = await installLoopbackOnlyGuard(page);
  await page.goto("/zh/hermes", { waitUntil: "networkidle" });

  await expect(page.getByTestId("global-safety-strip")).toHaveCount(1);
  await expect(page.getByRole("status").filter({ hasText: "仅模拟" })).toHaveCount(1);
  await expect(page.getByRole("navigation", { name: "Hermes 工作台" })).toBeVisible();
  await expect(page.getByRole("link", { name: "今日" })).toBeVisible();
  await expect(page.getByText("本交付未连接 Hermes 写入能力")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "和 Hermes 对话" })).toBeDisabled();
  expect(externalRequests).toEqual([]);
});

test("@real-backend-smoke Hermes sessions fail closed when the gateway is disabled", async ({
  page,
}) => {
  test.skip(
    Boolean(process.env.PW_HERMES_WORKBENCH_FIXTURE),
    "The temporary real backend owns this disabled-gateway contract.",
  );
  const externalRequests = await installLoopbackOnlyGuard(page);

  await page.goto("/zh/hermes/sessions", { waitUntil: "networkidle" });

  await expect(page.getByRole("heading", { name: "真实会话记录" })).toBeVisible();
  await expect(page.locator("[data-hermes-sessions-unavailable]")).toBeVisible();
  await expect(page.getByRole("link", { name: "会话记录" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "和 Hermes 对话" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "发送（已禁用）" })).toBeDisabled();
  expect(externalRequests).toEqual([]);
});

test("@live-hermes-sessions reads real persisted sessions without opening chat writes", async ({
  page,
}) => {
  test.skip(
    process.env.PW_HERMES_LIVE_SESSIONS !== "1",
    "Set PW_HERMES_LIVE_SESSIONS=1 with the local Hermes API Server and BFF enabled.",
  );
  const externalRequests = await installLoopbackOnlyGuard(page);

  await page.goto("/zh/hermes/sessions", { waitUntil: "networkidle" });

  await expect(page.locator("[data-hermes-sessions-unavailable]")).toHaveCount(0);
  await expect(page.getByText("只读已连接")).toBeVisible();
  const sessionLinks = page.locator("[data-hermes-session-list] a");
  expect(await sessionLinks.count()).toBeGreaterThan(0);
  await sessionLinks.first().click();
  await expect(page).toHaveURL(/\/zh\/hermes\/sessions\/[^/?#]+$/);
  await expect(
    page.locator("[data-hermes-session-messages], [data-hermes-session-empty]"),
  ).toHaveCount(1);
  await expect(page.getByRole("textbox", { name: "和 Hermes 对话" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "发送（已禁用）" })).toBeDisabled();
  expect(externalRequests).toEqual([]);
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

test("@combined-fixture F2 subroutes are truthful and mutation-free", async ({
  page,
}) => {
  const fixture = process.env.PW_HERMES_WORKBENCH_FIXTURE ?? "normal";
  const externalRequests = await installLoopbackOnlyGuard(page);

  await page.goto("/zh/hermes/tasks");
  await expect(page.getByRole("heading", { name: "任务" })).toBeVisible();
  await expect(page.getByText(/研究任务.*账本尚未接入|write ledger is not connected/i)).toBeVisible();
  await expect(page.locator("[data-hermes-tasks-write-ledger-banner]")).toBeVisible();
  // Platform evidence sections — still no research-task write mutation.
  if (fixture === "normal") {
    await expect(page.locator("[data-hermes-tasks-automation]")).toBeVisible();
    await expect(page.locator("[data-hermes-automation-summary]")).toBeVisible();
    await expect(page.locator("[data-hermes-tasks-weekly-review]")).toBeVisible();
    await expect(page.locator("[data-hermes-tasks-opportunity-summary]")).toBeVisible();
  }
  await expect(page.getByRole("button", { name: /创建|提交|Create|Submit/i })).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "和 Hermes 对话" })).toBeDisabled();

  await page.goto("/zh/hermes/approvals");
  await expect(page.getByRole("heading", { name: "待我确认" })).toBeVisible();
  await expect(page.getByText("研究审批项")).toBeVisible();
  // Digest-aware cards follow each combined fixture's candidate row (not a fixed id).
  if (fixture === "normal") {
    await expect(
      page.locator(
        '[data-hermes-approval-id="factor-momentum_20d_reversal-323b045e4b"]',
      ),
    ).toBeVisible();
    await expect(page.locator("code").filter({ hasText: "a".repeat(64) })).toBeVisible();
  } else if (fixture === "degraded") {
    await expect(
      page.locator('[data-hermes-approval-id="legacy-pending-migration"]'),
    ).toBeVisible();
    await expect(page.getByText("迁移证据，不能审批")).toBeVisible();
    await expect(page.locator("code").filter({ hasText: "b".repeat(64) })).toBeVisible();
  }
  // Browser Gate 2 stays hard-off for every fixture until HQA Gate 1 binding
  // and the same-origin session/CSRF BFF are delivered.
  await expect(page.getByText("网页审批写端已安全关闭")).toBeVisible();
  await expect(page.locator("[data-hermes-gate2-controls]")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /批准|拒绝/ })).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "和 Hermes 对话" })).toBeDisabled();

  await page.goto("/zh/hermes/results");
  await expect(page.getByRole("heading", { name: "结果" })).toBeVisible();
  await expect(page.getByText("只读结果索引")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "和 Hermes 对话" })).toBeDisabled();

  expect(externalRequests).toEqual([]);
});
