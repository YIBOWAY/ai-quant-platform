import { expect, test, type Page } from "@playwright/test";
import { definitionEvaluationFixture, RESEARCH_KEY, STRATEGY_ID } from "../support/research-product-fixtures.mjs";

test.beforeEach(() => {
  test.skip(process.env.PW_E2E !== "1" || process.env.PW_HERMES_WORKBENCH_FIXTURE !== "normal", "Explicit normal protocol fixture only; no real research/provider actions.");
});

function trackRequests(page: Page) {
  const requests: Array<{ method: string; url: string; body: unknown }> = [];
  page.on("request", request => { if (request.url().includes("/api/")) requests.push({ method: request.method(), url: request.url(), body: request.postDataJSON() }); });
  return requests;
}

const snapshot = {
  schema_version: 1, symbol: "NVDA.US", status: "partial", research_only: true, pit_backtest_ready: false,
  snapshot_id: "e2e-company-snapshot-a", updated_at: "2026-09-15T01:00:00Z", stale: false,
  source_policy: "Futu 优先，Longbridge 备用；本条为测试资料", headline: "测试收入增长，不是真实公司判断", summary: ["E2E 测试资料，不用于交易"], warnings: ["缺少历史修订数据，不能回测历史时点"],
  sections: [{ key: "company", label: "公司", status: "available", provider: "longbridge", operation: "company", fetched_at: "2026-09-15T01:00:00Z", raw_sha256: "c".repeat(64), source_url: "https://example.com/fixture", data: { name: "E2E Fixture Company", profile: "测试公司主营简介", employees: 100 } },
    { key: "quote", label: "报价", status: "available", provider: "futu", operation: "quote", fetched_at: "2026-09-15T01:00:00Z", raw_sha256: "d".repeat(64), data: { last: 125, currency: "USD", as_of: "2026-09-14T20:00:00Z" } },
    { key: "filings", label: "公告", status: "available", provider: "longbridge", operation: "filing", fetched_at: "2026-09-15T01:00:00Z", raw_sha256: "e".repeat(64), data: [{ title: "E2E Fixture Filing", publish_at: "2026-09-14T20:00:00Z", file_urls: ["https://example.com/fixture-filing"] }] }],
  financials: { status: "partial", currency: "USD", periods: [{ period: "FY2027Q2", fiscal_year: 2027, quarter: 2, period_end: "2026-07-31", reported_at: "2026-08-26", revenue: 120000000, revenue_yoy_pct: 20, net_income: null }], metrics: [{ key: "cash_ratio", label: "利润现金含量", value: null, unit: "ratio", period: "FY2027Q2", formula: "经营现金流 / 净利润", reason: "缺少同期间净利润" }], checks: [{ key: "balance", status: "unknown", message: "资产负债表尚缺失" }], warnings: [] }, research_ideas: [],
};

test("@combined-fixture company research updates explicitly, keeps identity and shows real permission failures", async ({ page }) => {
  let updated = false, checked = false;
  const requests = trackRequests(page);
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async (value: string) => { (window as unknown as { copiedResearch: string }).copiedResearch = value; } } });
  });
  await page.route("**/api/auth/owner/session", route => route.fulfill({ json: { session_id: "fixture-owner", mutation_enabled: true, security_ready: true }, headers: { "set-cookie": "qs_aw_csrf=fixture-company-csrf; Path=/; SameSite=Strict" } }));
  await page.route("**/api/company-research?*", route => route.fulfill({ json: updated ? snapshot : { ...snapshot, status: "not_loaded", snapshot_id: null, sections: [], financials: {} } }));
  await page.route("**/api/company-research/refresh", route => {
    expect(route.request().postDataJSON()).toEqual({ symbol: "NVDA" });
    updated = true; return route.fulfill({ status: 202, json: { ...snapshot, status: "updating", snapshot_id: null, sections: [], financials: {} } });
  });
  await page.route("**/api/data-sources", route => route.fulfill({ json: checked ? { status: "partial", checked_at: "2026-09-15T01:00:00Z", checks: [
    { provider: "longbridge", capability: "history", status: "unavailable", reason: "quota_exceeded" },
    { provider: "longbridge", capability: "option_quote", status: "unavailable", reason: "permission_denied" },
  ], sources: [] } : { status: "not_checked", sources: [{ provider: "longbridge", installed: true, version: "0.28.5" }], checks: [] } }));
  await page.route("**/api/data-sources/check", route => { checked = true; return route.fulfill({ status: 202, json: { status: "updating", sources: [], checks: [] } }); });
  await page.goto("/zh/company-research?symbol=NVDA", { waitUntil: "networkidle" });
  await expect(page.getByText(/NVDA 尚无已保存快照/)).toBeVisible();
  expect(requests.filter(row => row.method === "POST")).toHaveLength(0);
  await page.getByRole("button", { name: "更新公司资料", exact: true }).click();
  await expect(page.getByText("E2E Fixture Company", { exact: false })).toBeVisible();
  await page.locator("summary").filter({ hasText: "查看研究问题" }).click();
  await expect(page.getByText("e2e-company-snapshot-a", { exact: false }).first()).toBeVisible();
  await page.getByRole("tab", { name: "财务", exact: true }).click();
  await expect(page.getByText("FY2027Q2").first()).toBeVisible();
  await expect(page.getByText("缺少同期间净利润")).toBeVisible();
  await expect(page.getByRole("row", { name: /^净利润/ })).toContainText("—");
  await page.getByRole("tab", { name: "事件与观点", exact: true }).click();
  await expect(page.getByRole("link", { name: "E2E Fixture Filing" })).toHaveAttribute("href", "https://example.com/fixture-filing");
  await page.getByRole("tab", { name: "数据来源", exact: true }).click();
  await page.getByRole("button", { name: "检查当前股票权限" }).click();
  await expect(page.getByText(/quota_exceeded/)).toBeVisible();
  await expect(page.getByText(/permission_denied/)).toBeVisible();
  await page.getByRole("button", { name: "复制研究问题", exact: true }).click();
  const copied = await page.evaluate(() => (window as unknown as { copiedResearch: string }).copiedResearch);
  expect(copied).toContain("NVDA.US"); expect(copied).toContain("snapshot_id=e2e-company-snapshot-a"); expect(copied).toContain("不创建或启用策略");
  expect(requests.filter(row => row.method === "POST").map(row => new URL(row.url).pathname)).toEqual(["/api/company-research/refresh", "/api/data-sources/check"]);
});

