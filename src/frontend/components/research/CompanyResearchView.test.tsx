import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { CompanyEvents, CompanyFinancials, CompanyResearchView, CompanySources } from "./CompanyResearchView";
import type { CompanyResearch, ResearchSection } from "@/lib/companyResearch";
import { Sidebar } from "@/components/Sidebar";

vi.mock("next/navigation", () => ({ usePathname: () => "/zh/company-research" }));
vi.mock("@/components/LocaleProvider", () => ({ useLocale: () => "zh" }));

function evidence(key: string, data: unknown, options: Partial<ResearchSection> = {}): ResearchSection {
  return { key, label: key, status: "available", provider: "longbridge", operation: key, fetched_at: "2026-09-12T10:00:00Z", source_url: "https://example.com/source", raw_sha256: "a".repeat(64), data, ...options };
}
const report: CompanyResearch = {
  schema_version: 1, research_only: true, pit_backtest_ready: false,
  symbol: "NVDA", status: "partial", snapshot_id: "fixture-snapshot", stale: true,
  updated_at: "2026-09-12T10:00:00Z", headline: "营收增长需要结合现金流核对", summary: ["同季营收增长 20%"],
  source_policy: "Futu 优先报价，Longbridge 备用", warnings: ["业务分部的日期与报告标签存在冲突"],
  sections: [
    evidence("company", { name: "Fixture Company", profile: "测试公司主营简介", website: "https://example.com", employees: 100 }),
    evidence("quote", { last: 125, currency: "USD", as_of: "2026-09-11T20:00:00Z", pre_market: { last: 126, timestamp: "2026-09-11T12:00:00Z" } }, { provider: "futu" }),
    evidence("valuation", [{ symbol: "NVDA", pe: "-", pb: "12.5", dps_rate: "0.1", mktcap: "3000000000" }]),
    evidence("segments", { business: [{ name: "数据中心", percent: 80, value: 1000 }], regionals: [{ name: "美国", percent: 50 }], report_txt: "Q2 2027", rpt_date: "2026-07-31" }),
  ],
  financials: {
    status: "partial", currency: "USD", periods: [{ period: "Q2 2027", quarter: 2, fiscal_year: 2027, period_end: "2026-07-31", reported_at: null, revenue: 120000000, revenue_yoy_pct: 20, net_income: null }],
    metrics: [{ key: "revenue_yoy_pct", label: "营收同比", value: 20, unit: "pct", period: "Q2 2027", formula: "本季与上一财年同季比较" }, { key: "cash_ratio", label: "利润现金含量", value: null, unit: "ratio", period: "Q2 2027", formula: "经营现金流 / 净利润", reason: "缺少可比现金流量表" }],
    checks: [{ key: "balance", status: "unknown", message: "缺少资产负债表，无法核对" }], warnings: ["没有历史修订版本"],
  },
  research_ideas: [{ key: "growth", title: "观察收入增长持续性", formula: "营收同比变化", required_data: ["公布日期"], status: "observation_only", reason: "需要更多历史期间" }],
};

describe("CompanyResearchView", () => {
  it("starts empty and asks for an explicit update without fake metrics", () => {
    const html = renderToStaticMarkup(<CompanyResearchView locale="zh" initialSymbol="AAPL" initialReport={{ ...report, symbol: "AAPL", status: "not_loaded", headline: "尚无快照", sections: [], snapshot_id: null }} />);
    expect(html).toContain("AAPL 尚无已保存快照");
    expect(html).toContain("更新公司资料");
    expect(html).not.toContain("fixture-snapshot");
    expect(html).not.toContain("复制研究问题");
  });
  it("shows actual business data, quote source, stale state and backend date warnings", () => {
    const html = renderToStaticMarkup(<CompanyResearchView locale="zh" initialReport={report} />);
    for (const value of ["Fixture Company", "测试公司主营简介", "数据中心", "80%", "美国", "futu", "USD", "126", "快照已陈旧", "业务分部的日期与报告标签存在冲突", "fixture-snapshot", "复制研究问题", "概览", "财务", "事件与观点", "数据来源"]) expect(html).toContain(value);
    expect(html).toContain('href="/zh/hermes"');
    expect(html).toContain('role="tablist"');
    expect(html).toContain('aria-selected="true"');
    expect(html).not.toContain("undefined");
  });
  it("renders English controls and comparison reads", () => {
    const html = renderToStaticMarkup(<CompanyResearchView locale="en" initialReport={report} />);
    for (const value of ["Company Research", "Read snapshot", "Update company data", "Financials", "Events &amp; views", "Data sources", "Read comparison", "Copy research question"]) expect(html).toContain(value);
    expect(html).toContain('href="/en/hermes"');
  });
  it("makes company research visible after market outlook in the sidebar", () => {
    const html = renderToStaticMarkup(<Sidebar shellEnabled />);
    expect(html).toContain('href="/zh/company-research"');
    expect(html.indexOf('href="/zh/watch"')).toBeLessThan(html.indexOf('href="/zh/company-research"'));
    expect(html.indexOf('href="/zh/company-research"')).toBeLessThan(html.indexOf('href="/zh/brief"'));
  });
  it("labels Futu US market-local time as the snapshot update time", () => {
    const localQuote = { ...report, symbol: "NVDA.US", sections: [evidence("quote", { last: 218.29, currency: "USD", as_of: "2026-09-11 19:59:58.994", timestamp_kind: "market_local_snapshot_update" }, { provider: "futu" })] };
    const html = renderToStaticMarkup(<CompanyResearchView locale="zh" initialReport={localQuote}/>);
    expect(html).toContain("美东时间 · 快照更新时间");
    expect(html).toContain("2026-09-11 19:59:58.994");
    expect(html).not.toContain("2026-09-11 19:59:58.994 UTC");
    expect(html).not.toContain("最后成交时间");
  });
  it("keeps the financials cross-check button at the 44px touch target", async () => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const source = readFileSync(
      join(process.cwd(), "components/research/CompanyResearchView.tsx"),
      "utf8",
    );
    expect(source).toMatch(/app-touch-target[\s\S]*?核对财报与计算过程/);
    expect(source).toContain('app-touch-target mt-4 inline-flex items-center');
  });
});

