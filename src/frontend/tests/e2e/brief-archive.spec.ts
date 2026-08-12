import { expect, test } from "@playwright/test";

test.beforeEach(() => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");
});

// /brief is an RSC: getLatestBriefIssue / getAiHotItems run on the Next server against
// NEXT_PUBLIC_QUANT_API_BASE_URL. Playwright page.route never sees those SSR fetches, so
// this suite asserts the hermetic empty-DB path that playwright.config forces
// (QS_DATABASE_ENABLED=false, no aihot seed). Positive seeded-archive coverage belongs
// in API/unit tests or a future backend seed helper — not a browser route mock.
test("brief empty archive DB shows no manual save control and shows empty digest", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/zh/brief?range=7d");
  await expect(page.getByRole("heading", { name: "每日晨报" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "日涨跌" })).toBeVisible();

  await expect(page.getByRole("link", { name: "近 7 日" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(page.getByRole("link", { name: "近一月" })).toBeVisible();
  await expect(page.getByRole("link", { name: "近三月" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);

  const backendPort = process.env.PW_BACKEND_PORT ?? "8765";
  const performanceResponse = await page.request.get(
    `http://127.0.0.1:${backendPort}/api/paper/account/performance?range=7d&granularity=1d&benchmarks=SPY%2CQQQ`,
  );
  expect(performanceResponse.status()).toBe(200);
  const performance = await performanceResponse.json();
  expect(performance.series.map((series: { id: string }) => series.id)).toEqual([
    "paper",
    "SPY",
    "QQQ",
  ]);
  await page.screenshot({
    path: testInfo.outputPath("brief-desktop-1440.png"),
    fullPage: true,
  });
  const desktopPerformanceSection = page
    .getByRole("heading", { name: "模拟盘收益" })
    .locator("xpath=ancestor::section[1]");
  await desktopPerformanceSection.scrollIntoViewIfNeeded();
  await desktopPerformanceSection.screenshot({
    path: testInfo.outputPath("brief-performance-desktop-1440.png"),
  });

  await page.getByRole("link", { name: "近三月" }).click();
  await expect(page).toHaveURL(/\/zh\/brief\?range=3m$/);
  await expect(page.getByRole("link", { name: "近三月" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await page.getByRole("link", { name: "近一月" }).click();
  await expect(page).toHaveURL(/\/zh\/brief\?range=1m$/);
  await expect(page.getByRole("link", { name: "近一月" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { name: "每日晨报" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("brief-mobile-390.png"),
    fullPage: true,
  });
  const mobilePerformanceSection = page
    .getByRole("heading", { name: "模拟盘收益" })
    .locator("xpath=ancestor::section[1]");
  await mobilePerformanceSection.scrollIntoViewIfNeeded();
  await mobilePerformanceSection.screenshot({
    path: testInfo.outputPath("brief-performance-mobile-390.png"),
  });

  await expect(page.getByRole("link", { name: "查看归档版" })).toHaveCount(0);
  // Manual archive save is retired: archiving runs daily via the auto-archive
  // LaunchAgent, so the brief page no longer renders a save control.
  await expect(page.getByRole("button", { name: "保存今日归档" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "更新今日归档" })).toHaveCount(0);
  await expect(page.getByText("本地 AI 情报源暂无条目。")).toBeVisible();

  // Digest titles only become <a href="http(s):..."> when items exist with safe URLs.
  await expect(
    page.locator('a[href^="http"]').filter({ has: page.locator("h3") }),
  ).toHaveCount(0);
});