test("@combined-fixture company failed refresh retains saved evidence and comparison never starts work", async ({ page }) => {
  const requests = trackRequests(page);
  await page.route("**/api/company-research?*", route => route.fulfill({ json: snapshot }));
  await page.route("**/api/auth/owner/session", route => route.fulfill({ json: { session_id: "fixture-owner", mutation_enabled: true, security_ready: true }, headers: { "set-cookie": "qs_aw_csrf=fixture-csrf; Path=/; SameSite=Strict" } }));
  await page.route("**/api/company-research/refresh", route => route.fulfill({ status: 202, json: { ...snapshot, status: "failed", error: "全部来源更新失败，保留上一份快照" } }));
  await page.route("**/api/company-research/compare?*", route => route.fulfill({ json: { comparison_note: "E2E 已保存快照对照", items: [snapshot, { ...snapshot, symbol: "AAPL.US", snapshot_id: "e2e-company-snapshot-b" }] } }));
  await page.goto("/zh/company-research?symbol=NVDA", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "更新公司资料", exact: true }).click();
  await expect(page.getByText("全部来源更新失败，保留上一份快照")).toBeVisible();
  await expect(page.getByText("测试公司主营简介")).toBeVisible();
  await page.getByLabel("对比股票，最多新增三个").fill("AAPL");
  await page.getByRole("button", { name: "读取对比快照" }).click();
  await expect(page.getByRole("rowheader", { name: "AAPL.US" })).toBeVisible();
  expect(requests.filter(row => row.method === "POST")).toHaveLength(1);
  expect(requests.some(row => new URL(row.url).pathname === "/api/company-research/compare")).toBe(true);
});

test("@combined-fixture collection preserves exact strategy evidence and separates factor IC", async ({ page }) => {
  const requests = trackRequests(page);
  await page.route("**/api/research-evaluation?*", route => route.fulfill({ json: { status: "unavailable", key: new URL(route.request().url()).searchParams.get("key"), progress: "未提供测试评价" } }));
  await page.goto(`/zh/collection?item=${encodeURIComponent(RESEARCH_KEY)}`, { waitUntil: "networkidle" });
  await expect(page.getByRole("heading", { name: "测试用每周反转组合", exact: true })).toBeVisible();
  const detail = page.getByRole("article", { name: "详情 测试用每周反转组合" });
  await expect(detail.getByText("20.00%", { exact: true })).toBeVisible();
  await expect(detail.getByText("0.8123", { exact: true })).toBeVisible();
  await expect(detail.getByRole("row").filter({ hasText: "Qlib" })).toContainText("—");
  await expect(detail.getByRole("row").filter({ hasText: "Qlib" })).not.toContainText("20.00%");
  await expect(detail.getByRole("row").filter({ hasText: "Qlib" })).not.toContainText("0.8123");
  await expect(detail.getByRole("link", { name: "查看这份策略的规则与验证" })).toHaveAttribute("href", `/zh/strategy-library?strategy=${STRATEGY_ID}#strategy-${STRATEGY_ID}`);
  expect(requests.some(row => new URL(row.url).pathname === "/api/research-evaluation")).toBe(false);
  await page.getByRole("button", { name: /^因子组件/ }).click();
  await expect(page.getByRole("heading", { name: "测试动量信号", exact: true })).toBeVisible();
  await expect(page.getByText("0.0357", { exact: true })).toBeVisible();
  await expect(page.getByText("19.01", { exact: true })).toHaveCount(0);
  expect(requests.filter(row => row.method === "POST")).toHaveLength(0);
});

test("@combined-fixture definition evaluation URL retains identity and never offers legacy reference rerun", async ({ page }) => {
  const requests = trackRequests(page);
  await page.route("**/api/research-evaluation?*", route => {
    expect(new URL(route.request().url()).searchParams.get("key")).toBe(RESEARCH_KEY);
    return route.fulfill({ json: definitionEvaluationFixture });
  });
  await page.goto(`/zh/research-evaluation?key=${encodeURIComponent(RESEARCH_KEY)}`, { waitUntil: "networkidle" });
  await expect(page.getByRole("heading", { name: "测试用每周反转组合", exact: true })).toBeVisible();
  await expect(page.getByText(RESEARCH_KEY, { exact: true })).toBeVisible();
  await expect(page.getByText("20.00%", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "运行真实数据评价" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "查看这份策略的规则与验证" })).toHaveAttribute("href", `/zh/strategy-library?strategy=${STRATEGY_ID}#strategy-${STRATEGY_ID}`);
  expect(requests.filter(row => row.method === "POST")).toHaveLength(0);
  expect(requests.some(row => new URL(row.url).pathname === "/api/strategy-studies")).toBe(false);
});
