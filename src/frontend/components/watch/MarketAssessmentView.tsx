"use client";

import { useEffect, useId, useState } from "react";
import { ArrowUpRight, RefreshCw, Sparkles } from "lucide-react";
import Link from "next/link";
import { getMarketAssessment, refreshMarketAssessment, type MarketAssessment, type MarketScope } from "@/lib/marketAssessment";
import { watchHref } from "@/lib/watchPanes";
import type { Locale } from "@/lib/locale";

const number = (value: number | null | undefined, digits = 1) => value == null || !Number.isFinite(value) ? "—" : value.toLocaleString("en-US", { maximumFractionDigits: digits });
const scoreColor = (score: number | null) => score == null ? "var(--color-text-secondary)" : score >= 75 ? "var(--color-danger)" : score >= 45 ? "var(--color-warning)" : "#75b8a0";

export function marketFactorSection(key: string): "market" | "macro" {
  const metric = key.split(".").at(-1)?.toLowerCase() ?? "";
  return ["cape", "pe", "pb", "yield_spread", "buffett"].includes(metric) || metric.startsWith("buffett_") ? "macro" : "market";
}

function HistoryComparison({ factor, locale }: { factor: MarketAssessment["factors"][number]; locale: Locale }) {
  const zh = locale === "zh";
  const history = factor.history_reference;
  if (!history) return /^us\.(cape|pe|pb|buffett|yield_spread)$/.test(factor.key)
    ? <p className="mt-3 text-xs text-text-secondary">{zh ? "历史对照尚未取得" : "Historical comparison unavailable"}</p>
    : null;
  const frequency = zh
    ? { day: "日度", month: "月度", quarter: "季度", year: "年度" }[history.frequency]
    : { day: "daily", month: "monthly", quarter: "quarterly", year: "annual" }[history.frequency];
  const low = Math.min(history.minimum, factor.value ?? history.minimum);
  const high = Math.max(history.maximum, factor.value ?? history.maximum);
  const position = (value: number) => high === low ? 50 : 3 + (value - low) / (high - low) * 94;
  return <div className="mt-4 max-w-lg rounded-md bg-bg-surface px-3 py-3" data-history-reference={factor.key}>
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-[11px]">
      <span className="font-medium text-text-primary">{zh ? "真实历史对照" : "Historical comparison"}</span>
      <span className="text-text-secondary">{history.start_date} – {history.end_date} · {history.samples} {frequency}{zh ? "样本" : " observations"}</span>
    </div>
    <dl className="mt-3 grid grid-cols-3 gap-3">
      {[[zh ? "历史最低" : "Minimum", history.minimum], [zh ? "历史中位数" : "Median", history.median], [zh ? "历史最高" : "Maximum", history.maximum]].map(([label, value]) => <div key={String(label)}>
        <dt className="text-[10px] text-text-secondary">{label}</dt>
        <dd className="mt-1 font-mono text-sm text-text-primary">{number(value as number, 2)}<span className="ml-1 text-[10px] text-text-secondary">{factor.unit}</span></dd>
      </div>)}
    </dl>
    <div className="relative my-3 h-4" aria-hidden="true">
      <div className="absolute inset-x-0 top-1.5 h-1 rounded-full bg-border-subtle" />
      <div className="absolute top-1 h-2 rounded-full bg-text-secondary/35" style={{ left: `${position(history.minimum)}%`, width: `${position(history.maximum) - position(history.minimum)}%` }} />
      <span className="absolute top-0.5 h-3 w-px bg-text-secondary" style={{ left: `${position(history.median)}%` }} />
      {factor.value != null ? <span className="absolute top-0.5 h-3 w-3 -translate-x-1/2 rounded-full border-2 border-bg-surface bg-[var(--color-hermes)]" style={{ left: `${position(factor.value)}%` }} /> : null}
    </div>
    <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-text-secondary">
      <span>{zh ? "灰带为历史范围，不含本期值" : "Grey band: prior range, excluding the current period"}</span>
      {factor.value != null ? <span className="inline-flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-[var(--color-hermes)]" />{zh ? "当前" : "Current"} {number(factor.value, 2)} {factor.unit}</span> : null}
    </p>
  </div>;
}

