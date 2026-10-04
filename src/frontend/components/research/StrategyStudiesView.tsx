"use client";

import { useEffect, useState } from "react";
import { ArrowUpRight, ChevronDown, FlaskConical, RefreshCw } from "lucide-react";
import type { Locale } from "@/lib/locale";
import { object, objects, strings, valueNumber, type EvaluationObject } from "@/lib/researchEvaluation";
import { getStrategyStudies, getStrategyStudyProfile, refreshStrategyStudies, type StrategyStudies, type StrategyStudyDetail } from "@/lib/strategyStudies";
import { discoverySaveSource, studySaveSource } from "@/lib/strategyLibrary";
import { SaveStrategyButton } from "./StrategyLibraryPanel";

const text = (value: unknown, fallback = "—") => typeof value === "string" && value ? value : fallback;
const number = (value: unknown, digits = 3) => valueNumber(value)?.toFixed(digits) ?? "—";
const pct = (value: unknown) => valueNumber(value) === null ? "—" : `${(valueNumber(value)! * 100).toFixed(2)}%`;
const money = (value: unknown) => valueNumber(value) === null ? "—" : `$${valueNumber(value)!.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
const FAMILY_NAMES: Record<string, [string, string]> = {
  stock_momentum: ["个股动量", "Stock momentum"], price_multifactor: ["个股多因子", "Stock multi-factor"],
  asset_momentum: ["跨资产配置", "Asset allocation"], index_trend: ["指数趋势", "Index trend"],
  rsi_reversion: ["指数短期回归", "Index reversion"], formula_hypothesis: ["待检验假说", "Research hypotheses"],
};
const familyName = (value: unknown, zh: boolean) => FAMILY_NAMES[text(value)]?.[zh ? 0 : 1] ?? text(value);
const statusName = (value: unknown, zh: boolean) => {
  if (!zh) return text(value);
  return ({ available: "已完成", ready: "已完成", partial: "部分完成", updating: "计算中", stale: "旧版本结果", not_started: "尚未运行", failed: "失败", unavailable: "未取得结果", frozen: "已冻结待检验", evaluated: "已检验", accepted: "公式检查通过", rejected: "未通过公式检查", duplicate: "重复信号", completed: "已完成" } as Record<string, string>)[text(value)] ?? text(value);
};
const reasonName = (value: unknown, zh: boolean) => {
  const raw = text(value);
  if (!zh) return raw;
  return ({ duplicate_expression: "与已有公式重复，未作为新增因子计算。", constant_expression: "公式为常数，不能区分标的。", study_no_signal_with_complete_history: "完整形成窗口不足，尚无有效交易信号。", study_no_evaluation_sessions: "评价区间没有有效交易日。", proposal_schema_invalid: "模型提议格式未通过检查。" } as Record<string, string>)[raw] ?? raw;
};

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="rounded-md border border-dashed border-border-strong px-5 py-7 text-sm leading-7 text-text-secondary">{children}</p>;
}

function ProfileProtocol({ profile, result, zh }: { profile: EvaluationObject; result: EvaluationObject; zh: boolean }) {
  const labels = object(profile.symbol_labels), symbols = strings(profile.symbols);
  const limitations = strings(profile.limitations);
  const staticNote = limitations.find(line => /幸存者|survivorship/i.test(line));
  const peer = strings(profile.peer_symbols);
  const assetType = ["stock_momentum", "price_multifactor", "formula_hypothesis"].includes(text(profile.family))
    ? (zh ? "个股" : "Stocks") : profile.family === "asset_momentum" ? (zh ? "跨资产 ETF" : "Cross-asset ETFs") : (zh ? "指数 ETF" : "Index ETFs");
  return <>
    <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs text-[var(--color-hermes)]">{assetType} · {familyName(profile.family, zh)}</p><h2 className="mt-2 text-2xl font-semibold tracking-tight">{text(profile.name)}</h2></div><span className="text-xs text-text-secondary">{statusName(result.status ?? "not_started", zh)}</span></div>
    {staticNote ? <p className="mt-5 border-l-2 border-warning pl-4 text-sm leading-7 text-warning">{staticNote} {zh ? "同池等权用于区分选股与股票池本身的收益，不能据此声称全市场超额收益。" : "The equal-weight peer separates selection from universe performance; it does not establish market-wide alpha."}</p> : null}
    <details className="group mt-4 border-y border-border-subtle py-2" aria-label={zh ? "候选池完整名单" : "Full candidate universe"}>
      <summary className="app-touch-target flex cursor-pointer list-none items-center gap-2 text-sm font-medium"><ChevronDown size={15} className="group-open:rotate-180"/>{zh ? `候选池完整名单 · ${peer.length} 个${profile.defensive_symbol ? "，另含防守资产" : ""}` : `Full candidate universe · ${peer.length} instruments`}{valueNumber(profile.top_n) ? <span className="ml-auto text-xs font-normal text-text-secondary">{zh ? `每期最多选 ${number(profile.top_n, 0)} 个` : `Select up to ${number(profile.top_n, 0)} each period`}</span> : null}</summary>
      <p className="mt-2 text-xs leading-6 text-text-secondary">{zh ? "这是可参与排名的研究范围；当期实际选中标的与权重见下面的调仓记录。" : "These instruments are eligible for ranking. Actual selections and weights are shown in the historical rebalance record."}</p>
      <ul className="mt-3 grid gap-x-6 gap-y-2 text-xs sm:grid-cols-2 xl:grid-cols-4">{symbols.map(symbol => <li key={symbol} className="flex gap-3 border-b border-border-subtle/50 py-2"><span className="w-14 shrink-0 font-mono font-medium">{symbol}</span><span className="text-text-secondary">{text(labels[symbol], symbol)}{symbol === profile.defensive_symbol ? (zh ? " · 防守" : " · defensive") : ""}</span></li>)}</ul>
    </details>
    <details className="group mt-3"><summary className="app-touch-target flex cursor-pointer list-none items-center gap-2 text-sm font-medium"><ChevronDown size={15} className="group-open:rotate-180"/>{zh ? "展开完整规则与比较口径" : "Full rules and comparison methodology"}</summary><dl className="mt-3 grid gap-6 border-y border-border-subtle py-5 text-sm lg:grid-cols-3">
      {[[zh ? "指标形成窗口" : "Formation", text(profile.formation)], [zh ? "调仓与持有" : "Rebalance & holding", `${profile.rebalance === "daily_event" ? (zh ? "每日检查，条件触发" : "Daily event-driven") : (zh ? "每月调仓" : "Monthly rebalance")} · ${text(profile.holding)}`], [zh ? "两组对照" : "Two comparisons", `${text(profile.benchmark_symbol)} ${zh ? "同期买入持有；" : "buy-and-hold; "}${peer.length === 1 ? (zh ? "同池对照与主基准相同。" : "the peer is the same instrument.") : (zh ? "同池中满足相同历史条件的全部标的等权月调仓。" : "monthly equal-weight of the same eligible universe.")}`]].map(([title, value]) => <div key={title}><dt className="text-xs text-text-secondary">{title}</dt><dd className="mt-2 leading-7">{value}</dd></div>)}
    </dl>
    <ol className="mt-4 list-inside list-decimal space-y-2 text-sm leading-7">{strings(profile.rules).map((rule, index) => <li key={index}>{rule}</li>)}</ol>
    </details>
    {profile.family === "rsi_reversion" ? <p className="mt-3 text-xs leading-6 text-[var(--color-hermes)]">{zh ? "本方案使用 Wilder RSI(2) 与独立进出场规则；与原因子组件中的 RSI(14) 排名组合不同，不能混用两者的回测指标。" : "This profile uses Wilder RSI(2) with explicit entry/exit rules, not the resident RSI(14) ranking component."}</p> : null}
    <details className="group mt-5 border-b border-border-subtle pb-4"><summary className="app-touch-target flex cursor-pointer list-none items-center gap-2 text-sm font-medium"><ChevronDown size={15} className="transition-transform group-open:rotate-180"/>{zh ? "公开方法来源、改编与计算口径" : "Sources, adaptations & calculation rules"}</summary><div className="mt-3 space-y-3 text-xs leading-7 text-text-secondary">{objects(profile.sources).map(source => /^https?:\/\//.test(text(source.url)) ? <a className="flex items-center gap-1 text-[var(--color-hermes)] hover:underline" key={text(source.url)} href={text(source.url)} target="_blank" rel="noreferrer">{text(source.title)}<ArrowUpRight size={12}/></a> : <p key={text(source.title)}>{text(source.title)}</p>)}{limitations.filter(line => line !== staticNote).map((line, index) => <p key={index}>{line}</p>)}{object(result.eligibility).peer_method ? <p>{text(object(result.eligibility).peer_method)}</p> : null}</div></details>
  </>;
}

function ActiveStudyMetrics({ result, profile, zh }: { result: EvaluationObject; profile: EvaluationObject; zh: boolean }) {
  const active = object(result.active_metrics), evidence = object(result.active_metrics_evidence);
  if (active.status !== "ready") {
    const reason = text(evidence.reason, text(active.reason, "not_imported"));
    const explanation = reason === "source_result_digest_mismatch"
      ? (zh ? "主动评价与当前保存结果不匹配，未展示其指标。" : "Active metrics do not match this saved result and are not displayed.")
      : reason === "not_imported"
        ? (zh ? "这份保存研究尚无经过绑定的主动评价补充统计。" : "No bound active-performance supplement is available for this saved study.")
        : (zh ? `主动评价暂不可用（${reason}）；原回测收益仍按保存记录展示。` : `Active metrics unavailable (${reason}); original saved returns remain visible.`);
    return <section className="mt-5 rounded-md border border-border-subtle px-4 py-3 text-xs leading-7 text-text-secondary" aria-label={zh ? "主动评价状态" : "Active evaluation status"}>{explanation}</section>;
  }
  const comparisons = [
    { name: zh ? `相对家族基准 ${text(profile.benchmark_symbol)}` : `Versus family benchmark ${text(profile.benchmark_symbol)}`, data: object(active.vs_benchmark) },
    { name: zh ? "相对同池等权" : "Versus equal-weight peer", data: object(active.vs_peer) },
  ];
  const interval = (item: EvaluationObject) => valueNumber(item.ci95_low) !== null && valueNumber(item.ci95_high) !== null ? `${number(item.ci95_low)} ～ ${number(item.ci95_high)}` : "—";
  const rows: [string, (item: EvaluationObject) => string][] = [
    [zh ? "平均超额收益（年化）" : "Mean active return (annualized)", item => pct(object(item.active_return).annualized)],
    [zh ? "相对基准表现的稳定度（IR）" : "Information ratio (IR)", item => number(object(item.information_ratio).value)],
    [zh ? "IR 的 95% 估计区间" : "IR 95% interval", item => interval(object(item.information_ratio))],
    [zh ? "偏离基准的波动（年化 TE）" : "Tracking error (annualized)", item => pct(object(item.tracking_error).annualized)],
    [zh ? "跟随基准涨跌的程度（β）" : "Sensitivity to the benchmark (beta)", item => number(object(item.beta_alpha).beta)],
    [zh ? "扣除基准影响后的估计收益（α）" : "Estimated return after benchmark effects (alpha)", item => pct(object(item.beta_alpha).alpha_annualized)],
    [zh ? "α 的统计证据（NW t）" : "Alpha evidence (NW t)", item => number(object(item.beta_alpha).alpha_nw_t)],
    [zh ? "策略 Sharpe 的 95% 估计区间" : "Strategy Sharpe 95% interval", item => interval(object(item.sharpe_se_ci))],
    [zh ? "与对照的 Sharpe 差" : "Sharpe difference versus reference", item => number(object(item.block_bootstrap).value)],
    [zh ? "Sharpe 差的配对 95% 估计区间" : "Paired Sharpe difference 95% interval", item => interval(object(item.block_bootstrap))],
  ];
  return <section className="mt-6 border-t border-border-subtle pt-5" aria-label={zh ? "相对基准的主动评价" : "Active performance versus references"}>
    <h3 className="text-base font-semibold">{zh ? "相对基准，多出来的表现如何" : "Performance beyond the reference"}</h3>
    <p className="mt-2 text-xs leading-7 text-text-secondary">{text(active.start)} → {text(active.end)} · {number(active.n_observations, 0)} {zh ? "个日收益样本" : "daily return samples"} · {evidence.kind === "derived_sidecar" ? (zh ? "绑定原保存曲线的补充统计，导入时未重跑策略。" : "Supplement bound to the original saved curve; importing did not rerun the strategy.") : (zh ? "随本次研究一同保存的统计。" : "Metrics saved with this study run.")}</p>
    <div className="mt-3 overflow-x-auto"><table className="w-full min-w-[650px] text-left text-sm"><thead className="border-b border-border-strong text-xs text-text-secondary"><tr><th className="py-3 pr-4 font-medium">{zh ? "评价指标" : "Metric"}</th>{comparisons.map(item => <th key={item.name} className="py-3 pr-4 text-right font-medium">{item.name}</th>)}</tr></thead><tbody>{rows.map(([name, format]) => <tr key={name} className="border-b border-border-subtle/60"><th className="py-3 pr-4 font-normal text-text-secondary">{name}</th>{comparisons.map(item => <td key={item.name} className="py-3 pr-4 text-right font-mono">{format(item.data)}</td>)}</tr>)}</tbody></table></div>
    <p className="mt-3 text-xs leading-7 text-text-secondary">{zh ? "α 按年化百分比展示，IR、β 和 Sharpe 没有百分比单位。IR 结合超额收益和偏离基准的波动；β 接近 1 表示历史涨跌幅度较接近基准。α 来自这段历史的回归估计，不是单独可交易的收益。" : "Alpha is annualized percent; IR, beta and Sharpe are unitless. IR combines active return and tracking error. Beta near one indicates similar historical sensitivity. Alpha is a historical regression estimate, not a separate tradeable return."}</p>
    <p className="mt-1 text-xs leading-7 text-text-secondary">{zh ? "估计区间不是未来收益的保证；差值区间跨过 0 时，仅凭这份样本不能确定改善方向。Sharpe 差采用配对分块抽样，保留日收益之间的部分时间依赖。— 表示原证据没有可用估计，不按 0 计算。" : "Intervals are not guarantees of future returns. A difference interval spanning zero does not establish improvement. Paired block resampling retains part of the serial dependence. A dash means no available estimate, not zero."}</p>
    <details className="mt-3"><summary className="app-touch-target cursor-pointer py-2 text-xs text-text-secondary">{zh ? "统计口径与绑定证据" : "Methodology and binding evidence"}</summary><p className="text-xs leading-7 text-text-secondary">{zh ? "区块长度 / 重抽次数" : "Block length / resamples"}: {number(object(active.disclosure).bootstrap_block_length, 0)} / {number(object(active.disclosure).bootstrap_resamples, 0)} · {text(object(active.disclosure).bootstrap_method)}</p><p className="mt-1 text-xs leading-7 text-text-secondary">{text(object(active.disclosure).note, "")}</p>{evidence.source_result_digest ? <p className="mt-2 break-all font-mono text-[11px] text-text-secondary">{zh ? "原结果摘要" : "Source result digest"}: {text(evidence.source_result_digest)}</p> : null}</details>
  </section>;
}

function Metrics({ result, profile, zh }: { result: EvaluationObject; profile: EvaluationObject; zh: boolean }) {
  const rows = [
    { name: zh ? "策略 · 扣费后" : "Strategy · net", metrics: object(result.metrics), costs: object(result.costs), exposure: result.average_exposure, risk: result.average_risk_exposure },
    { name: zh ? "策略 · 未扣费" : "Strategy · gross", metrics: object(result.gross_metrics), costs: {}, exposure: null, risk: null },
    { name: `${text(profile.benchmark_symbol)} ${zh ? "买入持有" : "buy-and-hold"}`, metrics: object(result.benchmark_metrics), costs: object(result.benchmark_costs), exposure: result.benchmark_average_exposure, risk: null },
    { name: zh ? "同池等权" : "Equal-weight peer", metrics: object(result.peer_metrics), costs: object(result.peer_costs), exposure: result.peer_average_exposure, risk: null },
  ];
  const fields: [string, (row: typeof rows[number]) => string][] = [
    [zh ? "累计收益" : "Total return", row => pct(row.metrics.total_return)],
    [zh ? "年化复合收益 CAGR" : "CAGR", row => pct(row.metrics.annualized_return)],
    ["Sharpe", row => number(row.metrics.sharpe, 4)],
    [zh ? "最大回撤" : "Maximum drawdown", row => pct(valueNumber(row.metrics.max_drawdown) === null ? null : Math.abs(valueNumber(row.metrics.max_drawdown)!))],
    [zh ? "年化波动率" : "Annual volatility", row => pct(row.metrics.volatility)],
    [zh ? "累计成交成本" : "Cumulative trading cost", row => money(row.costs.total)],
    [zh ? "平均持仓比例" : "Average invested exposure", row => pct(row.exposure)],
    [zh ? "平均风险资产比例" : "Average risk-asset exposure", row => pct(row.risk)],
  ];
  const rotating = valueNumber(profile.top_n) !== null && profile.rebalance === "monthly";
  return <section className="mt-6" aria-label={zh ? "当前策略收益与规则" : "Strategy returns and rules"}>
    <h3 className="text-lg font-semibold">{text(profile.name)} · {zh ? "回测收益" : "Backtest returns"}</h3>
    <p className="mt-2 text-sm leading-7 text-text-secondary">{zh ? "因子 / 规则" : "Signal / rule"} · {text(profile.formation)}{profile.expression ? <code className="ml-2 break-all font-mono text-xs">{text(profile.expression)}</code> : null}</p>
    <p className="mt-1 font-mono text-xs text-text-secondary">{text(result.start)} → {text(result.end)}</p>
    <p className="mt-3 rounded-md border-l-2 border-[var(--color-hermes)] bg-bg-surface px-4 py-3 text-sm leading-7">
      {rotating ? (zh ? <>累计净收益 <span className="font-mono text-[var(--color-hermes)]">{pct(object(result.metrics).total_return)}</span> 属于这套每月重新排名、轮换 Top {number(profile.top_n, 0)} 并等权配置的组合；候选池有 {strings(profile.peer_symbols).length} 个标的，持仓名单随月份变化。这不是某只股票的涨幅，也不是固定持有 {number(profile.top_n, 0)} 只股票的收益。</> : <>The net return of {pct(object(result.metrics).total_return)} belongs to a monthly re-ranked, equal-weight Top {number(profile.top_n, 0)} portfolio from {strings(profile.peer_symbols).length} candidates. Holdings change by month; this is neither one stock&apos;s return nor a fixed basket&apos;s return.</>) : (zh ? <>累计净收益 <span className="font-mono text-[var(--color-hermes)]">{pct(object(result.metrics).total_return)}</span> 属于上述进出场规则在完整区间内的组合表现；买入持有收益在对照列单独展示。</> : <>The net return of {pct(object(result.metrics).total_return)} is for this strategy&apos;s entry and exit rules over the full period. Buy-and-hold returns are shown separately.</>)}
    </p>
    <p className="mt-2 text-xs leading-6 text-text-secondary">{zh ? "毛收益是零费用独立回放；成本是实际累计成交支出，不能直接从毛收益百分比中相减。未记录的统计留空。" : "Gross returns are a separate zero-cost replay. Trading costs are dollar outlays, not a percentage to subtract from gross return. Unrecorded statistics stay empty."}</p><div className="mt-3 overflow-x-auto"><table className="w-full min-w-[660px] text-left text-sm"><caption className="sr-only">{text(profile.name)} · {text(result.start)} — {text(result.end)}</caption><thead className="border-b border-border-strong text-xs text-text-secondary"><tr><th className="py-3 pr-5 font-medium">{zh ? "评价指标" : "Metric"}</th>{rows.map(row => <th key={row.name} className="py-3 pr-5 text-right font-medium">{row.name}</th>)}</tr></thead><tbody>{fields.map(([title, value]) => <tr key={title} className="border-b border-border-subtle/60"><th className="py-3 pr-5 font-normal text-text-secondary">{title}</th>{rows.map((row, index) => <td key={row.name} className={`py-3 pr-5 text-right font-mono ${index === 0 ? "text-[var(--color-hermes)]" : ""}`}>{value(row)}</td>)}</tr>)}</tbody></table></div></section>;
}

function StudyComparison({ profiles, results, selected, onSelect, zh }: {
  profiles: EvaluationObject[]; results: EvaluationObject[]; selected: string;
  onSelect: (id: string) => void; zh: boolean;
}) {
  return <section className="my-6" aria-label={zh ? "固定方案对比总表" : "Fixed profile comparison"}>
    <h3 className="text-base font-semibold">{zh ? `${profiles.length} 套固定方案 · 对比总表` : `${profiles.length} fixed profiles · comparison`}</h3>
    <p className="mt-2 text-xs leading-6 text-text-secondary">{zh ? "点选策略名称查看规则与逐期持仓。顺序按用途固定，收益列分别来自各自真实区间；同池对照和基准随方案变化。" : "Select a profile to inspect its rules and holdings. Order is fixed by purpose; each row uses its own saved dates, peer and benchmark."}</p>
    <div className="mt-3 overflow-x-auto"><table className="w-full min-w-[780px] text-left text-xs">
      <thead className="border-b border-border-strong text-text-secondary"><tr>{[zh ? "策略 / 回测区间" : "Strategy / dates", zh ? "累计净收益" : "Net return", zh ? "同池等权" : "Peer return", zh ? "主基准收益" : "Benchmark", "Sharpe", zh ? "最大回撤" : "Drawdown"].map(name => <th key={name} className="px-3 py-3 font-medium first:pl-0">{name}</th>)}</tr></thead>
      <tbody>{profiles.map(profile => {
        const result = results.find(row => object(row.profile).id === profile.id) ?? {};
        const saved = object(result.profile), matchedProfile = Object.keys(saved).length ? saved : profile;
        const available = result.status === "available";
        const metric = (value: unknown) => available ? pct(value) : "—";
        return <tr key={text(profile.id)} className={`border-b border-border-subtle/60 ${selected === profile.id ? "bg-bg-surface-muted" : "hover:bg-bg-surface"}`}>
          <th className="py-2 pr-3 text-left font-normal"><button type="button" aria-pressed={selected === profile.id} onClick={() => onSelect(text(profile.id))} className={`app-touch-target w-full rounded px-2 py-2 text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-hermes)] ${selected === profile.id ? "font-semibold text-[var(--color-hermes)]" : "text-text-primary"}`}><span>{text(matchedProfile.name)}</span><span className="mt-1 block font-mono text-[10px] font-normal text-text-secondary">{text(result.start)} → {text(result.end)}{!available ? ` · ${statusName(result.status ?? "not_started", zh)}` : ""}</span></button></th>
          <td className="px-3 font-mono text-[var(--color-hermes)]">{metric(object(result.metrics).total_return)}</td>
          <td className="px-3 font-mono">{metric(object(result.peer_metrics).total_return)}</td>
          <td className="px-3 font-mono">{metric(object(result.benchmark_metrics).total_return)}<span className="mt-1 block text-[10px] text-text-secondary">{text(matchedProfile.benchmark_symbol)}</span></td>
          <td className="px-3 font-mono">{available ? number(object(result.metrics).sharpe, 4) : "—"}</td>
          <td className="px-3 font-mono">{metric(object(result.metrics).max_drawdown)}</td>
        </tr>;
      })}</tbody>
    </table></div>
  </section>;
}

function targetSummary(signal: EvaluationObject, zh: boolean) {
  if (signal.targets === null) return signal.action === "flat"
    ? (zh ? "未触发开仓，保持空仓" : "No entry; remain in cash")
    : (zh ? "本日不调仓，保持原持仓" : "No rebalance; retain existing positions");
  if (signal.targets && typeof signal.targets === "object") {
    return Object.entries(object(signal.targets)).map(([symbol, weight]) => `${symbol} ${pct(weight)}`).join(" / ") || (zh ? "全部退出，持有现金" : "Exit all positions; hold cash");
  }
  return zh ? "未记录目标持仓" : "Target holdings unavailable";
}

function RankingTable({ scores, targets, profile, offset = 0, zh }: {
  scores: EvaluationObject[]; targets: unknown; profile: EvaluationObject; offset?: number; zh: boolean;
}) {
  const labels = object(profile.symbol_labels), weights = object(targets);
  const crossSectional = valueNumber(profile.top_n) !== null;
  const momentumReturn = profile.family === "stock_momentum";
  return <div className="overflow-x-auto"><table className="w-full min-w-[530px] text-left text-sm">
    <thead className="border-b border-border-subtle text-xs text-text-secondary"><tr>{[zh ? "排名" : "Rank", zh ? "标的 / 名称" : "Instrument", momentumReturn ? (zh ? "形成期涨幅（12–2月动量）" : "Formation return (12–2 momentum)") : (zh ? "信号分数 / 指标" : "Score / indicators"), zh ? "目标权重" : "Target weight"].map(label => <th key={label} className="py-3 pr-4 font-medium">{label}</th>)}</tr></thead>
    <tbody>{scores.map((row, index) => <tr key={text(row.symbol)} className="border-b border-border-subtle/60">
      <td className="py-3 pr-4 font-mono text-text-secondary">{crossSectional ? offset + index + 1 : "—"}</td>
      <th className="py-3 pr-4 text-left font-normal"><span className="font-mono">{text(row.symbol)}</span><span className="ml-3 text-xs text-text-secondary">{text(row.name, text(labels[text(row.symbol)], text(row.symbol)))}</span></th>
      <td className="py-3 pr-4 font-mono text-xs">{valueNumber(row.score) !== null ? (momentumReturn ? pct(row.score) : number(row.score, 6)) : Object.entries(row).filter(([key, value]) => key !== "symbol" && valueNumber(value) !== null).map(([key, value]) => `${key} ${number(value, 4)}`).join(" · ") || "—"}</td>
      <td className={`py-3 pr-4 font-mono text-xs ${valueNumber(weights[text(row.symbol)]) ? "text-[var(--color-hermes)]" : "text-text-secondary"}`}>{targets === undefined ? "—" : targets === null ? (zh ? "维持原持仓" : "Unchanged") : Object.hasOwn(weights, text(row.symbol)) ? pct(weights[text(row.symbol)]) : (zh ? "未入选" : "Not selected")}</td>
    </tr>)}</tbody>
  </table></div>;
}

export function StudySignalEvidence({ detail, signal, profile, zh }: {
  detail: StrategyStudyDetail | null; signal: EvaluationObject; profile: EvaluationObject; zh: boolean;
}) {
  const scores = objects(signal.scores);
  const topN = valueNumber(profile.top_n) ?? scores.length;
  const selected = scores.slice(0, topN), remaining = scores.slice(topN);
  const reconciliation = object(detail?.reconciliation);
  const trades = objects(detail?.trades).filter(row => !signal.trade_date || row.date === signal.trade_date);
  const hasFillEvidence = detail && (trades.length > 0 || ["matched", "mismatch"].includes(text(reconciliation.status)));
  const dayFees = hasFillEvidence && trades.every(trade => valueNumber(trade.commission) !== null) ? trades.reduce((total, trade) => total + valueNumber(trade.commission)!, 0) : null;
  return <div>
    <p className="mt-3 text-xs leading-7 text-text-secondary">{text(signal.signal_date)} {zh ? "收盘信号 →" : "close signal →"} {text(signal.trade_date)} {zh ? "开盘执行" : "open execution"}</p>
    <p className="mt-2 text-sm leading-7"><span className="text-text-secondary">{zh ? "本期目标" : "Targets"} · </span>{targetSummary(signal, zh)}</p>
    {scores.length ? <>
      <h4 className="mt-4 text-sm font-medium">{valueNumber(profile.top_n) ? (zh ? `当期排名前 ${topN} · 共 ${scores.length} 个满足历史条件` : `Top ${topN} of ${scores.length} eligible instruments`) : (zh ? "当期指标与目标" : "Indicators and targets")}</h4>
      <RankingTable scores={selected} targets={signal.targets} profile={profile} zh={zh}/>
      {remaining.length ? <details className="group mt-2"><summary className="app-touch-target flex cursor-pointer list-none items-center gap-2 text-xs text-text-secondary"><ChevronDown size={14} className="group-open:rotate-180"/>{zh ? `展开其余 ${remaining.length} 个标的排名` : `Remaining ${remaining.length} ranks`}</summary><RankingTable scores={remaining} targets={signal.targets} profile={profile} offset={topN} zh={zh}/></details> : null}
    </> : <p className="mt-3 text-xs text-text-secondary">{zh ? "该期尚无可读取的排名分数。" : "No saved ranking scores for this date."}</p>}
    <div className="mt-5 border-t border-border-subtle pt-4">
      <h4 className="text-sm font-medium">{zh ? "该次回测成交与资金核对" : "Backtest fills and cash reconciliation"}</h4>
      {detail ? <>
        <p className={`mt-2 text-xs leading-6 ${reconciliation.status === "matched" ? "text-success" : "text-warning"}`}>
          {reconciliation.status === "matched" ? (zh ? "成交重建现金 + 持仓市值 = 已保存净值，核对一致。" : "Cash plus marked holdings match the saved NAV.") : reconciliation.status === "mismatch" ? (zh ? "成交重建与保存净值存在差额，需要复核。" : "Reconstructed and saved NAV differ; review is needed.") : text(reconciliation.reason, zh ? "资金核对未知：旧记录缺少完整证据。" : "Reconciliation unknown: saved evidence is incomplete.")}
          {reconciliation.as_of ? ` ${zh ? "核对截至" : "As of"} ${text(reconciliation.as_of)}` : ""}
        </p>
        <dl className="mt-4 grid grid-cols-2 gap-x-5 gap-y-4 xl:grid-cols-4">{[
          [zh ? "交易后现金" : "Cash", money(reconciliation.cash)],
          [zh ? "收盘持仓市值" : "Closing holdings value", money(reconciliation.market_value)],
          [zh ? "收盘净值 NAV" : "Closing NAV", money(reconciliation.equity)],
          [zh ? "该日佣金" : "Session commission", money(dayFees)],
        ].map(([name, value]) => <div key={name}><dt className="text-[11px] text-text-secondary">{name}</dt><dd className="mt-1 font-mono text-lg">{value}</dd></div>)}</dl>
        {trades.length ? <details className="group mt-4" open>
          <summary className="app-touch-target flex cursor-pointer list-none items-center gap-2 text-xs text-text-secondary"><ChevronDown size={14} className="group-open:rotate-180"/>{zh ? `该日实际回测成交 · ${trades.length} 笔` : `${trades.length} saved backtest fills`}</summary>
          <div className="overflow-x-auto"><table className="w-full min-w-[580px] text-left text-xs">
            <thead className="border-b border-border-subtle text-text-secondary"><tr>{[zh ? "标的" : "Symbol", zh ? "方向" : "Side", zh ? "数量" : "Quantity", zh ? "成交价" : "Fill price", zh ? "金额" : "Notional", zh ? "佣金" : "Commission"].map(name => <th key={name} className="py-3 pr-4 font-medium">{name}</th>)}</tr></thead>
            <tbody>{trades.map((trade, index) => <tr key={`${text(trade.symbol)}-${index}`} className="border-b border-border-subtle/60"><th className="py-3 pr-4 font-mono font-normal">{text(trade.symbol)}</th><td className="pr-4">{trade.side === "buy" ? (zh ? "买入" : "Buy") : trade.side === "sell" ? (zh ? "卖出" : "Sell") : text(trade.side)}</td><td className="pr-4 font-mono">{number(trade.quantity, 4)}</td><td className="pr-4 font-mono">{money(trade.fill_price)}</td><td className="pr-4 font-mono">{money(valueNumber(trade.fill_price) !== null && valueNumber(trade.quantity) !== null ? valueNumber(trade.fill_price)! * valueNumber(trade.quantity)! : null)}</td><td className="pr-4 font-mono">{money(trade.commission)}</td></tr>)}</tbody>
          </table></div>
        </details> : <p className="mt-4 text-xs text-text-secondary">{hasFillEvidence ? (zh ? "该日保存记录为 0 笔成交；目标权重不等于实际成交。" : "No fills were saved for this date; target weights alone are not fills.") : (zh ? "旧记录未提供可核验的成交明细，成交笔数与费用未知。" : "The legacy record lacks verifiable fills; fill count and costs are unknown.")}</p>}
        <p className="mt-3 text-[11px] leading-6 text-text-secondary">{zh ? "成交价已包含滑点，佣金单列；净值按当日收盘盯市，没有为核对而强制卖出。这里只读本次历史回测，不改变模拟账户。" : "Fill prices include slippage; commissions are separate. NAV is marked at the session close without forced liquidation. These are saved backtest records."}</p>
        {objects(object(reconciliation.full_period).attribution).length ? <details className="group mt-4 border-t border-border-subtle pt-2">
          <summary className="app-touch-target flex cursor-pointer list-none items-center gap-2 text-sm"><ChevronDown size={14} className="group-open:rotate-180"/>{zh ? "整个回测的利润由哪些标的贡献？" : "Which instruments contributed to the full backtest?"}</summary>
          <p className="my-3 text-xs leading-6 text-text-secondary">{text(object(reconciliation.full_period).as_of)} · {zh ? "累计净利润" : "Cumulative net profit"} {money(object(reconciliation.full_period).net_profit)} · {zh ? "按真实回测买卖现金流、佣金与期末持仓市值计算。这里是收益贡献，不是当期选股排名。" : "Saved buy/sell cash flows, commissions and terminal holdings; this is P&L attribution, not the selection ranking."}</p>
          <div className="grid gap-x-8 sm:grid-cols-2 xl:grid-cols-3">{objects(object(reconciliation.full_period).attribution).map(row => <div key={text(row.symbol)} className="flex justify-between border-b border-border-subtle/50 py-2 text-xs"><span className="font-mono">{text(row.symbol)}</span><span className="font-mono">{money(row.net_profit)}</span></div>)}</div>
        </details> : null}
      </> : <p className="mt-3 text-xs leading-6 text-text-secondary">{zh ? "成交与资金核对尚未取得，未知项保持留空。" : "Fills and cash reconciliation are not loaded; unknown values remain empty."}</p>}
    </div>
  </div>;
}

function StudyHistory({ runId, profile, result, zh }: { runId: string | null; profile: EvaluationObject; result: EvaluationObject; zh: boolean }) {
  const latest = object(result.latest_signal);
  const initialDates = strings(result.signal_dates);
  const [date, setDate] = useState(initialDates.at(-1) ?? text(latest.signal_date, ""));
  const [saved, setSaved] = useState<{ detail: StrategyStudyDetail; date: string } | null>(null);
  const [failure, setFailure] = useState<{ message: string; date: string } | null>(null);
  const profileId = text(profile.id, "");
  useEffect(() => {
    if (!runId || !profileId) return;
    let active = true;
    getStrategyStudyProfile(runId, profileId, date || undefined).then(detail => {
      if (active) { setSaved({ detail, date }); setFailure(null); }
    }).catch(reason => { if (active) setFailure({ message: reason instanceof Error ? reason.message : "Saved study detail unavailable", date }); });
    return () => { active = false; };
  }, [runId, profileId, date]);
  const detail = saved?.date === date && saved.detail.run_id === runId && saved.detail.profile_id === profileId ? saved.detail : null;
  const dates = strings(saved?.detail.signal_dates).length ? saved!.detail.signal_dates : initialDates.length ? initialDates : typeof latest.signal_date === "string" ? [latest.signal_date] : [];
  const signal = detail ? objects(detail.signals).find(row => row.signal_date === date) ?? objects(detail.signals).at(-1) ?? {} : latest.signal_date === date ? latest : {};
  const error = failure?.date === date ? failure.message : null;
  return <section className="mt-6 rounded-lg border border-border-strong p-4 sm:p-5" aria-label={zh ? "历史调仓记录" : "Historical rebalance records"}>
    <div className="flex flex-wrap items-start justify-between gap-4"><div><h3 className="text-base font-semibold">{zh ? "每期选了谁，怎样成交" : "Selections and fills for each period"}</h3><p className="mt-1 text-xs leading-6 text-text-secondary">{zh ? "按信号日期查看当时的排名、目标与成交；候选池不等于持仓。" : "Inspect ranks, targets and fills by signal date. The candidate universe is not the portfolio."}</p></div><label className="space-y-1 text-xs text-text-secondary"><span>{profile.rebalance === "daily_event" ? (zh ? "历史检查日期" : "Historical signal date") : (zh ? "调仓信号日期" : "Rebalance signal date")}</span><select aria-label={zh ? "调仓信号日期" : "Rebalance signal date"} value={date} disabled={!dates.length} onChange={event => setDate(event.target.value)} className="app-touch-target block rounded-md border border-border-strong bg-bg-base px-3 font-mono text-sm text-text-primary">{dates.length ? [...dates].reverse().map(value => <option value={value} key={value}>{value}</option>) : <option value="">{zh ? "尚无历史日期" : "No saved dates"}</option>}</select></label></div>
    {error ? <p role="alert" className="mt-3 text-xs text-warning">{error}</p> : !detail && runId ? <p role="status" className="mt-3 text-xs text-text-secondary">{zh ? "正在读取该日期的保存明细…" : "Loading saved details for this date…"}</p> : null}
    {Object.keys(signal).length ? <StudySignalEvidence detail={detail} signal={signal} profile={profile} zh={zh}/> : <p className="mt-4 text-sm text-text-secondary">{error ? (zh ? "该日期明细未取得，没有借用其他日期的持仓或成交。" : "No details for this date; other dates are not substituted.") : !runId ? (zh ? "旧结果未记录可查询的研究标识，成交与资金核对未知。" : "This legacy result has no queryable run identity; fills and cash remain unknown.") : (zh ? "尚无该日期可显示的排名与成交。" : "No ranks or fills available for this date yet.")}</p>}
  </section>;
}

export function StudyCurve({ value, benchmark, zh }: { value: unknown; benchmark: string; zh: boolean }) {
  const points = objects(value).filter(point => typeof point.date === "string" && Number.isFinite(Date.parse(point.date))).sort((a, b) => Date.parse(text(a.date)) - Date.parse(text(b.date)));
  const keys = ["equity", "benchmark", "peer"] as const;
  const values = points.flatMap(point => keys.map(key => valueNumber(point[key]))).filter((value): value is number => value !== null);
  if (!points.length || !values.length) return <Empty>{zh ? "尚无真实净值曲线。" : "No saved equity curve."}</Empty>;
  const low = Math.min(...values), high = Math.max(...values), span = high - low || Math.max(Math.abs(high) * 0.01, 1);
  const first = Date.parse(text(points[0].date)), last = Date.parse(text(points[points.length - 1].date));
  const x = (date: unknown) => 85 + (Date.parse(text(date)) - first) / (last - first || 1) * 830;
  const y = (value: number) => 245 - (value - low) / span * 215;
  const path = (key: typeof keys[number]) => {
    let drawing = false;
    return points.map(point => { const value = valueNumber(point[key]); if (value === null) { drawing = false; return ""; } const command = drawing ? "L" : "M"; drawing = true; return `${command}${x(point.date).toFixed(1)},${y(value).toFixed(1)}`; }).join(" ");
  };
  const lines = [{ key: "equity" as const, name: zh ? "策略扣费净值" : "Strategy net", color: "var(--color-hermes)", dash: undefined }, { key: "benchmark" as const, name: benchmark, color: "var(--color-text-secondary)", dash: "7 4" }, { key: "peer" as const, name: zh ? "同池等权" : "Equal-weight peer", color: "var(--color-success)", dash: "2 4" }];
  return <figure className="mt-6 border-y border-border-subtle py-4"><figcaption className="flex flex-wrap gap-5 text-xs">{lines.map(line => <span key={line.key} style={{ color: line.color }}>● {line.name}</span>)}<span className="text-text-secondary">{zh ? "净值 · USD" : "Equity · USD"}</span></figcaption><div className="overflow-x-auto"><svg viewBox="0 0 960 295" className="mt-3 w-full min-w-[540px]" role="img" aria-label={zh ? `策略、${benchmark}、同池等权真实净值曲线，${text(points[0].date)}至${text(points[points.length - 1].date)}` : `Net equity: strategy, ${benchmark}, equal-weight peer`}>
    {[0, 0.5, 1].map(ratio => { const value = low + ratio * span; return <g key={ratio}><line x1={85} x2={915} y1={y(value)} y2={y(value)} stroke="var(--color-border-subtle)"/><text x={73} y={y(value) + 4} textAnchor="end" fill="var(--color-text-secondary)" fontSize={11}>{value.toLocaleString("en-US", { maximumFractionDigits: 0 })}</text></g>; })}
    {[...lines].reverse().map(line => <path key={line.key} d={path(line.key)} fill="none" stroke={line.color} strokeWidth={line.key === "equity" ? 2.4 : 1.7} strokeDasharray={line.dash}/>)}<text x={85} y={278} fill="var(--color-text-secondary)" fontSize={11}>{text(points[0].date)}</text><text x={915} y={278} textAnchor="end" fill="var(--color-text-secondary)" fontSize={11}>{text(points[points.length - 1].date)}</text>
    </svg></div></figure>;
}

function Periods({ rows, benchmark, zh }: { rows: EvaluationObject[]; benchmark: string; zh: boolean }) {
  return <div className="overflow-x-auto"><table className="w-full min-w-[670px] text-left text-xs"><thead className="border-b border-border-subtle text-text-secondary"><tr>{[zh ? "区间" : "Period", zh ? "策略净收益" : "Net return", benchmark, zh ? "同池等权" : "Peer", "Sharpe", zh ? "最大回撤" : "Drawdown"].map(title => <th key={title} className="py-3 pr-5 font-medium">{title}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr className="border-b border-border-subtle/60" key={index}><th className="py-3 pr-5 font-normal"><p>{({ train: zh ? "历史分段 A" : "Historical section A", validation: zh ? "历史分段 B" : "Historical section B", test: zh ? "历史分段 C" : "Historical section C" } as Record<string, string>)[text(row.label)] ?? text(row.label, String(row.year ?? "—"))}</p><p className="mt-1 font-mono text-[11px] text-text-secondary">{text(row.start)} → {text(row.end)}</p>{row.status === "unavailable" ? <p className="text-warning">{zh ? "无覆盖数据" : "No covered dates"}</p> : null}</th><td className="font-mono">{pct(object(row.metrics).total_return)}</td><td className="font-mono">{pct(object(row.benchmark_metrics).total_return)}</td><td className="font-mono">{pct(object(row.peer_metrics).total_return)}</td><td className="font-mono">{number(object(row.metrics).sharpe)}</td><td className="font-mono">{pct(object(row.metrics).max_drawdown)}</td></tr>)}</tbody></table></div>;
}

function SignalStatistics({ value, zh }: { value: unknown; zh: boolean }) {
  const diagnostics = object(value), splits = object(diagnostics.splits);
  if (!Object.keys(diagnostics).length) return null;
  if (diagnostics.status === "not_applicable") return <p className="mt-5 text-xs leading-7 text-text-secondary">{zh ? "单指数择时没有横截面排序，不用个股 IC 为它评分。" : "Single-index timing has no cross-sectional ranking; stock-selection IC does not apply."}</p>;
  const rows = [[zh ? "全部成熟信号" : "All matured signals", diagnostics.all], [zh ? "历史分段 A" : "Historical section A", splits.train], [zh ? "历史分段 B" : "Historical section B", splits.validation], [zh ? "历史分段 C" : "Historical section C", splits.test]] as const;
  return <details className="group mt-5 border-t border-border-subtle pt-3"><summary className="app-touch-target flex cursor-pointer list-none items-center gap-2 text-sm font-medium"><ChevronDown size={14} className="group-open:rotate-180"/>{zh ? "Qlib 信号评价：排名是否对应下月收益" : "Qlib signals: does ranking predict next-month returns?"}</summary><p className="my-3 text-xs leading-7 text-text-secondary">{zh ? "把本期信号与实际下月开盘至再下月开盘的价格收益对应。分区只纳入结算日期已落在区间内的完整样本；Rank IC / IR 衡量排序关系，不是组合收益或夏普率。" : "Signals are paired with actual next-month open-to-open returns. Only complete labels within each interval are included; Rank IC and IR are signal statistics, not portfolio returns or Sharpe."}</p><div className="overflow-x-auto"><table className="w-full min-w-[570px] text-left text-xs"><thead className="border-b border-border-subtle text-text-secondary"><tr>{[zh ? "区间" : "Period", "IC", "Rank IC", "Rank IC / IR", zh ? "有效月份" : "Valid months", zh ? "标的样本" : "Instrument samples"].map(title => <th key={title} className="py-3 pr-4 font-medium">{title}</th>)}</tr></thead><tbody>{rows.filter(([, raw]) => Object.keys(object(raw)).length).map(([name, raw]) => { const row = object(raw); return <tr className="border-b border-border-subtle/60" key={name}><th className="py-3 pr-4 font-normal">{name}</th>{[row.ic, row.rank_ic, row.rank_ic_ir].map((value, index) => <td key={index} className="font-mono">{number(value, 4)}</td>)}<td className="font-mono">{number(row.periods, 0)}</td><td className="font-mono">{number(row.samples, 0)}</td></tr>; })}</tbody></table></div></details>;
}

function ResultDetail({ result, profile, zh, history }: { result: EvaluationObject; profile: EvaluationObject; zh: boolean; history?: React.ReactNode }) {
  if (result.status !== "available") return <div className="mt-6"><Empty>{result.reason ? reasonName(result.reason, zh) : zh ? "此方案尚无对应结果。运行失败不会借用其他方案的业绩；已经完成的方案仍可查看。" : "No matching result. Other profiles remain available if this profile fails."}</Empty></div>;
  const splits = object(result.splits), years = objects(result.by_year);
  const savedSignal = object(result.latest_signal);
  const latest = Object.keys(savedSignal).length ? savedSignal : null;
  const targetLabel = latest?.targets === null
    ? latest.action === "flat" ? (zh ? "未触发开仓，保持空仓" : "No entry; remain in cash") : (zh ? "本日不调仓，保持原持仓" : "No rebalance; retain existing positions")
    : latest && typeof latest.targets === "object"
      ? Object.entries(object(latest.targets)).map(([symbol, value]) => `${symbol} ${pct(value)}`).join(" / ") || (zh ? "全部退出，持有现金" : "Exit all positions; hold cash")
      : (zh ? "未提供目标持仓" : "Target holdings unavailable");
  return <>
    <Metrics result={result} profile={profile} zh={zh}/>
    <ActiveStudyMetrics result={result} profile={profile} zh={zh}/>
    {history}
    <StudyCurve value={result.curve} benchmark={text(profile.benchmark_symbol)} zh={zh}/>
    <section className="mt-6">
      <h3 className="text-base font-semibold">{zh ? "不同时间段是否一致" : "Performance across periods"}</h3>
      <p className="mt-2 text-xs leading-6 text-text-secondary">{text(result.evaluation_note, zh ? "固定规则的历史时间分区，不自动等于未查看过的样本外证据。" : "Calendar partitions of fixed rules are not automatically unseen out-of-sample evidence.")}</p>
      <Periods rows={["train", "validation", "test"].map(key => object(splits[key])).filter(row => Object.keys(row).length)} benchmark={text(profile.benchmark_symbol)} zh={zh}/>
      {years.length ? <details className="group mt-3"><summary className="app-touch-target flex cursor-pointer list-none items-center gap-2 text-sm"><ChevronDown size={14} className="group-open:rotate-180"/>{zh ? "展开逐年收益与回撤" : "Expand annual returns & drawdowns"}</summary><Periods rows={years} benchmark={text(profile.benchmark_symbol)} zh={zh}/></details> : null}
    </section>
    {latest && !history ? <details className="group mt-5 border-t border-border-subtle pt-3">
      <summary className="app-touch-target flex cursor-pointer list-none items-center gap-2 text-sm"><ChevronDown size={14} className="group-open:rotate-180"/>{zh ? "最近一次历史信号与目标" : "Latest historical signal and targets"}</summary>
      <p className="py-3 text-xs leading-7 text-text-secondary">{text(latest.signal_date)} {zh ? "信号 →" : "signal →"} {text(latest.trade_date)} · {targetLabel}</p>
      <p className="text-xs text-text-secondary">{zh ? "仅解释本次历史回测的目标，不是当前账户持仓或新交易建议。" : "Historical backtest targets, not current account positions or new trade instructions."}</p>
    </details> : null}
  </>;
}

function Discovery({ discovery, busy, onRun, zh }: { discovery: EvaluationObject; busy: boolean; onRun: () => void; zh: boolean }) {
  const proposals = objects(discovery.proposals), results = objects(discovery.results);
  const window = object(discovery.research_window);
  const trainingEnd = text(window.training_end, text(discovery.training_end));
  const generatedAt = text(discovery.generated_at, ""), evaluatedAt = text(discovery.evaluated_at, "");
  const lastAttempt = object(discovery.last_attempt);
  return <section className="mt-10 border-t-2 border-border-strong pt-7" aria-label={zh ? "因子探索" : "Factor exploration"}>
    <div className="flex flex-wrap items-start justify-between gap-4"><div><h2 className="flex items-center gap-2 text-xl font-semibold"><FlaskConical size={19}/>{zh ? "让 RD-Agent 提出新假说" : "New hypotheses with RD-Agent"}</h2><p className="mt-2 max-w-3xl text-sm leading-7 text-text-secondary">{zh ? "按本次研究窗口提出并冻结最多 3 条公式，再查看历史表现。所有已看历史都属于研发与回顾性评价；只有冻结后新到达、未被用于改公式的数据才能作为前瞻观察。全部提议、失败与跑输结果都会保留。" : "Propose and freeze up to three formulas using this run's research window, then inspect historical performance. All inspected history is retrospective research; prospective observation begins with new data after the formula is frozen. Failed and losing proposals remain visible."}</p></div><button type="button" disabled={busy} onClick={onRun} className="app-touch-target inline-flex items-center gap-2 rounded-md border border-[var(--color-hermes)] px-4 py-2 text-sm font-medium text-[var(--color-hermes)] disabled:cursor-wait disabled:opacity-50"><FlaskConical size={16}/>{zh ? "提出并检验最多 3 条因子" : "Propose & test up to 3 factors"}</button></div>
    {Object.keys(window).length ? <p className="mt-4 text-xs leading-7 text-text-secondary">{zh ? "本次已保存研究窗口" : "Saved research window"} · {text(window.training_start)} → {trainingEnd} · {zh ? "数据截至" : "Data through"} {text(window.data_watermark)}{window.note ? <span className="mt-1 block">{text(window.note)}</span> : null}</p> : proposals.length ? <p className="mt-4 text-xs leading-7 text-text-secondary">{zh ? "历史探索使用原窗口，训练截至" : "This historical exploration used its original training window through"} {trainingEnd}{zh ? "；没有把旧提议重新标成今天的新发现。" : ". Its proposal date is unchanged."}</p> : null}
    {generatedAt || evaluatedAt ? <p className="mt-2 text-xs leading-7 text-text-secondary">{generatedAt ? `${zh ? "原提议生成于" : "Originally proposed"} ${generatedAt.replace("T", " ").slice(0, 19)} UTC` : ""}{evaluatedAt ? ` · ${zh ? "原评价保存于" : "Evaluation saved"} ${evaluatedAt.replace("T", " ").slice(0, 19)} UTC` : ""}</p> : null}
    {discovery.status === "stale" || discovery.evaluation_status === "stale" ? <p className="mt-2 text-xs text-warning">{zh ? "保留的旧探索：其行情或计算版本与当前固定方案不同，指标和日期按原记录展示。" : "Retained exploration uses an older data or calculation version; metrics and dates remain bound to its original record."}</p> : null}
    {lastAttempt.error ? <p role="alert" className="mt-3 text-xs text-warning">{zh ? "最近一次探索未完成；原结果仍保留。" : "The latest exploration attempt failed; prior results are retained."} {reasonName(lastAttempt.error, zh)}</p> : null}
    {!proposals.length ? <p className="mt-4 text-sm leading-7 text-text-secondary">{discovery.error ? reasonName(discovery.error, zh) : zh ? "尚无已保存的因子提议。点击按钮才会调用模型，页面不会自行挖掘。" : "No saved proposals. Only an explicit click calls the model."}</p> : <><p className="mt-4 text-xs text-text-secondary">{statusName(discovery.evaluation_status ?? discovery.status, zh)} · {text(discovery.model)} · {text(discovery.reasoning_effort)} · {zh ? "参考行情截至" : "Market data through"} {trainingEnd}</p><ol className="mt-5 space-y-7">{proposals.map((proposal, index) => {
      const result = results.find(result => object(result.profile).proposal_id === proposal.id || object(result.profile).id === `rdagent:${text(proposal.id)}`);
      const test = object(object(result?.splits).test);
      const reasons = [...new Set([proposal.reason, result?.reason].filter((reason): reason is string => typeof reason === "string" && reason.length > 0))];
      return <li key={text(proposal.id, String(index))} className="border-t border-border-subtle pt-5">
        <div className="flex flex-wrap justify-between gap-3"><h3 className="text-base font-semibold">{index + 1}. {text(proposal.title, zh ? "未形成有效标题的提议" : "Untitled proposal")}</h3><span className="text-xs text-text-secondary">{statusName(result?.status === "available" ? "evaluated" : result?.status ?? proposal.status, zh)}</span></div>
        <p className="mt-3 text-sm leading-7 text-text-secondary">{text(proposal.rationale, zh ? "没有可用的研究依据说明。" : "No rationale available.")}</p>
        {proposal.expression ? <pre className="mt-3 overflow-x-auto rounded-md bg-bg-surface px-4 py-3 text-xs leading-6 text-text-primary"><code>{text(proposal.expression)}</code></pre> : null}
        {reasons.map(reason => <p key={reason} className="mt-3 break-words text-sm text-warning">{reasonName(reason, zh)}</p>)}
        {Object.keys(test).length ? <div className="mt-3"><Periods rows={[test]} benchmark={text(object(result?.profile).benchmark_symbol, "SPY")} zh={zh}/></div> : null}
        {result?.status === "available" ? <div className="mt-4"><SaveStrategyButton source={discoverySaveSource(discovery, result)} locale={zh ? "zh" : "en"} title={text(proposal.title, text(object(result.profile).name, ""))}/>{!discoverySaveSource(discovery, result) ? <p className="mt-2 text-xs text-text-secondary">{zh ? "原探索记录的来源缺失，暂不能保存该版本。" : "The original exploration run is missing; this version cannot be saved yet."}</p> : null}</div> : null}
        {result?.status === "available" ? <details className="group mt-3"><summary className="app-touch-target flex cursor-pointer list-none items-center gap-2 text-sm text-[var(--color-hermes)]"><ChevronDown size={14} className="group-open:rotate-180"/>{zh ? "展开全部历史分段结果" : "Expand all historical sections"}</summary><ResultDetail result={result} profile={object(result.profile)} zh={zh}/><SignalStatistics value={result.signal_diagnostics} zh={zh}/></details> : null}
      </li>;
    })}</ol></>}
  </section>;
}

export function StrategyStudiesView({ locale, initialReport = null }: { locale: Locale; initialReport?: StrategyStudies | null }) {
  const zh = locale === "zh";
  const [report, setReport] = useState(initialReport), [error, setError] = useState<string | null>(null);
  const [requesting, setRequesting] = useState(false), [selected, setSelected] = useState("stocks_momentum_12_2");
  const [family, setFamily] = useState("all");
  useEffect(() => { let active = true; getStrategyStudies().then(value => { if (active) { setReport(value); setError(null); } }).catch(reason => { if (active) setError(reason instanceof Error ? reason.message : "Saved study unavailable"); }); return () => { active = false; }; }, []);
  useEffect(() => {
    if (report?.status !== "updating" || error) return;
    let active = true; let timer: ReturnType<typeof setTimeout>;
    const poll = async () => { try { const next = await getStrategyStudies(); if (!active) return; setReport(next); if (next.status === "updating") timer = setTimeout(poll, 3000); } catch (reason) { if (active) setError(reason instanceof Error ? reason.message : "Saved study unavailable"); } };
    timer = setTimeout(poll, 3000); return () => { active = false; clearTimeout(timer); };
  }, [report?.status, error]);
  const run = async (discovery: boolean) => { setRequesting(true); setError(null); try { setReport(await refreshStrategyStudies(discovery)); } catch (reason) { setError(reason instanceof Error ? reason.message : "Study update failed"); } finally { setRequesting(false); } };
  const profiles = objects(report?.profiles), results = objects(report?.results);
  const families = [...new Set(profiles.map(profile => text(profile.family)))];
  const choices = profiles.filter(profile => family === "all" || profile.family === family);
  const profile = choices.find(profile => profile.id === selected) ?? choices.find(profile => profile.id === "stocks_momentum_12_2") ?? choices[0];
  const result = results.find(result => object(result.profile).id === profile?.id) ?? {};
  const busy = requesting || report?.status === "updating";
  return <div>
    <div className="flex flex-wrap items-start justify-between gap-5"><div><h2 className="text-xl font-semibold">{zh ? "先确定用途，再看回测" : "Match the method to its purpose"}</h2><p className="mt-2 max-w-3xl text-sm leading-7 text-text-secondary">{zh ? "个股选股、跨资产配置、指数趋势和短期回归分别定义规则。方案在比较前固定，不自动选收益最高的一项。" : "Stock selection, asset allocation, index trends and short-term reversion use distinct fixed rules. The page does not automatically select the highest return."}</p></div><button type="button" disabled={busy} onClick={() => void run(false)} className="app-touch-target inline-flex items-center gap-2 rounded-md bg-[var(--color-hermes)] px-5 py-2 text-sm font-medium text-bg-base disabled:cursor-wait disabled:opacity-60"><RefreshCw size={16} className={busy ? "motion-safe:animate-spin" : ""}/>{busy ? (zh ? "正在计算…" : "Evaluating…") : (zh ? "更新固定研究方案" : "Evaluate fixed profiles")}</button></div>
    <div className="my-5 flex flex-wrap gap-x-5 gap-y-2 text-xs text-text-secondary" role="status"><span>{statusName(report?.status ?? "not_started", zh)}</span>{report?.updated_at ? <span>{zh ? "保存于" : "Saved"} {report.updated_at.replace("T", " ").slice(0, 19)} UTC</span> : null}{object(report?.source).data_end ? <span>Futu · {text(object(report?.source).data_start)} → {text(object(report?.source).data_end)}</span> : null}{busy ? <span>{text(report?.progress, zh ? "已完成的方案保持可读。" : "Completed profiles remain readable.")}</span> : null}</div>
    {error || report?.error ? <p role="alert" className="my-5 rounded-md border border-warning/50 px-4 py-3 text-sm leading-7 text-warning">{error ?? report?.error}</p> : null}
    {!error && report?.error && report.status !== "stale" ? <p className="-mt-2 mb-5 text-xs leading-7 text-text-secondary">{zh ? "上方是这次保存的历史运行记录中的错误，不是打开页面重新回测产生的错误。已成功的方案仍可查看；新增相对基准统计不会把当时的失败改写为成功。" : "The error above belongs to this saved historical run, not a backtest started by opening the page. Successful profiles remain available; supplemental active metrics do not rewrite the original failure."}</p> : null}
    {report?.status === "stale" ? <p className="my-5 border-l-2 border-warning pl-4 text-sm leading-7 text-warning">{zh ? "下面是旧协议或旧代码生成的历史记录，不代表当前实现；显式更新后才能获得当前方案的对应评价。" : "These saved results use an older protocol or implementation. Explicitly update to evaluate the current profiles."}</p> : null}
    {!profiles.length ? <Empty>{error ? (zh ? "暂时无法读取研究方案，未填入示例数据。" : "Study profiles unavailable; no sample data substituted.") : report ? (zh ? "尚未保存研究方案与结果，运行后在这里查看。" : "No saved profiles or results yet.") : (zh ? "正在读取已保存研究…" : "Loading saved studies…")}</Empty> : <>
      <StudyComparison profiles={profiles} results={results} selected={text(profile?.id)} onSelect={id => { setFamily("all"); setSelected(id); }} zh={zh}/>
      <div className="mb-6 grid gap-4 border-y border-border-subtle py-5 sm:grid-cols-[minmax(160px,1fr)_minmax(240px,3fr)]"><label className="space-y-2 text-xs text-text-secondary"><span>{zh ? "研究用途" : "Research purpose"}</span><select aria-label={zh ? "研究用途" : "Research purpose"} value={family} onChange={event => setFamily(event.target.value)} className="app-touch-target block w-full rounded-md border border-border-strong bg-bg-base px-3 text-sm text-text-primary"><option value="all">{zh ? "全部用途" : "All purposes"}</option>{families.map(value => <option key={value} value={value}>{familyName(value, zh)}</option>)}</select></label><label className="space-y-2 text-xs text-text-secondary"><span>{zh ? "固定方案（未按收益排名）" : "Fixed profile (not ranked by return)"}</span><select aria-label={zh ? "固定研究方案" : "Fixed research profile"} value={text(profile?.id)} onChange={event => setSelected(event.target.value)} className="app-touch-target block w-full rounded-md border border-border-strong bg-bg-base px-3 text-sm text-text-primary">{choices.map(profile => <option key={text(profile.id)} value={text(profile.id)}>{text(profile.name)}</option>)}</select></label></div>
      {profile ? <><ProfileProtocol profile={Object.keys(object(result.profile)).length ? object(result.profile) : profile} result={result} zh={zh}/>{result.status === "available" ? <div className="mt-5 flex flex-wrap items-center gap-4"><SaveStrategyButton source={studySaveSource(report?.run_id, object(result.profile).id ?? profile.id, result.status)} locale={locale} title={text(object(result.profile).name, text(profile.name, ""))}/><p className="text-xs leading-6 text-text-secondary">{zh ? "保存当前规则和参数；到“我的策略”验证后，再决定是否启用模拟。" : "Save this fixed recipe, validate it in My strategies, then decide whether to enable paper simulation."}</p></div> : null}<ResultDetail result={result} profile={Object.keys(object(result.profile)).length ? object(result.profile) : profile} zh={zh} history={<StudyHistory key={`${report?.run_id}:${text(profile.id)}`} runId={report?.run_id ?? null} profile={Object.keys(object(result.profile)).length ? object(result.profile) : profile} result={result} zh={zh}/>}/><SignalStatistics value={result.signal_diagnostics} zh={zh}/></> : null}
    </>}
    <Discovery discovery={object(report?.discovery)} busy={busy} onRun={() => void run(true)} zh={zh}/>
    {report ? <details className="mt-8 border-t border-border-subtle pt-3"><summary className="app-touch-target cursor-pointer text-xs text-text-secondary">{zh ? "数据限制与本次记录" : "Data limits & saved run"}</summary><div className="space-y-2 py-3 text-xs leading-7 text-text-secondary">{strings(report.warnings).map((warning, index) => <p key={index}>{warning}</p>)}<p className="break-all font-mono">{report.run_id}</p><p className="break-all font-mono">{zh ? "协议指纹" : "Protocol digest"}: {report.protocol_digest}</p></div></details> : null}
  </div>;
}
