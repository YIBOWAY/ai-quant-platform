import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

test.beforeEach(() => {
  test.skip(process.env.PW_E2E !== "1", "Set PW_E2E=1 to run local full-stack smoke.");
});

test("Hermes exposes every read-only artifact through its exact unified result", async ({ page }) => {
  const seeded = JSON.parse(readFileSync(path.join(process.cwd(), "tests/fixtures/hermes-artifacts.v1.json"), "utf8")) as {
    items: Array<{ id: string; kind: string; data: Record<string, unknown> }>;
  };
  const mutations: string[] = [];
  page.on("request", request => { if (request.method() === "POST") mutations.push(request.url()); });
  await page.goto("/zh/hermes", { waitUntil: "networkidle" });
  await page.locator("summary").filter({ hasText: "运行记录与诊断" }).click();
  await expect(page.locator("[data-hermes-automation-summary]")).toBeVisible();
  await expect(page.getByText("自动化 0/4 正常", { exact: true })).toBeVisible();
  await expect(page.getByText("从未运行", { exact: true }).first()).toBeVisible();
  await expect(page.locator("#hermes-chat-rail textarea:not([disabled])")).toHaveCount(0);

  // The desk no longer repeats six large cards. Their source-bound catalog and
  // exact detail payload remain the user-visible way to inspect each result.
  for (const item of seeded.items) {
    await page.goto(`/zh/hermes/results?kind=${encodeURIComponent(item.kind)}`, { waitUntil: "networkidle" });
    const row = page.locator("[data-hermes-result-key]").filter({ has: page.locator(`a[href*="/${item.kind}/${item.id}"]`) });
    await expect(row).toHaveCount(1);
    await row.getByRole("link").click();
    await expect(page).toHaveURL(new RegExp(`/hermes/results/${item.kind}/${item.id}$`));
    const payload = page.locator("[data-hermes-result-resource]");
    await expect(payload).toBeVisible();
    const shown = JSON.parse(await payload.innerText());
    expect(shown.id).toBe(item.id);
    expect(shown.kind).toBe(item.kind);
    const expectedData = item.kind === "portfolio_risk" ? { account_equity: null, ledger_split: false, ...item.data } : item.data;
    expect(shown.data).toEqual(expectedData);
    await expect(page.getByRole("textbox", { name: "和 Hermes 对话" })).toBeDisabled();
  }
  expect(mutations).toEqual([]);
});