function FactorTable({ factors, locale }: { factors: MarketAssessment["factors"]; locale: Locale }) {
  const zh = locale === "zh";
  return <div className="overflow-x-auto"><table className="w-full min-w-[620px] text-left text-xs">
    <thead className="border-b border-border-subtle text-text-secondary"><tr>
      {[zh ? "指标与已完成检查" : "Metric and completed checks", zh ? "当前值" : "Value", zh ? "分项 / 权重" : "Score / weight", zh ? "日期与来源" : "Date and source"].map(label => <th key={label} className="py-3 pr-5 font-medium">{label}</th>)}
    </tr></thead>
    <tbody>{factors.map(factor => <tr key={factor.key} className="border-b border-border-subtle/60">
      <td className="max-w-xl py-4 pr-5"><p className="font-medium text-text-primary">{factor.label}</p><p className="mt-1.5 text-xs leading-6 text-text-secondary">{factor.meaning}</p><HistoryComparison factor={factor} locale={locale} /></td>
      <td className="whitespace-nowrap pr-5 font-mono text-base">{number(factor.value, 2)}<span className="ml-1 text-xs text-text-secondary">{factor.value == null ? "" : factor.unit}</span></td>
      <td className="whitespace-nowrap pr-5 font-mono"><span style={{ color: scoreColor(factor.score) }}>{number(factor.score, 0)}</span><span className="text-text-secondary"> / 100</span><p className="mt-1 text-[10px] text-text-secondary">{zh ? "权重" : "Weight"} {number(factor.weight, 2)}%</p></td>
      <td className="font-mono text-text-secondary"><p className="whitespace-nowrap">{factor.source_date ?? (zh ? "日期不可用" : "Date unavailable")}</p><div className="mt-1 flex flex-col items-start">{Object.entries(factor.source_urls ?? (factor.source_url ? { source: factor.source_url } : {})).map(([key, url]) => <a key={key} className="inline-flex min-h-8 items-center gap-1 whitespace-nowrap text-[var(--color-hermes)] hover:underline" href={url} target="_blank" rel="noreferrer">{zh ? ({ market_cap: "联储市值", gdp: "BEA GDP", release: "联储发布日期", source: "数据来源" }[key] ?? key) : key}<ArrowUpRight size={11} /></a>)}</div></td>
    </tr>)}</tbody>
  </table></div>;
}

