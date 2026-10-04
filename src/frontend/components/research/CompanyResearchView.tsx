"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { ArrowUpRight, Building2, Check, Copy, Database, RefreshCw, Search } from "lucide-react";
import { localizePath, type Locale } from "@/lib/locale";
import {
  checkDataSources, companyResearchQuestion, compareCompanyResearch, getCompanyResearch,
  getDataSources, normalizeResearchSymbol, observeResearchUpdate, refreshCompanyResearch,
  researchNumber as numeric, researchObject as object, researchRows as rows,
  researchStrings as strings, researchText as text, safeResearchUrl,
  type CompanyResearch, type ResearchObject, type ResearchSection,
} from "@/lib/companyResearch";

type Tab = "overview" | "financials" | "events" | "sources";
const tabs: Tab[] = ["overview", "financials", "events", "sources"];
const button = "inline-flex min-h-10 items-center justify-center gap-2 rounded-md border border-border-strong px-3 py-2 text-sm text-text-primary transition-colors hover:bg-bg-elevated focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-hermes)] disabled:cursor-not-allowed disabled:opacity-50";
const input = "min-h-10 min-w-0 rounded-md border border-border-strong bg-bg-base px-3 py-2 text-sm text-text-primary outline-none focus:border-[var(--color-hermes)]";
const titles: Record<Tab, [string, string]> = {
  overview: ["概览", "Overview"], financials: ["财务", "Financials"],
  events: ["事件与观点", "Events & views"], sources: ["数据来源", "Data sources"],
};
const sectionTitles: Record<string, [string, string]> = {
  quote: ["行情", "Quote"], company: ["公司资料", "Company"], valuation: ["估值", "Valuation"],
  income: ["利润表", "Income statement"], balance: ["资产负债表", "Balance sheet"], cashflow: ["现金流量表", "Cash flow"],
  segments: ["业务构成", "Segments"], dividends: ["分红", "Dividends"], corporate_actions: ["公司行动", "Corporate actions"],
  news: ["新闻", "News"], filings: ["公司公告", "Filings"], consensus: ["市场一致预期", "Consensus"],
  ratings: ["分析师评级", "Analyst ratings"], insiders: ["内部人记录", "Insider records"],
};

function statusLabel(value: string, zh: boolean) {
  const names: Record<string, string> = {
    not_loaded: "尚无快照", not_checked: "尚未检查", updating: "正在更新", available: "可用", partial: "部分可用",
    failed: "未完成", unavailable: "不可用", empty: "未返回记录", ok: "已核对", invalid: "数据存在问题",
    passed: "通过", unknown: "尚无法核对", installed: "已安装", configured: "已配置", not_installed: "未安装",
  };
  return zh ? names[value] ?? value : value.replaceAll("_", " ");
}
function reasonText(value: unknown, zh: boolean) {
  const reason = text(value);
  if (reason === "quota_exceeded") return `${zh ? "历史行情额度不足" : "Insufficient historical market-data quota"} (${reason})`;
  if (reason === "permission_denied") return `${zh ? "当前账号未开通此项行情权限" : "This account does not have permission for this market data"} (${reason})`;
  return reason;
}
function Status({ value, zh }: { value: string; zh: boolean }) {
  return <span className={`inline-flex rounded border px-2 py-0.5 text-xs ${["unavailable", "failed", "invalid"].includes(value) ? "border-amber-700/50 text-amber-300" : "border-border-strong text-text-secondary"}`}>{statusLabel(value, zh)}</span>;
}
function number(value: unknown, digits = 2) {
  const v = numeric(value);
  return v === null ? "—" : v.toLocaleString("en-US", { maximumFractionDigits: digits });
}
function percent(value: unknown) { return numeric(value) === null ? "—" : `${number(value)}%`; }
function amount(value: unknown, zh: boolean) {
  const n = numeric(value);
  if (n === null) return "—";
  if (Math.abs(n) >= (zh ? 1e8 : 1e9)) return `${number(n / (zh ? 1e8 : 1e9))}${zh ? " 亿" : "B"}`;
  if (Math.abs(n) >= (zh ? 1e4 : 1e6)) return `${number(n / (zh ? 1e4 : 1e6))}${zh ? " 万" : "M"}`;
  return number(n);
}
function first(row: ResearchObject, keys: string[]): unknown {
  for (const key of keys) if (typeof row[key] === "string" || typeof row[key] === "number") return row[key];
  return undefined;
}
function display(value: unknown) { return typeof value === "number" ? number(value) : text(value); }
function section(report: CompanyResearch, key: string) { return report.sections?.find(item => item.key === key); }
function dataRecord(value?: ResearchSection) { return Array.isArray(value?.data) ? rows(value.data)[0] ?? {} : object(value?.data); }
function date(value: unknown) {
  const raw = text(value);
  return /^\d{8}$/.test(raw) ? `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}` : raw.replace("T", " ").replace(/\+00:00$|Z$/, " UTC");
}
function Section({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return <section className="min-w-0 rounded-lg border border-border-subtle bg-bg-surface p-4 sm:p-5">
    <div className="mb-4 flex flex-wrap items-center justify-between gap-2"><h2 className="text-base font-medium text-text-primary">{title}</h2>{aside}</div>{children}
  </section>;
}
function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-md border border-dashed border-border-strong px-4 py-5 text-sm leading-7 text-text-secondary">{children}</p>;
}
function External({ url, children }: { url: unknown; children: ReactNode }) {
  const href = safeResearchUrl(url);
  return href ? <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-[var(--color-hermes)] underline-offset-4 hover:underline">{children}<ArrowUpRight className="size-3.5 shrink-0" aria-hidden="true" /></a> : <span>{children}</span>;
}

