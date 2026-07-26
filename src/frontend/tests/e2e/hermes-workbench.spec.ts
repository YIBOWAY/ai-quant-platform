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
  await expect(page.getByText("Hermes 对话当前不可用")).toBeVisible();
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
  const sessionScrollRegion = page.locator("[data-page-scroll-region]");
  const latestMessageAnchor = page.locator("[data-hermes-session-latest-anchor]");
  await expect(latestMessageAnchor).toBeInViewport();
  await expect
    .poll(() => sessionScrollRegion.evaluate((element) => element.scrollTop))
    .toBeGreaterThan(0);
  await expect(page.getByRole("textbox", { name: "和 Hermes 对话" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "发送（已禁用）" })).toBeDisabled();
  expect(externalRequests).toEqual([]);
});

test("@live-hermes-sessions keeps session context pinned while reading the latest messages", async ({
  page,
}) => {
  test.skip(
    process.env.PW_HERMES_LIVE_SESSIONS !== "1",
    "Set PW_HERMES_LIVE_SESSIONS=1 with the local Hermes API Server and BFF enabled.",
  );
  const externalRequests = await installLoopbackOnlyGuard(page);

  await page.goto("/zh/hermes/sessions", { waitUntil: "networkidle" });
  const sessionLinks = page.locator("[data-hermes-session-list] a");
  expect(await sessionLinks.count()).toBeGreaterThan(0);
  await sessionLinks.first().click();
  await expect(page.locator("[data-hermes-session-latest-anchor]")).toBeInViewport();

  const scrollRegion = page.locator("[data-page-scroll-region]");
  const sessionContext = page.locator("[data-hermes-session-context]");
  await expect(sessionContext).toBeVisible();
  await expect(page.getByRole("link", { name: "← 返回会话记录" })).toBeVisible();

  const regionBox = await scrollRegion.boundingBox();
  const pinnedBox = await sessionContext.boundingBox();
  expect(regionBox).not.toBeNull();
  expect(pinnedBox).not.toBeNull();
  expect(Math.abs(pinnedBox!.y - regionBox!.y)).toBeLessThanOrEqual(1);

  await scrollRegion.evaluate((element) => {
    element.scrollTop = Math.max(1, element.scrollTop - 400);
  });
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
  const pinnedAfterScroll = await sessionContext.boundingBox();
  expect(pinnedAfterScroll).not.toBeNull();
  expect(Math.abs(pinnedAfterScroll!.y - regionBox!.y)).toBeLessThanOrEqual(1);

  await page.getByRole("link", { name: "← 返回会话记录" }).click();
  await expect(page).toHaveURL(/\/zh\/hermes\/sessions$/);
  expect(externalRequests).toEqual([]);
});

test("@combined-fixture opens a persisted transcript at its latest message with pinned context", async ({
  page,
}) => {
  test.skip(
    process.env.PW_HERMES_WORKBENCH_FIXTURE !== "normal",
    "The deterministic long session belongs to the normal combined fixture.",
  );
  const externalRequests = await installLoopbackOnlyGuard(page);

  await page.goto("/zh/hermes/sessions", { waitUntil: "networkidle" });
  await page.getByRole("link", { name: "Fixture long session" }).click();
  await expect(page).toHaveURL(/\/zh\/hermes\/sessions\/fixture-long-session$/);
  await expect(page.getByText("Latest fixture message")).toBeInViewport();

  const scrollRegion = page.locator("[data-page-scroll-region]");
  const sessionContext = page.locator("[data-hermes-session-context]");
  await expect(page.locator("[data-hermes-session-latest-anchor]")).toBeInViewport();
  await expect
    .poll(() => scrollRegion.evaluate((element) => element.scrollTop))
    .toBeGreaterThan(0);

  const regionBox = await scrollRegion.boundingBox();
  const pinnedBox = await sessionContext.boundingBox();
  expect(regionBox).not.toBeNull();
  expect(pinnedBox).not.toBeNull();
  expect(Math.abs(pinnedBox!.y - regionBox!.y)).toBeLessThanOrEqual(1);

  await scrollRegion.evaluate((element) => {
    element.scrollTop = Math.max(1, element.scrollTop - 400);
  });
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
  const pinnedAfterScroll = await sessionContext.boundingBox();
  expect(pinnedAfterScroll).not.toBeNull();
  expect(Math.abs(pinnedAfterScroll!.y - regionBox!.y)).toBeLessThanOrEqual(1);

  await page.getByRole("link", { name: "← 返回会话记录" }).click();
  await expect(page).toHaveURL(/\/zh\/hermes\/sessions$/);
  expect(externalRequests).toEqual([]);
});