function MarketFactorDetails({ assessment, locale }: { assessment: MarketAssessment; locale: Locale }) {
  const zh = locale === "zh";
  const [activeSection, setActiveSection] = useState<"market" | "macro">("market");
  const prefix = useId();
  const sections = [
    { key: "market" as const, label: zh ? "行情与波动" : "Price & volatility" },
    { key: "macro" as const, label: assessment.scope === "asia" ? (zh ? "ETF估值" : "ETF valuations") : (zh ? "宏观与估值" : "Macro & valuations") },
  ];
  return <section className="border-t border-border-subtle pt-5" aria-label={zh ? "指标分组" : "Indicator groups"}>
    <div role="tablist" aria-label={zh ? "指标分组" : "Indicator groups"} className="flex flex-wrap gap-1 border-b border-border-subtle pb-3">
      {sections.map(section => <button
        key={section.key}
        id={`${prefix}-${section.key}-tab`}
        type="button"
        role="tab"
        data-factor-tab={section.key}
        aria-selected={activeSection === section.key}
        aria-controls={`${prefix}-${section.key}-panel`}
        tabIndex={activeSection === section.key ? 0 : -1}
        className={`app-touch-target rounded-md px-4 text-[13px] ${activeSection === section.key ? "bg-warning/10 font-medium text-warning" : "text-text-secondary hover:bg-bg-surface hover:text-text-primary"}`}
        onClick={() => setActiveSection(section.key)}
        onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          const next = event.key === "Home" ? "market" : event.key === "End" ? "macro" : activeSection === "market" ? "macro" : "market";
          setActiveSection(next);
          document.getElementById(`${prefix}-${next}-tab`)?.focus();
        }}
      >{section.label}</button>)}
    </div>
    <p className="mt-4 text-xs text-text-secondary">{zh ? `本次已取得 ${assessment.coverage.available}/${assessment.coverage.total} 项指标，覆盖原始权重的 ${number(assessment.coverage.weight_pct, 0)}%。缺项保留未知，各项日期与来源见表。` : `${assessment.coverage.available}/${assessment.coverage.total} indicators cover ${number(assessment.coverage.weight_pct, 0)}% of the original weights. Missing values remain unknown; dates and sources are listed below.`}</p>
    {sections.map(section => {
      const factors = assessment.factors.filter(factor => marketFactorSection(factor.key) === section.key);
      const macro = section.key === "macro";
      return <div key={section.key} hidden={activeSection !== section.key} role="tabpanel" aria-labelledby={`${prefix}-${section.key}-tab`} id={`${prefix}-${section.key}-panel`} data-factor-panel={section.key} className="pt-4" tabIndex={0}>
        {assessment.scope === "asia" && assessment.market_rows.length > 0 ? <>
          <div className="overflow-x-auto"><table className="w-full min-w-[640px] text-left text-xs">
            <thead className="border-b border-border-subtle text-text-secondary"><tr>{[zh ? "市场 / ETF" : "Market / ETF", ...(macro ? ["P/E", "P/B", zh ? "估值分项" : "Valuation score"] : [zh ? "距 200 日均线" : "200D MA distance", zh ? "距 252 日最高收盘" : "Below 252D high", zh ? "行情压力" : "Price pressure"]), zh ? "数据日期" : "Data date", zh ? "查看明细" : "Details"].map(label => <th key={label} className="py-3 pr-4 font-medium">{label}</th>)}</tr></thead>
            <tbody>{[...assessment.market_rows].sort((a, b) => ((macro ? b.valuation_score : b.pressure_score) ?? -1) - ((macro ? a.valuation_score : a.pressure_score) ?? -1)).map(row => {
              const priceDate = factors.find(factor => factor.key === `${row.symbol}.trend`)?.source_date;
              const score = macro ? row.valuation_score : row.pressure_score;
              return <tr key={row.symbol} className="border-b border-border-subtle/60">
                <td className="py-4 pr-4"><p className="font-medium">{row.label}</p><p className="mt-1 font-mono text-[10px] text-text-secondary">{row.symbol}</p></td>
                <td className="font-mono">{number(macro ? row.pe : row.trend_deviation_pct, 2)}{!macro && row.trend_deviation_pct != null ? "%" : ""}</td>
                <td className="font-mono">{number(macro ? row.pb : row.drawdown_pct, 2)}{!macro && row.drawdown_pct != null ? "%" : ""}</td>
                <td className="font-mono text-base" style={{ color: scoreColor(score) }}>{number(score, 0)}</td>
                <td className="font-mono text-text-secondary">{(macro ? row.source_date : priceDate) ?? "—"}</td>
                <td>{macro ? (row.source_url ? <a className="inline-flex min-h-11 items-center text-[var(--color-hermes)] hover:underline" href={row.source_url} target="_blank" rel="noreferrer">{zh ? "估值来源" : "Valuation source"}</a> : <span className="text-text-secondary">{zh ? "来源未接入" : "Source unavailable"}</span>) : <Link prefetch={false} className="app-touch-target inline-flex items-center text-[var(--color-hermes)] hover:underline" href={watchHref("quotes", locale, { symbol: row.symbol, provider: "futu" })}>{zh ? "K线与成交量" : "Price & volume"}</Link>}</td>
              </tr>;
            })}</tbody>
          </table></div>
          <details className="mt-4"><summary className="app-touch-target cursor-pointer text-xs text-text-secondary">{zh ? "展开分项计算与来源" : "Calculation details and sources"}</summary><FactorTable factors={factors} locale={locale} /></details>
        </> : factors.length > 0 ? <FactorTable factors={factors} locale={locale} /> : <p className="py-6 text-sm text-text-secondary">{zh ? "本次没有取得这组指标。" : "This indicator group is unavailable."}</p>}
      </div>;
    })}
  </section>;
}