/** A new read or action cancels the previous observer, including late provider responses. */
function useSavedSnapshot<T extends { status: string }>(
  identity: string, read: (signal: AbortSignal) => Promise<T>, initial: T | null = null,
) {
  const [saved, setSaved] = useState<{ identity: string; value: T } | null>(initial ? { identity, value: initial } : null);
  const [state, setState] = useState<{ identity: string; error: string | null; busy: boolean }>({ identity, error: null, busy: Boolean(identity && !initial) });
  const current = useRef<AbortController | null>(null);
  const receive = useCallback(async (action: (signal: AbortSignal) => Promise<T>, controller: AbortController) => {
    let error: string | null = null;
    try {
      const result = await action(controller.signal);
      await observeResearchUpdate(result, read, value => {
        if (!controller.signal.aborted && current.current === controller) setSaved({ identity, value });
      }, controller.signal);
    } catch (reason) {
      error = reason instanceof Error ? reason.message : String(reason);
    } finally {
      if (!controller.signal.aborted && current.current === controller) setState({ identity, error, busy: false });
    }
  }, [identity, read]);
  const run = useCallback(async (action: (signal: AbortSignal) => Promise<T>) => {
    current.current?.abort();
    const controller = new AbortController();
    current.current = controller;
    setState({ identity, error: null, busy: true });
    await receive(action, controller);
  }, [identity, receive]);
  useEffect(() => {
    const controller = new AbortController();
    current.current = controller;
    if (identity) void receive(read, controller);
    return () => current.current?.abort();
  }, [identity, read, receive]);
  return {
    report: saved?.identity === identity ? saved.value : null,
    error: state.identity === identity ? state.error : null,
    busy: state.identity === identity ? state.busy : Boolean(identity),
    run, cancel: () => current.current?.abort(),
  };
}

function Business({ report, zh }: { report: CompanyResearch; zh: boolean }) {
  const companySection = section(report, "company");
  const company = dataRecord(companySection);
  const segments = dataRecord(section(report, "segments"));
  const businesses = rows(segments.business ?? segments.businesses);
  const regionals = rows(segments.regionals);
  return <Section title={zh ? "这家公司做什么" : "What the company does"}>
    {companySection?.status === "available" ? <>
      <p className="whitespace-pre-line text-sm leading-7 text-text-secondary">{text(first(company, ["profile", "description", "business_description"]), zh ? "来源未提供公司简介。" : "No company profile was supplied.")}</p>
      <dl className="mt-4 flex flex-wrap gap-x-7 gap-y-2 border-t border-border-subtle pt-3 text-xs text-text-secondary">
        <div><dt className="inline">{zh ? "员工 " : "Employees "}</dt><dd className="inline font-mono text-text-primary">{number(company.employees, 0)}</dd></div>
        <div><dt className="inline">{zh ? "官网 " : "Website "}</dt><dd className="inline"><External url={company.website}>{text(company.website)}</External></dd></div>
      </dl>
    </> : <Empty>{companySection?.reason ?? (zh ? "公司资料尚不可用。" : "Company profile is unavailable.")}</Empty>}
    {[{ label: zh ? "按业务划分" : "Business segments", items: businesses }, { label: zh ? "按地区划分" : "Regional segments", items: regionals }].filter(group => group.items.length > 0).map(group => <div key={group.label} className="mt-5">
      <h3 className="mb-2 text-sm font-medium">{group.label}</h3>
      <div className="divide-y divide-border-subtle">{group.items.map((row, index) => <div key={index} className="flex items-center justify-between gap-4 py-2 text-sm">
        <span className="min-w-0 break-words text-text-secondary">{display(first(row, ["name", "business", "regional", "region"]))}</span>
        <span className="shrink-0 font-mono">{numeric(row.percent) !== null ? percent(row.percent) : amount(row.value, zh)}</span>
      </div>)}</div>
    </div>)}
    {(segments.rpt_date || segments.report_txt) ? <p className="mt-3 text-xs leading-5 text-text-secondary">{zh ? "来源标注报告期 " : "Source report period "}{display(segments.report_txt)} · {date(segments.rpt_date)}</p> : null}
  </Section>;
}

function ResearchTabs({ tab, onTab, zh }: { tab: Tab; onTab: (tab: Tab) => void; zh: boolean }) {
  return <div role="tablist" aria-label={zh ? "公司研究内容" : "Company research sections"} className="flex gap-1 overflow-x-auto border-b border-border-subtle">{tabs.map(item => <button id={`company-tab-${item}`} key={item} type="button" role="tab" aria-selected={tab === item} aria-controls={`company-panel-${item}`} tabIndex={tab === item ? 0 : -1} onKeyDown={event => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const target = event.key === "Home" ? tabs[0] : event.key === "End" ? tabs[tabs.length - 1] : tabs[(tabs.indexOf(item) + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length];
    onTab(target); document.getElementById(`company-tab-${target}`)?.focus();
  }} onClick={() => onTab(item)} className={`min-h-11 shrink-0 border-b-2 px-4 py-3 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--color-hermes)] ${tab === item ? "border-[var(--color-hermes)] text-[var(--color-hermes)]" : "border-transparent text-text-secondary hover:text-text-primary"}`}>{titles[item][zh ? 0 : 1]}</button>)}</div>;
}