describe("company evidence panels", () => {
  it("keeps fiscal periods, missing metrics, reason and checks visible", () => {
    const html = renderToStaticMarkup(<CompanyFinancials report={report} zh />);
    for (const value of ["Q2 2027", "2026-07-31", "1.2 亿", "20%", "缺少可比现金流量表", "缺少资产负债表，无法核对", "没有历史修订版本", "尚未具备按历史时点回测", "本季与上一财年同季比较"]) expect(html).toContain(value);
    expect(html).not.toContain("0×");
    expect(html).toContain('role="region"');
  });
  it("safely renders unknown source objects and suppresses non-HTTP source links", () => {
    const events = { ...report, sections: [evidence("news", [{ title: "<script>alert('x')</script>", url: "javascript:alert(1)", source: { unexpected: true }, summary: { nested: true } }]), evidence("consensus", { target: { unknown: 42 } }), evidence("filings", null, { status: "unavailable", reason: "权限不足" })] };
    const html = renderToStaticMarkup(<CompanyEvents report={events} zh />);
    expect(html).toContain("&lt;script&gt;"); expect(html).not.toContain("<script>");
    expect(html).not.toContain('href="javascript:');
    expect(html).toContain("权限不足"); expect(html).toContain("unknown");
  });
  it("shows raw hashes and distinct dates without declaring PIT ready", () => {
    const html = renderToStaticMarkup(<CompanySources report={report} zh capabilities={false}/>);
    for (const value of ["fixture-snapshot", "a".repeat(64), "SHA-256", "抓取时间", "尚未具备历史时点回测", "原始来源", "futu", "longbridge"]) expect(html).toContain(value);
  });
  it("explains quota and permission failures while preserving exact source codes", () => {
    const failures = { ...report, sections: [evidence("income", null, { status: "unavailable", reason: "quota_exceeded" }), evidence("quote", null, { status: "unavailable", reason: "permission_denied" }), evidence("filings", null, { status: "unavailable", reason: "request_timeout" })] };
    const html = renderToStaticMarkup(<CompanySources report={failures} zh capabilities={false}/>);
    expect(html).toContain("历史行情额度不足 (quota_exceeded)");
    expect(html).toContain("当前账号未开通此项行情权限 (permission_denied)");
    expect(html).toContain("request_timeout");
  });

  it("renders actual Longbridge filing, dividend, action, consensus and insider field shapes", () => {
    const actualShapes = { ...report, sections: [
      evidence("filings", [{ title: "NVIDIA Form 4", publish_at: "2026-09-11T21:04:47Z", file_urls: ["https://www.sec.gov/Archives/example.xml"] }]),
      evidence("dividends", { list: [{ desc: "Cash dividend 0.25 USD", ex_date: "09/10/2026", payment_date: "10/01/2026" }] }),
      evidence("corporate_actions", { items: [{ act_desc: "FY2027 Q2 Earning Release", date: "20260826", date_type: "Announcement Date" }] }),
      evidence("consensus", { list: [{ period_text: "Q4 2027", details: [{ key: "revenue", name: "Revenue", estimate: "124266648840", actual: "", is_released: false }] }] }),
      evidence("ratings", { instratings: { updated_at: "Sep 10, 2026", recommend: "strong_buy", target: "327.17759", ccy_symbol: "$", evaluate: { strong_buy: 48, buy: 10, hold: 2, sell: 1, under: 0 } }, analyst: { target: { highest_price: "515", lowest_price: "180" } } }),
      evidence("insiders", [{ owner: "Parker Nicholas P.", title: "EVP, Worldwide Field Ops", date: "2026-09-09", filing_date: "2026-09-11", type: "GRANT", code: "A", shares: 172507, price: 0 }]),
    ] };
    const html = renderToStaticMarkup(<CompanyEvents report={actualShapes} zh/>);
    for (const value of ['href="https://www.sec.gov/Archives/example.xml"', "2026-09-11 21:04:47 UTC", "Cash dividend 0.25 USD", "派息日", "10/01/2026", "FY2027 Q2 Earning Release", "2026-08-26", "Q4 2027", "未公布", "1,242.67 亿", "机构汇总意见", "$327.18", "强烈买入", "Parker Nicholas P.", "GRANT", "172,507", "申报日期"]) expect(html).toContain(value);
  });
});