function RiskGauge({ value, locale }: { value: number | null; locale: Locale }) {
  const score = value == null ? null : Math.max(0, Math.min(100, value));
  const angle = Math.PI * (1 - (score ?? 0) / 100);
  return <figure className="m-0 flex flex-col items-center justify-center" aria-label={`${locale === "zh" ? "综合观察评分" : "Assessment score"} ${number(score)} / 100`}>
    <svg viewBox="0 0 260 165" className="w-full max-w-[280px]" role="img" aria-label={locale === "zh" ? "从低到高的风险刻度" : "Risk scale from low to high"}>
      <path d="M25 135 A105 105 0 0 1 235 135" pathLength="100" fill="none" stroke="var(--color-border-subtle)" strokeWidth="16" />
      <path d="M25 135 A105 105 0 0 1 235 135" pathLength="100" fill="none" stroke="#75b8a0" strokeWidth="16" strokeDasharray="43 100" opacity="0.65" />
      <path d="M25 135 A105 105 0 0 1 235 135" pathLength="100" fill="none" stroke="var(--color-warning)" strokeWidth="16" strokeDasharray="29 100" strokeDashoffset="-45" opacity="0.75" />
      <path d="M25 135 A105 105 0 0 1 235 135" pathLength="100" fill="none" stroke="var(--color-danger)" strokeWidth="16" strokeDasharray="24 100" strokeDashoffset="-76" opacity="0.75" />
      {score != null ? <circle cx={130 + 105 * Math.cos(angle)} cy={135 - 105 * Math.sin(angle)} r="8" fill="var(--color-text-primary)" stroke="var(--color-bg-base)" strokeWidth="3" /> : null}
      <text x="130" y="117" textAnchor="middle" fill="var(--color-text-primary)" fontSize="48" fontWeight="500" fontFamily="var(--font-mono)">{number(score, 0)}</text>
      <text x="130" y="144" textAnchor="middle" fill="var(--color-text-secondary)" fontSize="11">{locale === "zh" ? "综合观察评分 / 100" : "Assessment score / 100"}</text>
      <text x="25" y="161" textAnchor="middle" fill="var(--color-text-secondary)" fontSize="10">0</text>
      <text x="235" y="161" textAnchor="middle" fill="var(--color-text-secondary)" fontSize="10">100</text>
    </svg>
    <figcaption className="mt-3 text-center text-[11px] text-text-secondary">{locale === "zh" ? "分数越高，已覆盖指标显示的风险越高" : "Higher scores indicate greater observed risk"}</figcaption>
  </figure>;
}