test("@combined-fixture exposes a 44px return target on persisted transcripts", async ({
  page,
}) => {
  test.skip(
    process.env.PW_HERMES_WORKBENCH_FIXTURE !== "normal",
    "The deterministic persisted session belongs to the normal combined fixture.",
  );
  const externalRequests = await installLoopbackOnlyGuard(page);

  await page.goto("/zh/hermes/sessions/fixture-long-session", {
    waitUntil: "networkidle",
  });
  const backLink = page.getByRole("link", { name: "← 返回会话记录" });
  await expect(backLink).toBeVisible();
  const backLinkBox = await backLink.boundingBox();
  expect(backLinkBox).not.toBeNull();
  expect(backLinkBox!.height).toBeGreaterThanOrEqual(44);
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
  await expect(page.getByText("Hermes 对话当前不可用")).toBeVisible();
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
  await expect(page.getByRole("heading", { name: "统一结果" })).toBeVisible();
  // The combined fixture does not invent a unified result catalog. Its missing
  // GET route must remain an explicit unavailable state, never a false empty list.
  await expect(page.locator("[data-hermes-results-unavailable]")).toBeVisible();
  await expect(page.getByText("当前无法判断是否存在结果；这不是空目录。")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "和 Hermes 对话" })).toBeDisabled();

  expect(externalRequests).toEqual([]);
});

test("@combined-fixture Hermes Approvals navigates complete GET-only candidate evidence", async ({
  page,
}) => {
  const fixture = process.env.PW_HERMES_WORKBENCH_FIXTURE ?? "normal";
  test.skip(
    !["normal", "degraded"].includes(fixture),
    "Candidate detail evidence requires a fixture with one persisted candidate.",
  );
  const externalRequests = await installLoopbackOnlyGuard(page);
  const candidateMutationRequests: string[] = [];
  page.on("request", (request) => {
    if (
      request.url().includes("/api/agent/") &&
      !["GET", "HEAD", "OPTIONS"].includes(request.method())
    ) {
      candidateMutationRequests.push(`${request.method()} ${request.url()}`);
    }
  });
  const candidateId =
    fixture === "normal"
      ? "factor-momentum_20d_reversal-323b045e4b"
      : "legacy-pending-migration";

  await page.goto(
    `/zh/hermes/approvals?candidate=${encodeURIComponent(candidateId)}`,
    { waitUntil: "networkidle" },
  );

  await expect(page).toHaveURL(
    new RegExp(`/zh/hermes/approvals\\?candidate=${candidateId}$`),
  );
  await expect(
    page.locator(`[data-hermes-selected-candidate="${candidateId}"]`),
  ).toBeVisible();
  await expect(
    page.locator(`[data-hermes-approval-id="${candidateId}"] a[aria-current="page"]`),
  ).toBeVisible();
  await expect(page.locator("[data-hermes-candidate-metadata]")).toContainText(
    "artifact_type",
  );
  await expect(page.getByRole("heading", { name: "审计事件" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "复核事件" })).toBeVisible();

  if (fixture === "normal") {
    await expect(page.locator("[data-hermes-promoted-registry]")).toBeVisible();
    await expect(page.locator("[data-hermes-promoted-registry]")).toContainText(
      "2 已注册 · 1 已晋升",
    );
    await expect(
      page.locator(
        '[data-hermes-promoted-factor-id="agent_candidate_wave2_sceneb_mom20_v3"]',
      ),
    ).toBeVisible();
    await expect(
      page.locator("[data-hermes-promoted-registry-unavailable]"),
    ).toHaveCount(0);
    await expect(page.getByText("权威 manifest digest")).toBeVisible();
    await expect(page.getByText("平台可 review · 不代表 HQA Gate 2")).toBeVisible();
    await expect(page.locator("[data-hermes-candidate-source]")).toContainText(
      "fixture_factor",
    );
    await expect(page.locator('[data-hermes-candidate-events="audit"]')).toHaveCount(0);
    await expect(
      page.getByText("暂无与该 digest 精确绑定的审计证据；全局与旧版未绑定日志已主动排除。"),
    ).toBeVisible();

    const approvedId = "factor-quality-approved-7d34f0a12c";
    await page
      .locator(`[data-hermes-approval-id="${approvedId}"] a`)
      .click();
    await expect(page).toHaveURL(
      new RegExp(`/zh/hermes/approvals\\?candidate=${approvedId}$`),
    );
    await expect(
      page.locator(`[data-hermes-selected-candidate="${approvedId}"]`),
    ).toBeVisible();
    await expect(page.getByText("平台不可 review")).toBeVisible();
    await expect(page.locator('[data-hermes-candidate-events="review"]')).toContainText(
      "fixture review",
    );

    await page.goto("/zh/hermes/approvals?candidate=candidate-not-in-index", {
      waitUntil: "networkidle",
    });
    await expect(page.locator("[data-hermes-candidate-detail-unavailable]")).toBeVisible();
  } else {
    await expect(
      page.locator("[data-hermes-promoted-registry-unavailable]"),
    ).toBeVisible();
    await expect(page.getByText("当前无法核验因子目录；这不代表已晋升注册表为空。")).toBeVisible();
    await expect(page.getByText("503: fixture_factor_registry_unavailable")).toBeVisible();
    await expect(page.locator("[data-hermes-promoted-registry]")).toHaveCount(0);
    await expect(page.locator("[data-hermes-promoted-factor-list]")).toHaveCount(0);
    await expect(page.getByText("仅为迁移证据，不能审批")).toBeVisible();
    await expect(page.getByText("平台不可 review")).toBeVisible();
  }

  await expect(page.locator("[data-hermes-gate2-controls]")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /批准|拒绝/ })).toHaveCount(0);
  await expect(page.locator("[data-hermes-approvals] form")).toHaveCount(0);
  expect(candidateMutationRequests).toEqual([]);
  expect(externalRequests).toEqual([]);
});