export function CompanyFinancials({ report, zh }: { report: CompanyResearch; zh: boolean }) {
  const financials = object(report.financials);
  const periods = rows(financials.periods);
  const metrics = rows(financials.metrics);
  const checks = rows(financials.checks);
  const columns: [string, string, string, "amount" | "percent"][] = [
    ["revenue", "营收", "Revenue", "amount"], ["revenue_yoy_pct", "营收同比", "Revenue YoY", "percent"],
    ["revenue_qoq_pct", "营收环比", "Revenue QoQ", "percent"], ["gross_profit", "毛利润", "Gross profit", "amount"],
    ["gross_margin_pct", "毛利率", "Gross margin", "percent"], ["net_income", "净利润", "Net income", "amount"],
    ["net_margin_pct", "净利率", "Net margin", "percent"], ["assets", "总资产", "Assets", "amount"],
    ["liabilities", "总负债", "Liabilities", "amount"], ["equity", "股东权益", "Equity", "amount"],
    ["operating_cash_flow", "经营现金流", "Operating cash flow", "amount"],
  ];
  return <div className="space-y-5">
    <Section title={zh ? "财报趋势" : "Financial statements"} aside={<Status value={text(financials.status, "unavailable")} zh={zh} />}>
      <p className="mb-3 text-xs leading-6 text-text-secondary">{zh ? "币种" : "Currency"} {text(financials.currency)} · {zh ? "同比按上一年同季重算；缺失值留空，金额按万 / 亿缩写。" : "YoY is recalculated against the same quarter last year. Missing values remain blank; amounts use M / B."}</p>
      {!periods.length ? <Empty>{zh ? "没有足够的可比财报；更新后仍缺失时请查看数据来源。" : "No comparable statements are available. Check data sources for the missing evidence."}</Empty> : <div className="overflow-x-auto rounded-md border border-border-subtle" tabIndex={0} role="region" aria-label={zh ? "财务多期表格，可横向滚动" : "Financial periods, horizontally scrollable"}>
        <table className="w-full min-w-[560px] border-collapse text-left text-sm"><caption className="sr-only">{zh ? "历期财报与重算指标" : "Financial statements by reporting period"}</caption><thead className="bg-bg-elevated"><tr>
          <th scope="col" className="min-w-[135px] px-3 py-3 font-medium">{zh ? "指标" : "Metric"}</th>
          {periods.map((period, i) => <th scope="col" key={i} className="min-w-[140px] px-3 py-3 font-mono font-medium">{display(period.period)}<span className="mt-1 block font-sans text-[11px] font-normal text-text-secondary">{date(period.period_end)}</span></th>)}
        </tr></thead><tbody>{columns.map(([key, cn, en, unit]) => <tr className="border-t border-border-subtle" key={key}><th scope="row" className="px-3 py-3 font-normal text-text-secondary">{zh ? cn : en}</th>{periods.map((period, i) => <td key={i} className="px-3 py-3 font-mono">{unit === "percent" ? percent(period[key]) : amount(period[key], zh)}</td>)}</tr>)}
          <tr className="border-t border-border-subtle"><th scope="row" className="px-3 py-3 font-normal text-text-secondary">{zh ? "发布日期" : "Reported at"}</th>{periods.map((period, i) => <td key={i} className="px-3 py-3 text-xs text-text-secondary">{date(period.reported_at)}</td>)}</tr>
        </tbody></table>
      </div>}
      <Warnings values={strings(financials.warnings)} />
    </Section>
    {metrics.length > 0 && <Section title={zh ? "基本面观察指标" : "Fundamental observations"}>
      <div className="grid gap-x-5 gap-y-4 sm:grid-cols-2 xl:grid-cols-4">{metrics.map((metric, index) => <article key={text(metric.key, String(index))} className="border-t border-border-subtle pt-3">
        <div className="text-sm text-text-secondary">{text(metric.label, text(metric.key))}</div>
        <div className="my-2 font-mono text-2xl text-text-primary">{metric.unit === "pct" ? percent(metric.value) : number(metric.value)}{metric.unit === "ratio" && numeric(metric.value) !== null ? "×" : ""}</div>
        <p className="text-xs leading-5 text-text-secondary">{text(metric.period)}</p>
        <p className="mt-2 break-words text-xs leading-5 text-text-secondary">{zh ? "计算 " : "Formula "}{text(metric.formula)}</p>
        {metric.reason ? <p className="mt-2 text-xs leading-5 text-amber-300">{text(metric.reason)}</p> : null}
      </article>)}</div>
    </Section>}
    {checks.length > 0 && <Section title={zh ? "财报核对" : "Statement checks"}>
      <ul className="divide-y divide-border-subtle">{checks.map((check, index) => <li key={index} className="flex flex-wrap items-start gap-3 py-3 text-sm"><Status value={text(check.status, "unknown")} zh={zh}/><span className="min-w-0 flex-1 leading-6 text-text-secondary">{text(check.message)}</span></li>)}</ul>
    </Section>}
    <ResearchIdeas report={report} zh={zh} />
  </div>;
}

function ResearchIdeas({ report, zh }: { report: CompanyResearch; zh: boolean }) {
  const ideas = rows(report.research_ideas).length ? rows(report.research_ideas) : rows(object(report.financials).research_ideas);
  if (!ideas.length) return null;
  return <Section title={zh ? "可以继续追问" : "Questions to investigate"}>
    <p className="mb-4 text-xs leading-6 text-text-secondary">{zh ? "以下是观察线索，尚未具备按历史时点回测（PIT）的完整数据。" : "These observations still require point-in-time historical evidence before backtesting."}</p>
    <div className="space-y-4">{ideas.map((idea, i) => <article key={i} className="border-t border-border-subtle pt-3">
      <h3 className="text-sm font-medium">{text(idea.title)}</h3><p className="mt-1 break-words text-xs leading-6 text-text-secondary">{text(idea.formula)}</p>
      {idea.reason ? <p className="text-xs leading-6 text-text-secondary">{text(idea.reason)}</p> : null}
      {strings(idea.required_data).length > 0 && <p className="mt-1 text-xs leading-6 text-text-secondary">{zh ? "所需数据 " : "Required evidence "}{strings(idea.required_data).join(" · ")}</p>}
    </article>)}</div>
  </Section>;
}
function Warnings({ values }: { values: string[] }) {
  if (!values.length) return null;
  return <ul className="mt-3 space-y-1 border-l-2 border-amber-500/60 pl-3 text-xs leading-6 text-amber-200">{values.map((warning, index) => <li className="break-words" key={index}>{warning}</li>)}</ul>;
}