export function MarketAssessmentPanel({ assessment, locale, busy, error, onRefresh }: { assessment: MarketAssessment | null; locale: Locale; busy: boolean; error: string; onRefresh: () => void }) {
  const zh = locale === "zh";
  const ai = assessment?.input_digest && assessment.ai_analysis?.input_digest === assessment.input_digest ? assessment.ai_analysis : null;
  const previousAi = Boolean(ai && (busy || error || assessment?.ai_error || assessment?.status === "failed"));
  const reasoningEffort = ai && "reasoning_effort" in ai && typeof ai.reasoning_effort === "string" ? ai.reasoning_effort : null;
  const hasData = Boolean(assessment && assessment.coverage.available > 0);
  return <section aria-label={zh ? "市场研判结论" : "Market assessment"} className="space-y-7" data-market-assessment={assessment?.status ?? "loading"}>
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-subtle pb-4">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-secondary">
        <span>{assessment?.as_of ? `${zh ? "数据截至" : "Data as of"} ${assessment.as_of}` : zh ? "估值 · 宏观 · 市场压力" : "Valuation · Macro · Market pressure"}</span>
        {assessment ? <span>{zh ? "有效指标" : "Available factors"} {assessment.coverage.available}/{assessment.coverage.total}</span> : null}
        <span>{zh ? "每日 17:05（北京时间）自动更新" : "Updates daily at 17:05 China time"}</span>
        {busy ? <span role="status">{zh ? "正在更新，完成后会保留结果" : "Updating; results will be saved"}</span> : null}
      </div>
      <button type="button" onClick={onRefresh} disabled={busy} className="app-touch-target inline-flex items-center gap-2 rounded-md bg-[var(--color-hermes)] px-4 text-[13px] font-medium text-bg-base transition hover:brightness-110 disabled:cursor-wait disabled:opacity-60">
        <RefreshCw size={15} className={busy ? "animate-spin motion-reduce:animate-none" : ""} />{busy ? (zh ? "正在更新" : "Updating") : (zh ? "更新数据与 Grok 研判" : "Update data & Grok analysis")}
      </button>
    </div>
    {error ? <p role="alert" className="rounded-md border border-warning/30 px-4 py-3 text-sm text-warning">{error}</p> : null}
    {assessment?.ai_error ? <p role="alert" className="rounded-md border border-warning/30 px-4 py-3 text-sm text-warning">{assessment.ai_error}{ai ? (zh ? " 下方保留上次已生成的研判。" : " The previous analysis remains below.") : ""}</p> : null}
    <div className="grid items-center gap-8 border-b border-border-subtle pb-7 md:grid-cols-[250px_minmax(0,1fr)]">
      <RiskGauge value={assessment?.score ?? null} locale={locale} />
      <div>
        <p className="mb-3 text-xs tracking-wide text-[var(--color-hermes)]">{zh ? "系统数据结论" : "Data-based assessment"}</p>
        <h2 className="max-w-3xl text-balance text-2xl font-semibold leading-snug tracking-tight text-text-primary">{assessment?.rule_assessment.headline || (busy ? (zh ? "正在获取数据并完成市场检查" : "Collecting data and checking market conditions") : (zh ? "尚未获得可判断市场的数据" : "Market evidence is not available yet"))}</h2>
        {assessment?.rule_assessment.stance ? <p className="mt-3 max-w-3xl text-sm leading-7 text-text-secondary">{assessment.rule_assessment.stance}</p> : null}
        {assessment ? <div className="mt-6 flex flex-wrap gap-x-8 gap-y-4">
          {[[zh ? "下跌压力" : "Price pressure", assessment.scores.pressure], [zh ? "估值偏高程度" : "Valuation", assessment.scores.valuation], [zh ? "泡沫观察" : "Bubble indicators", assessment.scores.bubble]].map(([label, value]) => <div key={String(label)}><p className="text-[11px] text-text-secondary">{label}</p><p className="mt-1 font-mono text-xl" style={{ color: scoreColor(value as number | null) }}>{number(value as number | null, 0)}<span className="ml-1 text-xs text-text-secondary">/100</span></p></div>)}
        </div> : null}
      </div>
    </div>
    <section aria-label={zh ? "Grok 研判" : "Grok analysis"} data-assessment-ai={ai ? (previousAi ? "previous" : "current") : "unavailable"}>
      <div className="mb-3 flex flex-wrap items-center gap-2"><Sparkles size={16} className="text-[var(--color-hermes)]" /><h3 className="text-base font-semibold">{zh ? (previousAi ? "上次 AI 解读" : "AI 解读") : (previousAi ? "Previous AI interpretation" : "AI interpretation")}</h3>{ai ? <span className="ml-auto text-[11px] text-text-secondary">{ai.model} · {zh ? "推理强度" : "Reasoning"} {reasoningEffort ?? (zh ? "未记录" : "not recorded")} · {ai.generated_at.replace("T", " ").slice(0, 19)} UTC</span> : null}</div>
      {ai ? <>
        <p className="max-w-5xl whitespace-pre-line text-sm leading-7 text-text-primary">{ai.summary}</p>
        <div className="mt-5 grid gap-6 md:grid-cols-2">
          <div><h4 className="mb-2 text-xs text-text-secondary">{zh ? "当前建议" : "Current suggestions"}</h4><ul className="space-y-3 text-[13px] leading-6">{ai.actions.map((line, i) => <li key={i}>{line}</li>)}</ul></div>
          <div><h4 className="mb-2 text-xs text-text-secondary">{zh ? "结论适用条件" : "Conditions for this view"}</h4><ul className="space-y-3 text-[13px] leading-6">{ai.scenarios.map((line, i) => <li key={i}>{line}</li>)}</ul></div>
        </div>
        <p className="mt-4 text-[11px] text-text-secondary">{zh ? "引用指标" : "Evidence references"} · {ai.evidence_refs.map(ref => assessment?.factors.find(f => f.key === ref)?.label ?? assessment?.market_rows.find(row => row.symbol === ref)?.label ?? ref).join(" · ")}</p>
      </> : <p className="text-sm leading-6 text-text-secondary" role="status">{hasData
        ? (assessment?.ai_error ? (zh ? "已获得本次数据，但 AI 解读生成失败。下方保留系统实际完成的数据检查。" : "The data was collected, but AI interpretation failed. Completed data checks remain below.") : busy ? (zh ? "已获得本次数据，正在生成 AI 解读。" : "The data was collected; AI interpretation is being generated.") : (zh ? "已获得本次数据，尚未生成与这份数据匹配的 AI 解读。下方是系统检查结果。" : "The data was collected; no matching AI interpretation has been generated. Completed system checks appear below."))
        : (zh ? "当前尚无足够数据，AI 解读尚未生成。" : "There is not enough data yet; no AI interpretation has been generated.")}</p>}
    </section>
    {assessment?.input_digest && assessment.rule_assessment.reasons.length > 0 ? <section className="border-t border-border-subtle pt-5" data-assessment-checks>
      <h3 className="mb-3 text-sm font-semibold">{hasData ? (zh ? "系统已完成的检查" : "Completed system checks") : (zh ? "本次数据获取结果" : "Data collection results")}</h3>
      <ul className="grid gap-x-8 gap-y-3 text-[13px] leading-6 text-text-secondary lg:grid-cols-2">{assessment.rule_assessment.reasons.map((line, index) => <li key={`${index}-${line}`}>{line}</li>)}</ul>
    </section> : null}
    {assessment && assessment.factors.length > 0 ? <MarketFactorDetails assessment={assessment} locale={locale} /> : null}
    <p className="border-t border-border-subtle pt-4 text-[11px] leading-6 text-text-secondary">{zh ? "评分描述已覆盖数据的风险程度，尚未校准为崩盘概率。建议有适用条件，本页不执行交易。" : "Scores describe the covered evidence; they are not calibrated crash probabilities. Suggestions are conditional and this page does not execute trades."}</p>
  </section>;
}

export function MarketAssessmentView({ scope, locale }: { scope: MarketScope; locale: Locale }) {
  const [assessment, setAssessment] = useState<MarketAssessment | null>(null);
  const [error, setError] = useState("");
  const [requesting, setRequesting] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const read = async () => {
      try {
        const value = await getMarketAssessment(scope, controller.signal);
        if (controller.signal.aborted) return;
        setAssessment(value);
        setError("");
        if (value.status === "updating") timer = setTimeout(read, 3_000);
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Market assessment unavailable");
      }
    };
    void read();
    return () => { controller.abort(); if (timer) clearTimeout(timer); };
  }, [scope, requesting]);
  const refresh = async () => {
    setRequesting(true);
    setError("");
    try { setAssessment(await refreshMarketAssessment(scope)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Refresh failed"); }
    finally { setRequesting(false); }
  };
  return <MarketAssessmentPanel assessment={assessment} locale={locale} busy={requesting || (assessment?.status === "updating" && !error)} error={error} onRefresh={() => void refresh()} />;
}
