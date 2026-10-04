import { expect, test, type Page } from "@playwright/test";
import {
  assertFullPageTargetsAndFocus,
  assertNoHorizontalOverflow,
  assertReducedMotion,
  installLoopbackOnlyGuard,
} from "./helpers/hermes-page-gates";

test.beforeEach(() => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");
});

async function openLongestPersistedSession(page: Page) {
  const sessionRows = page.locator("[data-hermes-session-list] li");
  expect(await sessionRows.count()).toBeGreaterThan(0);
  const targetIndex = await sessionRows.evaluateAll((rows) => {
    let bestIndex = 0;
    let bestCount = -1;
    rows.forEach((row, index) => {
      const count = Number(
        (row as HTMLElement).dataset.hermesSessionMessageCount ?? "0",
      );
      if (count > bestCount) {
        bestIndex = index;
        bestCount = count;
      }
    });
    return bestIndex;
  });
  await sessionRows.nth(targetIndex).getByRole("link").click();
}

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
  await expect(page.getByTestId("global-safety-strip")).toContainText("仅模拟");
  await expect(page.getByRole("tablist", { name: "研究与运行" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "今日", exact: true })).toBeVisible();
  await expect(page.getByText("Hermes 对话当前不可用")).toBeVisible();
  await expect(page.locator("#hermes-chat-rail textarea:not([disabled])")).toHaveCount(0);
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

  await page.goto("/zh/hermes", { waitUntil: "domcontentloaded" });

  await page.locator("[data-hermes-recent-sessions]").evaluate((node) => {
    (node as HTMLDetailsElement).open = true;
  });
  await expect(page.getByText("会话列表暂不可用", { exact: true })).toBeVisible();
  await expect(page.locator("#hermes-chat-rail textarea:not([disabled])")).toHaveCount(0);
  await expect(page.locator("#hermes-chat-rail").getByRole("button", { name: /^发送/, disabled: false })).toHaveCount(0);
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

  await page.goto("/zh/hermes", { waitUntil: "domcontentloaded" });
  await page.locator("[data-hermes-recent-sessions]").evaluate((node) => {
    (node as HTMLDetailsElement).open = true;
  });

  await expect(page.getByText("会话列表暂不可用", { exact: true })).toHaveCount(0);
  await openLongestPersistedSession(page);
  await expect(page).toHaveURL(/\/zh\/hermes\/sessions\/[^/?#]+$/);
  await expect(
    page.locator("[data-hermes-session-messages], [data-hermes-session-empty]"),
  ).toHaveCount(1);
  const sessionScrollRegion = page.locator("[data-hermes-desk] > .dp-main");
  const latestMessageAnchor = page.locator("[data-hermes-session-latest-anchor]");
  await expect(latestMessageAnchor).toBeInViewport();
  await expect
    .poll(() => sessionScrollRegion.evaluate((element) => element.scrollTop))
    .toBeGreaterThan(0);
  await expect(page.locator("#hermes-chat-rail textarea:not([disabled])")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /^发送(?:（已禁用）)?$/ }),
  ).toBeDisabled();
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

  await page.goto("/zh/hermes", { waitUntil: "domcontentloaded" });
  await page.locator("[data-hermes-recent-sessions]").evaluate((node) => {
    (node as HTMLDetailsElement).open = true;
  });
  await openLongestPersistedSession(page);
  await expect(page.locator("[data-hermes-session-latest-anchor]")).toBeInViewport();

  const scrollRegion = page.locator("[data-hermes-desk] > .dp-main");
  const sessionContext = page.locator("[data-hermes-session-context]");
  await expect(sessionContext).toBeVisible();
  await expect(page.getByRole("link", { name: "← 返回 Hermes 助手" })).toBeVisible();

  const regionBox = await scrollRegion.boundingBox();
  const pinnedBox = await sessionContext.boundingBox();
  expect(regionBox).not.toBeNull();
  expect(pinnedBox).not.toBeNull();
  const inset = await scrollRegion.evaluate(el => Number.parseFloat(getComputedStyle(el).paddingTop));
  expect(Math.abs(pinnedBox!.y - regionBox!.y - inset)).toBeLessThanOrEqual(1);

  await scrollRegion.evaluate((element) => {
    element.scrollTop = Math.max(1, element.scrollTop - 400);
  });
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
  const pinnedAfterScroll = await sessionContext.boundingBox();
  expect(pinnedAfterScroll).not.toBeNull();
  expect(Math.abs(pinnedAfterScroll!.y - pinnedBox!.y)).toBeLessThanOrEqual(1);

  await page.getByRole("link", { name: "← 返回 Hermes 助手" }).click();
  await expect(page).toHaveURL(/\/zh\/hermes$/);
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

  await page.goto("/zh/hermes", { waitUntil: "networkidle" });
  await page.locator("[data-hermes-recent-sessions]").evaluate((node) => {
    (node as HTMLDetailsElement).open = true;
  });
  await page.getByRole("link", { name: "Fixture long session" }).click();
  await expect(page).toHaveURL(/\/zh\/hermes\?hermes_session_id=fixture-long-session$/);
  await expect(page.getByText("Latest fixture message")).toBeInViewport();
  await expect(page.locator("#hermes-chat-rail textarea:not([disabled])")).toHaveCount(0);
  // The retained permalink still owns pinned context and historical forking.
  await page.goto("/zh/hermes/sessions/fixture-long-session", { waitUntil: "networkidle" });
  await expect(page.getByText("Latest fixture message")).toBeInViewport();

  const scrollRegion = page.locator("[data-hermes-desk] > .dp-main");
  const sessionContext = page.locator("[data-hermes-session-context]");
  await expect(page.locator("[data-hermes-session-latest-anchor]")).toBeInViewport();
  await expect
    .poll(() => scrollRegion.evaluate((element) => element.scrollTop))
    .toBeGreaterThan(0);

  const regionBox = await scrollRegion.boundingBox();
  const pinnedBox = await sessionContext.boundingBox();
  expect(regionBox).not.toBeNull();
  expect(pinnedBox).not.toBeNull();
  const inset = await scrollRegion.evaluate(el => Number.parseFloat(getComputedStyle(el).paddingTop));
  expect(Math.abs(pinnedBox!.y - regionBox!.y - inset)).toBeLessThanOrEqual(1);

  await scrollRegion.evaluate((element) => {
    element.scrollTop = Math.max(1, element.scrollTop - 400);
  });
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
  const pinnedAfterScroll = await sessionContext.boundingBox();
  expect(pinnedAfterScroll).not.toBeNull();
  expect(Math.abs(pinnedAfterScroll!.y - pinnedBox!.y)).toBeLessThanOrEqual(1);

  await page.getByRole("link", { name: "← 返回 Hermes 助手" }).click();
  await expect(page).toHaveURL(/\/zh\/hermes$/);
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
  const backLink = page.getByRole("link", { name: "← 返回 Hermes 助手" });
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
  await expect(page.getByTestId("global-safety-strip")).toContainText("仅模拟");
  await expect(
    page.locator("main").getByText("仅模拟 · 不存在实盘路径", { exact: true }),
  ).toHaveCount(0);
  await expect(page.locator("main [data-global-safety-strip]")).toHaveCount(0);
  await expect(page.getByRole("tablist", { name: "研究与运行" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "今日", exact: true })).toBeVisible();
  await expect(page.getByText(process.env.PW_HERMES_WORKBENCH_FIXTURE === "offline" ? "Hermes 对话当前不可用" : "当前为只读模式", { exact: true })).toBeVisible();
  await expect(page.getByTestId("hermes-capability-notice")).toHaveAttribute(
    "data-delivery-state",
    "blocked_in_this_slice",
  );
  await expect(page.locator("#hermes-chat-rail textarea:not([disabled])")).toHaveCount(0);
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

  await expect(page.locator("#hermes-ledger-panel")).toBeVisible();
  await expect(page.locator("[data-hermes-automation-summary]")).toHaveCount(1);
  await expect(page.locator("#hermes-chat-rail textarea:not([disabled])")).toHaveCount(0);
  await expect(page.getByTestId("global-safety-strip")).toHaveCount(1);

  await page.locator("summary").filter({ hasText: "运行记录与诊断" }).click();

  if (fixture === "normal") {
    await expect(page.getByText("自动化 4/4 正常")).toBeVisible();
    await expect(page.getByText("研究审批项")).toHaveCount(0);
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

test("@combined-fixture retained deep subroutes are truthful and mutation-free", async ({
  page,
}) => {
  const externalRequests = await installLoopbackOnlyGuard(page);

  await page.goto("/zh/hermes/results");
  await expect(page.getByRole("heading", { name: "统一结果" })).toBeVisible();
  const source = await page.request.get("/api/hermes/results");
  const catalog = await source.json();
  if (catalog.read_status === "unavailable") {
    await expect(page.locator("[data-hermes-results-unavailable]")).toBeVisible();
    await expect(page.getByText("当前无法判断是否存在结果；这不是空目录。")).toBeVisible();
  } else if (catalog.items.length === 0) {
    await expect(page.locator("[data-hermes-results-empty]")).toBeVisible();
  } else {
    await expect(page.locator("[data-hermes-result-key]")).toHaveCount(catalog.items.length);
    for (const item of catalog.items) await expect(page.locator(`a[href="/zh/hermes/results/${item.kind}/${encodeURIComponent(item.resource_id)}"]`)).toBeVisible();
    const first = catalog.items[0];
    await page.locator(`a[href="/zh/hermes/results/${first.kind}/${encodeURIComponent(first.resource_id)}"]`).click();
    await expect(page.locator("[data-hermes-result-resource]")).toBeVisible();
    const resource = JSON.parse(await page.locator("[data-hermes-result-resource]").innerText());
    expect(resource.id).toBe(first.resource_id); expect(resource.kind).toBe(first.kind);
    await expect(page.getByTestId("hermes-capability-notice")).toHaveAttribute("data-read-state", "available");
    await expect(page.getByText("当前为只读模式", { exact: true })).toBeVisible();
  }
  await expect(page.locator("#hermes-chat-rail textarea:not([disabled])")).toHaveCount(0);

  expect(externalRequests).toEqual([]);
});