function ConsensusRecord({ record, zh }: { record: ResearchObject; zh: boolean }) {
  const details = rows(record.details);
  if (!details.length) return null;
  const metricNames: Record<string, string> = { revenue: "营收", ebit: "息税前利润", net_income: "净利润（GAAP）", normalized_net_income: "调整后净利润", eps: "每股收益（GAAP）", normalized_eps: "调整后每股收益" };
  return <div className="mt-2 overflow-x-auto"><table className="w-full min-w-[300px] text-left text-xs"><thead><tr className="border-b border-border-subtle text-text-secondary"><th scope="col" className="py-2 pr-3 font-normal">{zh ? "第三方预期指标" : "Consensus metric"}</th><th scope="col" className="py-2 pr-3 font-normal">{zh ? "预期值" : "Estimate"}</th><th scope="col" className="py-2 font-normal">{zh ? "已公布值" : "Reported"}</th></tr></thead><tbody>{details.map((detail, i) => {
    const key = text(detail.key, "");
    const format = (value: unknown) => key.includes("eps") ? number(value, 4) : amount(value, zh);
    return <tr key={i} className="border-b border-border-subtle/60"><th scope="row" className="py-2 pr-3 font-normal text-text-secondary">{zh ? metricNames[key] ?? text(detail.name, key) : text(detail.name, key)}</th><td className="py-2 pr-3 font-mono">{format(detail.estimate)}</td><td className="py-2 font-mono">{detail.is_released === false ? (zh ? "未公布" : "Not released") : format(detail.actual)}</td></tr>;
  })}</tbody></table></div>;
}

function AnalystRatings({ data, zh }: { data: ResearchObject; zh: boolean }) {
  const institution = object(data.instratings), analyst = object(data.analyst);
  const counts = object(institution.evaluate), targets = object(analyst.target);
  const recommendations: Record<string, string> = { strong_buy: "强烈买入", buy: "买入", hold: "持有", sell: "卖出", strong_sell: "强烈卖出" };
  const recommendation = text(institution.recommend);
  if (!Object.keys(institution).length && !Object.keys(analyst).length) return <JsonEvidence value={data}/>;
  return <>
    <p className="text-xs leading-6 text-text-secondary">{zh ? "机构汇总意见" : "Aggregated analyst opinion"} · {date(institution.updated_at)}</p>
    <p className="mt-2 text-sm">{zh ? recommendations[recommendation] ?? recommendation : recommendation.replaceAll("_", " ")}</p>
    <dl className="mt-4 grid grid-cols-3 gap-3 text-xs">{[
      [zh ? "机构目标价" : "Target", institution.target], [zh ? "最高目标价" : "Highest target", targets.highest_price], [zh ? "最低目标价" : "Lowest target", targets.lowest_price],
    ].map(([label, value]) => <div key={String(label)}><dt className="text-text-secondary">{String(label)}</dt><dd className="mt-1 font-mono">{numeric(value) === null ? "—" : `${text(institution.ccy_symbol, "")}${number(value)}`}</dd></div>)}</dl>
    <dl className="mt-4 flex flex-wrap gap-x-5 gap-y-2 border-t border-border-subtle pt-3 text-xs">{[["strong_buy", "强烈买入", "Strong buy"], ["buy", "买入", "Buy"], ["hold", "持有", "Hold"], ["sell", "卖出", "Sell"], ["under", "弱于大盘", "Underperform"]].map(([key, cn, en]) => <div key={key}><dt className="inline text-text-secondary">{zh ? cn : en} </dt><dd className="inline font-mono">{number(counts[key], 0)}</dd></div>)}</dl>
    <details className="mt-3 text-xs text-text-secondary"><summary className="cursor-pointer">{zh ? "评级原始记录" : "Original rating records"}</summary><JsonEvidence value={data}/></details>
  </>;
}

function EventRecord({ kind, record, provider, zh }: { kind: string; record: ResearchObject; provider: string; zh: boolean }) {
  const title = kind === "insiders" ? first(record, ["owner", "name", "title"]) : first(record, ["title", "headline", "name", "desc", "act_desc", "period_text", "description", "event", "type"]);
  const url = first(record, ["url", "link", "source_url", "filing_url", "article_url"]) ?? strings(record.file_urls).find(value => safeResearchUrl(value));
  const when = first(record, ["published_at", "publish_at", "publish_time", "date", "time", "report_date", "ex_date", "timestamp", "filing_date"]);
  const source = first(record, ["source", "publisher", "analyst", "institution", "broker"]) ?? provider;
  return <>
    <div className="text-sm leading-6 text-text-primary"><External url={url}>{display(title)}</External></div>
    <p className="mt-1 text-xs leading-6 text-text-secondary">{when !== undefined ? `${date(when)} · ` : ""}{display(source)}{record.date_type ? ` · ${text(record.date_type)}` : ""}</p>
    {kind === "consensus" && <ConsensusRecord record={record} zh={zh}/>}
    {kind === "dividends" && <p className="mt-1 text-xs leading-6 text-text-secondary">{zh ? "除息日 " : "Ex-date "}{date(record.ex_date)} · {zh ? "派息日 " : "Payment date "}{date(record.payment_date)}</p>}
    {kind === "insiders" && <>
      <p className="mt-1 text-xs leading-6 text-text-secondary">{text(record.title)} · {text(record.type)} ({text(record.code)})</p>
      <p className="mt-1 text-xs leading-6 text-text-secondary">{zh ? "股数 " : "Shares "}{number(record.shares, 0)} · {zh ? "申报价格 " : "Reported price "}{number(record.price)} · {zh ? "申报日期 " : "Filing date "}{date(record.filing_date)}</p>
    </>}
    {kind !== "insiders" && first(record, ["summary", "content", "rating"]) ? <p className="mt-1 whitespace-pre-line break-words text-xs leading-6 text-text-secondary">{display(first(record, ["summary", "content", "rating"]))}</p> : null}
    <details className="mt-2 text-xs text-text-secondary"><summary className="cursor-pointer">{zh ? "记录详情" : "Record details"}</summary><JsonEvidence value={record}/></details>
  </>;
}

