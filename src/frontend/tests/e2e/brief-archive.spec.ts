import { expect, test } from "@playwright/test";

test.beforeEach(() => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");
});

// /brief is an RSC: getLatestBriefIssue / getAiHotItems run on the Next server against
// NEXT_PUBLIC_QUANT_API_BASE_URL. Playwright page.route never sees those SSR fetches, so
// this suite asserts the hermetic empty-DB path that playwright.config forces
// (QS_DATABASE_ENABLED=false, no aihot seed). Positive seeded-archive coverage belongs
// in API/unit tests or a future backend seed helper — not a browser route mock.
test("brief empty archive DB offers save but fails closed and shows empty digest", async ({ page }) => {
  await page.goto("/zh/brief");
  await expect(page.getByRole("heading", { name: "每日晨报" })).toBeVisible();

  await expect(page.getByRole("link", { name: "查看归档版" })).toHaveCount(0);
  const saveButton = page.getByRole("button", { name: "保存今日归档" });
  await expect(saveButton).toBeVisible();
  await expect(page.getByText("本地 AI 情报源暂无条目。")).toBeVisible();

  await saveButton.click();
  await expect(page.locator('span[role="alert"]')).toContainText("brief_database_unavailable");

  // Digest titles only become <a href="http(s):..."> when items exist with safe URLs.
  await expect(
    page.locator('a[href^="http"]').filter({ has: page.locator("h3") }),
  ).toHaveCount(0);
});