export function CompanyEvents({ report, zh }: { report: CompanyResearch; zh: boolean }) {
  return <div className="space-y-5">
    <p className="text-sm leading-6 text-text-secondary">{zh ? "公告、新闻与分析师意见分别呈现。观点来自第三方，均保留来源和时间。" : "Filings, news and analyst views are separate records. Opinions are attributed to their sources and dates."}</p>
    <div className="grid items-start gap-5 xl:grid-cols-2">{["filings", "news", "dividends", "corporate_actions", "consensus", "ratings", "insiders"].map(key => {
      const item = section(report, key);
      const data = object(item?.data);
      const records = Array.isArray(item?.data) ? rows(item.data) : rows(data.items ?? data.list ?? data.records ?? data.news ?? data.filings);
      return <Section key={key} title={sectionTitles[key][zh ? 0 : 1]} aside={<Status value={item?.status ?? "unavailable"} zh={zh}/>}>
        {item?.status !== "available" ? <p className="text-sm leading-6 text-text-secondary">{item?.reason ?? (zh ? "暂无可用记录。" : "No records are available.")}</p> : <>
          {records.length > 0 ? <ul className="divide-y divide-border-subtle">{records.slice(0, 20).map((record, index) => <li className="py-3 first:pt-0" key={index}>
            <EventRecord kind={key} record={record} provider={item.provider} zh={zh}/>
          </li>)}</ul> : key === "ratings" ? <AnalystRatings data={data} zh={zh}/> : <JsonEvidence value={item.data}/>}
          <p className="mt-3 border-t border-border-subtle pt-3 text-xs text-text-secondary">{item.provider} · <External url={item.source_url}>{zh ? "数据来源" : "Source"}</External></p>
          {records.length > 20 && <p className="mt-2 text-xs text-text-secondary">{zh ? `共 ${records.length} 条，页面显示前 20 条。` : `${records.length} records; showing the first 20.`}</p>}
        </>}
      </Section>;
    })}</div>
  </div>;
}
function JsonEvidence({ value }: { value: unknown }) {
  return <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded bg-bg-base p-3 text-[11px] leading-5 text-text-secondary">{JSON.stringify(value ?? null, null, 2)}</pre>;
}

function DataSourceCapabilities({ symbol, zh }: { symbol: string; zh: boolean }) {
  const read = useCallback((signal: AbortSignal) => getDataSources(signal), []);
  const { report, error, busy, run } = useSavedSnapshot("sources", read);
  return <Section title={zh ? "数据源能力检查" : "Data source capabilities"} aside={<button type="button" className={button} disabled={busy || !symbol} onClick={() => void run(signal => checkDataSources(symbol, signal))}><RefreshCw className={`size-3.5 ${busy ? "animate-spin" : ""}`} aria-hidden="true"/>{zh ? "检查当前股票权限" : "Check this symbol"}</button>}>
    <p className="text-xs leading-6 text-text-secondary">{zh ? "安装与配置状态不代表行情权限。明确检查后才请求报价、最近及指定历史 K 线和财报；结果仅适用于被检查股票。" : "Installation does not prove data permission. An explicit check requests quotes, recent and dated historical bars, and statements for this symbol only."}</p>
    {error && <p role="alert" className="mt-3 break-words text-sm text-amber-300">{error}</p>}
    {report && <>
      <div className="my-4 flex flex-wrap items-center gap-3 text-xs text-text-secondary"><Status value={report.status} zh={zh}/><span>{zh ? "检查标的 " : "Checked symbol "}{text(report.symbol)}</span><span>{zh ? "上次检查 " : "Last check "}{date(report.checked_at)}</span></div>
      <div className="grid gap-3 sm:grid-cols-2">{rows(report.sources).map((source, i) => <div className="rounded border border-border-subtle p-3" key={i}>
        <div className="flex items-center justify-between gap-3"><span className="font-mono text-sm">{text(source.provider)}</span><Status value={text(source.status, "not_checked")} zh={zh}/></div>
        <p className="mt-2 text-xs leading-6 text-text-secondary">{zh ? "版本 " : "Version "}{text(source.version)}{typeof source.installed === "boolean" ? ` · ${source.installed ? (zh ? "已安装" : "installed") : (zh ? "未安装" : "not installed")}` : ""}</p>
        {source.reason ? <p className="text-xs leading-6 text-text-secondary">{reasonText(source.reason, zh)}</p> : null}
      </div>)}</div>
      {rows(report.checks).length > 0 && <ul className="mt-3 divide-y divide-border-subtle">{rows(report.checks).map((check, i) => <li className="py-3 text-sm" key={i}><div className="flex flex-wrap items-center justify-between gap-2"><span>{text(check.label, text(check.key))}</span><Status value={text(check.status, "unavailable")} zh={zh}/></div>{check.reason ? <p className="mt-1 text-xs leading-6 text-text-secondary">{reasonText(check.reason, zh)}</p> : null}{check.detail ? <details className="mt-2 text-xs text-text-secondary"><summary className="cursor-pointer">{zh ? "检查依据" : "Check evidence"}</summary><JsonEvidence value={check.detail}/></details> : null}</li>)}</ul>}
      {report.error && <p role="alert" className="mt-3 text-sm text-amber-300">{report.error}</p>}
    </>}
  </Section>;
}

export function CompanySources({ report, zh, capabilities = true }: { report: CompanyResearch; zh: boolean; capabilities?: boolean }) {
  const fallbacks = rows(dataRecord(section(report, "quote")).fallbacks);
  return <div className="space-y-5">
    <Section title={zh ? "快照与来源" : "Snapshot provenance"}>
      <p className="text-sm leading-7 text-text-secondary">{report.source_policy}</p>
      {fallbacks.length > 0 && <div className="mt-3 border-l-2 border-amber-500/60 pl-3 text-xs leading-6 text-text-secondary"><p>{zh ? "报价备用轨迹" : "Quote fallback trace"}</p>{fallbacks.map((fallback, i) => <p className="break-words" key={i}>{text(fallback.provider)} → {text(fallback.code, text(fallback.reason))}</p>)}<p>{zh ? "实际来源 " : "Served by "}{section(report, "quote")?.provider ?? "—"}</p></div>}
      <dl className="mt-3 grid gap-3 text-xs sm:grid-cols-2"><div><dt className="text-text-secondary">{zh ? "快照标识" : "Snapshot ID"}</dt><dd className="mt-1 break-all font-mono">{text(report.snapshot_id)}</dd></div><div><dt className="text-text-secondary">{zh ? "保存时间" : "Saved at"}</dt><dd className="mt-1 font-mono">{date(report.updated_at)}</dd></div></dl>
      <p className="mt-4 border-t border-border-subtle pt-4 text-sm leading-7 text-text-secondary">{zh ? "尚未具备历史时点回测（PIT）条件。报告期、发布日期和抓取时间分别记录；报告日期不能证明历史版本、修订记录和当时可见性已经齐备。" : "Point-in-time (PIT) backtesting is not ready. Reporting period, publication date and retrieval time are distinct; a report date alone does not prove historical versions, revisions or availability at the time."}</p>
    </Section>
    <div className="divide-y divide-border-subtle rounded-lg border border-border-subtle bg-bg-surface">{report.sections?.map(item => <details key={item.key} className="p-4 sm:p-5">
      <summary className="cursor-pointer text-sm marker:text-text-secondary"><span className="inline-flex max-w-full flex-wrap items-center gap-3 align-middle"><span className="font-medium">{sectionTitles[item.key]?.[zh ? 0 : 1] ?? item.label}</span><Status value={item.status} zh={zh}/><span className="font-mono text-xs text-text-secondary">{item.provider}</span></span></summary>
      <div className="mt-3 space-y-2 pl-4 text-xs leading-6 text-text-secondary">
        <p>{zh ? "抓取时间 " : "Retrieved "}{date(item.fetched_at)} · {item.operation}</p>
        {item.reason && <p className="text-amber-300">{reasonText(item.reason, zh)}</p>}
        <p><External url={item.source_url}>{zh ? "原始来源" : "Original source"}</External></p>
        <p className="break-all font-mono">SHA-256 {text(item.raw_sha256)}</p>
        <JsonEvidence value={item.data}/>
      </div>
    </details>)}</div>
    {capabilities && <DataSourceCapabilities symbol={report.symbol} zh={zh}/>}
  </div>;
}

function CompareSnapshots({ symbol, zh }: { symbol: string; zh: boolean }) {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<Awaited<ReturnType<typeof compareCompanyResearch>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const current = useRef<AbortController | null>(null);
  useEffect(() => () => current.current?.abort(), []);
  async function compare(event: FormEvent) {
    event.preventDefault();
    current.current?.abort();
    const controller = new AbortController();
    current.current = controller;
    setBusy(true); setError(null); setResult(null);
    try {
      const response = await compareCompanyResearch([symbol, ...query.split(/[,，\s]+/)], controller.signal);
      if (!controller.signal.aborted) setResult(response);
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <Section title={zh ? "并列查看已保存公司" : "Compare saved companies"}>
    <form onSubmit={compare} className="flex flex-wrap gap-2"><label className="min-w-[180px] flex-1"><span className="sr-only">{zh ? "对比股票，最多新增三个" : "Up to three comparison symbols"}</span><input value={query} onChange={event => setQuery(event.target.value)} className={`${input} w-full`} placeholder={zh ? "增加最多 3 个代码，以逗号分隔" : "Add up to 3 symbols, separated by commas"}/></label><button type="submit" className={button} disabled={busy || !symbol}>{zh ? "读取对比快照" : "Read comparison"}</button></form>
    <p className="mt-2 text-xs leading-6 text-text-secondary">{zh ? "含当前股票最多 4 家；只读取现有快照，各公司报告期不同则保留差异。" : "Up to 4 companies including this symbol. Reads existing snapshots and preserves differences in reporting periods."}</p>
    {error && <p role="alert" className="mt-3 text-sm text-amber-300">{error}</p>}
    {result && <><p className="mt-3 text-xs leading-6 text-text-secondary">{result.comparison_note}</p><div className="mt-3 overflow-x-auto"><table className="w-full min-w-[520px] text-left text-sm"><thead><tr className="border-b border-border-subtle">{[zh ? "公司" : "Company", zh ? "报告期" : "Period", zh ? "营收" : "Revenue", zh ? "营收同比" : "Revenue YoY", zh ? "状态 / 保存时间" : "Status / Saved"].map(label => <th className="py-2 pr-4 font-medium" key={label}>{label}</th>)}</tr></thead><tbody>{result.items.map(item => {
      const financials = object(item.financials); const latest = rows(financials.periods)[0] ?? {};
      return <tr className="border-b border-border-subtle" key={item.symbol}><th scope="row" className="py-3 pr-4 font-mono">{item.symbol}</th><td className="py-3 pr-4">{text(latest.period)}</td><td className="py-3 pr-4 font-mono">{amount(latest.revenue, zh)} <span className="text-xs text-text-secondary">{text(financials.currency, "")}</span></td><td className="py-3 pr-4 font-mono">{percent(latest.revenue_yoy_pct)}</td><td className="py-3 text-xs"><Status value={item.status} zh={zh}/><span className="mt-1 block text-text-secondary">{date(item.updated_at)}</span></td></tr>;
    })}</tbody></table></div></>}
  </Section>;
}

export function CompanyResearchView({ locale, initialSymbol = "", initialTab, initialReport = null }: {
  locale: Locale; initialSymbol?: string; initialTab?: string; initialReport?: CompanyResearch | null;
}) {
  const zh = locale === "zh";
  const initial = initialReport?.symbol ?? initialSymbol.trim().toUpperCase();
  const [symbol, setSymbol] = useState(initial);
  const [query, setQuery] = useState(initial);
  const [formError, setFormError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>(tabs.includes(initialTab as Tab) ? initialTab as Tab : "overview");
  const [copiedSnapshot, setCopiedSnapshot] = useState<string | null>(null);
  const read = useCallback((signal: AbortSignal) => getCompanyResearch(symbol, signal), [symbol]);
  const saved = useSavedSnapshot(symbol, read, initialReport);
  const report = saved.report;
  const quote = dataRecord(report ? section(report, "quote") : undefined);
  const company = dataRecord(report ? section(report, "company") : undefined);
  const valuation = dataRecord(report ? section(report, "valuation") : undefined);
  const loaded = report && report.status !== "not_loaded";
  const hasEvidence = Boolean(report?.snapshot_id || report?.sections?.length);
  function select(event: FormEvent) {
    event.preventDefault();
    try {
      const next = normalizeResearchSymbol(query);
      setFormError(null); setCopiedSnapshot(null);
      saved.cancel();
      if (next === symbol) void saved.run(read);
      else setSymbol(next);
      const url = new URL(window.location.href);
      url.searchParams.set("symbol", next);
      window.history.replaceState(null, "", url);
    } catch (reason) { setFormError(reason instanceof Error ? reason.message : String(reason)); }
  }
  async function copyQuestion() {
    if (!report) return;
    try { await navigator.clipboard.writeText(companyResearchQuestion(report, locale)); setCopiedSnapshot(report.snapshot_id ?? null); }
    catch { setFormError(zh ? "无法访问剪贴板，请展开下方研究问题后手动复制。" : "Clipboard unavailable. Expand the research question below and copy it manually."); }
  }
  return <div className="mx-auto w-full max-w-[1440px] space-y-5 px-4 py-6 sm:px-7 lg:px-8">
    <header className="flex flex-wrap items-end justify-between gap-4"><div><p className="mb-2 font-mono text-[10px] tracking-[0.18em] text-[var(--color-hermes)]">COMPANY RESEARCH</p><h1 className="flex items-center gap-3 text-2xl font-semibold tracking-tight text-text-primary"><Building2 className="size-6 text-[var(--color-hermes)]" strokeWidth={1.5} aria-hidden="true"/>{zh ? "公司研究" : "Company Research"}</h1><p className="mt-2 text-sm text-text-secondary">{zh ? "从主营业务、财报和事件，理解一家公司。" : "Understand a company through its business, financials and events."}</p></div>
      <Link href={localizePath("/hermes", locale)} className={button}>{zh ? "打开 Hermes" : "Open Hermes"}<ArrowUpRight className="size-4" aria-hidden="true"/></Link>
    </header>
    <form onSubmit={select} className="flex flex-wrap items-end gap-2 rounded-lg border border-border-subtle bg-bg-surface p-4"><label className="min-w-[150px] flex-1 sm:max-w-[320px]"><span className="mb-1.5 block text-xs text-text-secondary">{zh ? "股票代码" : "Symbol"}</span><input className={`${input} w-full font-mono`} value={query} onChange={event => setQuery(event.target.value)} autoCapitalize="characters" spellCheck={false} maxLength={32} placeholder="NVDA / AAPL.US / 700.HK" /></label>
      <button className={button} type="submit"><Search className="size-4" aria-hidden="true"/>{zh ? "查看快照" : "Read snapshot"}</button>
      <button className={`${button} border-[var(--color-hermes)]/60 text-[var(--color-hermes)]`} type="button" disabled={!symbol || saved.busy} onClick={() => void saved.run(signal => refreshCompanyResearch(symbol, signal))}><RefreshCw className={`size-4 ${saved.busy ? "animate-spin" : ""}`} aria-hidden="true"/>{zh ? "更新公司资料" : "Update company data"}</button>
      <p className="w-full pt-1 text-xs leading-6 text-text-secondary">{zh ? "查看只读取已保存记录。点击更新后采集当前所选公司的真实资料。" : "Reading uses saved records. Update fetches real data for the selected company."}{symbol && <span className="ml-2 font-mono text-text-primary">{zh ? "当前 " : "Selected "}{symbol}</span>}</p>
    </form>
    {(formError || saved.error || report?.error) && <div role="alert" className="space-y-2 rounded border border-amber-700/50 bg-amber-950/20 p-4 text-sm leading-6 text-amber-200">{[formError, saved.error, report?.error].filter(Boolean).map((error, index) => <p className="break-words" key={index}>{error}</p>)}</div>}
    <div role="status" aria-live="polite" className="text-xs text-text-secondary">{saved.busy ? (report?.status === "updating" ? (zh ? "正在后台更新，可继续查看已有资料。" : "Updating in the background. Saved data remains visible.") : (zh ? "正在读取记录…" : "Reading saved records…")) : ""}</div>
    {!symbol ? <Empty>{zh ? "输入股票代码开始查看；首次使用可点击“更新公司资料”建立快照。" : "Enter a symbol to begin. Use Update company data to create its first snapshot."}</Empty> : null}
    {symbol && !loaded && !saved.busy && <Empty>{zh ? `${symbol} 尚无已保存快照。点击“更新公司资料”获取基本面与事件资料。` : `No saved snapshot for ${symbol}. Update company data to retrieve fundamentals and events.`}</Empty>}
    {loaded && <>
      <section className="rounded-lg border border-border-subtle bg-bg-surface p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-5"><div className="min-w-0"><div className="mb-2 flex flex-wrap items-center gap-3"><span className="font-mono text-sm text-[var(--color-hermes)]">{report.symbol}</span><Status value={report.status} zh={zh}/>{report.stale && <span className="text-xs text-amber-300">{zh ? "快照已陈旧" : "Snapshot is stale"}</span>}</div><h2 className="break-words text-xl font-medium">{text(first(company, ["name", "company_name"]), report.symbol)}</h2><p className="mt-2 text-xs text-text-secondary">{zh ? "资料更新 " : "Updated "}{date(report.updated_at)}</p></div>
          <div className="text-left sm:text-right"><p className="mb-1.5 text-xs text-text-secondary">{zh ? "常规时段最新报价" : "Regular-session last quote"}</p><div className="font-mono text-3xl tracking-tight">{number(quote.last)} <span className="text-sm text-text-secondary">{text(quote.currency, "")}</span></div><p className="mt-2 text-xs text-text-secondary">{section(report, "quote")?.provider ?? "—"} · {date(quote.as_of)}{quote.timestamp_kind === "market_local_snapshot_update" && report.symbol.endsWith(".US") ? <span className="mt-1 block">{zh ? "美东时间 · 快照更新时间" : "US Eastern time · Snapshot updated"}</span> : null}</p></div>
        </div>
        {hasEvidence && <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-4 border-t border-border-subtle pt-4 sm:grid-cols-4">{[
          [zh ? "市值" : "Market cap", amount(valuation.mktcap, zh)], ["P/E", number(valuation.pe)], ["P/B", number(valuation.pb)], [zh ? "股息率" : "Dividend yield", percent(valuation.dps_rate)],
        ].map(([label, value]) => <div key={label}><dt className="text-xs text-text-secondary">{label}</dt><dd className="mt-1 font-mono text-lg">{value}</dd></div>)}</dl>}
        {hasEvidence && <p className="mt-3 text-xs leading-6 text-text-secondary">{zh ? "— 表示来源未提供或无法核对；具体原因见数据来源。" : "— means missing or unverifiable. See Data sources for the reason."}</p>}
        {hasEvidence && <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-xs text-text-secondary">{[["pre_market", zh ? "盘前" : "Pre-market"], ["post_market", zh ? "盘后" : "Post-market"], ["overnight", zh ? "夜盘" : "Overnight"]].map(([key, label]) => { const item = object(quote[key]); return <span key={key}>{label} <span className="font-mono text-text-primary">{number(item.last)}</span>{item.timestamp ? ` · ${date(item.timestamp)}` : ""}</span>; })}</div>}
        <Warnings values={report.warnings ?? []}/>
      </section>
      <ResearchTabs tab={tab} onTab={setTab} zh={zh}/>
      <div id={`company-panel-${tab}`} role="tabpanel" aria-labelledby={`company-tab-${tab}`} tabIndex={0} className="outline-none">
        {tab === "overview" && <div className="space-y-5"><div className="grid items-start gap-5 xl:grid-cols-[1.1fr_1fr]"><Business report={report} zh={zh}/><div className="space-y-5"><Section title={zh ? "已知财务表现" : "Financial observations"}><h3 className="text-sm leading-7 text-text-primary">{report.headline}</h3>{report.summary?.length ? <ul className="mt-3 space-y-3">{report.summary.map((summary, i) => <li key={i} className="border-l border-[var(--color-hermes)]/50 pl-3 text-sm leading-7 text-text-secondary">{summary}</li>)}</ul> : <p className="mt-2 text-sm text-text-secondary">{zh ? "尚无足够指标形成摘要。" : "There is not enough evidence for a summary."}</p>}<button type="button" className="app-touch-target mt-4 inline-flex items-center text-sm text-[var(--color-hermes)] hover:underline" onClick={() => setTab("financials")}>{zh ? "核对财报与计算过程" : "Review statements and calculations"} →</button></Section><ResearchIdeas report={report} zh={zh}/></div></div><CompareSnapshots key={symbol} symbol={symbol} zh={zh}/></div>}
        {tab === "financials" && <CompanyFinancials report={report} zh={zh}/>}
        {tab === "events" && <CompanyEvents report={report} zh={zh}/>}
        {tab === "sources" && <CompanySources report={report} zh={zh}/>}
      </div>
      {report.snapshot_id && <section className="rounded-lg border border-border-subtle bg-bg-surface p-4 sm:p-5"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-sm font-medium">{zh ? "带着这份资料继续研究" : "Continue with this evidence"}</h2><p className="mt-1 text-xs leading-6 text-text-secondary">{zh ? "复制包含股票与快照标识的问题，在 Hermes 中继续。" : "Copy a question with the symbol and snapshot ID to continue in Hermes."}</p></div><button type="button" className={button} onClick={() => void copyQuestion()}>{copiedSnapshot === report.snapshot_id ? <Check className="size-4" aria-hidden="true"/> : <Copy className="size-4" aria-hidden="true"/>}{copiedSnapshot === report.snapshot_id ? (zh ? "已复制" : "Copied") : (zh ? "复制研究问题" : "Copy research question")}</button></div><details className="mt-3 text-xs text-text-secondary"><summary className="cursor-pointer">{zh ? "查看研究问题" : "View research question"}</summary><p className="mt-2 select-text break-words leading-7">{companyResearchQuestion(report, locale)}</p></details></section>}
    </>}
    {!loaded && <><ResearchTabs tab={tab} onTab={setTab} zh={zh}/><div id={`company-panel-${tab}`} role="tabpanel" aria-labelledby={`company-tab-${tab}`} tabIndex={0}>{tab === "sources" ? <DataSourceCapabilities symbol={symbol} zh={zh}/> : <p className="text-sm leading-7 text-text-secondary">{zh ? "更新快照后，在这里查看公司业务、财报与事件。数据来源页可先检查已安装的数据源。" : "After updating a snapshot, review its business, financials and events here. Data sources shows installed providers now."}</p>}</div></>}
    <p className="flex items-start gap-2 text-xs leading-6 text-text-secondary"><Database className="mt-1 size-3.5 shrink-0" aria-hidden="true"/>{zh ? "报价与财报分别标注来源。估值和基本面观察需要结合报告期、缺失数据与公司事件理解。" : "Quotes and statements retain their sources. Interpret valuation and observations alongside reporting periods, missing data and company events."}</p>
  </div>;
}
