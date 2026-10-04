"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, ArrowUpRight, RefreshCw } from "lucide-react";
import { localizePath, type Locale } from "@/lib/locale";
import {
  getFactorScorecards, refreshFactorScorecards, type FactorScorecards,
} from "@/lib/factorScorecards";
import { StrategyStudiesView } from "./StrategyStudiesView";
import {
  getPaperEvaluation, getResearchEvaluation, object, objects, refreshPaperEvaluation,
  refreshResearchEvaluation, strings, valueNumber,
  type EvaluationObject, type PaperEvaluation, type ResearchEvaluation,
} from "@/lib/researchEvaluation";

type Tab = "studies" | "reference" | "rolling" | "increment" | "paper" | "scorecards";
const TABS: Tab[] = ["studies", "reference", "rolling", "increment", "paper", "scorecards"];
const LABELS: Record<string, string> = {
  momentum: "动量", volatility: "低波动", liquidity: "流动性", rsi: "RSI 反转",
  macd: "MACD", agent_candidate_wave2_sceneb_mom20_v3: "20 日动量（已登记版本）",
  paper_reversal_momentum_proxy_v2: "反转与长期动量因子",
  cross_sectional_top_n: "三因子 Top-3", mean_reversion_top_n: "三因子反向 Top-3",
  reversal_momentum: "月频反转与动量多空",
  drift_regime_reversal_top_n_v1: "漂移状态反转（草稿）",
};
const text = (value: unknown, missing = "—") => typeof value === "string" && value ? value : missing;
const label = (key: unknown, zh: boolean) => {
  const raw = text(key);
  const id = raw.replace(/^(factor|strategy):/, "");
  return zh ? LABELS[id] ?? (id.startsWith("candidate::") ? "当前研究因子" : id) : id;
};
const number = (value: unknown, digits = 3) => valueNumber(value)?.toFixed(digits) ?? "—";
const pct = (value: unknown) => valueNumber(value) === null ? "—" : `${(valueNumber(value)! * 100).toFixed(2)}%`;
const points = (value: unknown) => valueNumber(value) === null ? "—" : `${valueNumber(value)!.toFixed(2)}%`;
const money = (value: unknown) => valueNumber(value) === null ? "—" : `$${valueNumber(value)!.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
const statusName = (status: unknown, zh: boolean) => {
  const names: Record<string, string> = { ready: "已完成", available: "已完成", partial: "部分完成", failed: "未完成", stale: "旧版本结果", unavailable: "数据或样本不足", not_evaluated: "未评估", not_implemented: "尚无执行器", not_started: "尚未运行", updating: "正在更新" };
  return zh ? names[text(status)] ?? text(status) : text(status);
};

function useSavedReport<T extends { status: string }>(read: () => Promise<T>, enabled: boolean, initial: T | null = null) {
  const [report, setReport] = useState<T | null>(initial);
  const [error, setError] = useState<string | null>(null);
  const [requesting, setRequesting] = useState(false);
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    read().then(result => { if (active) { setReport(result); setError(null); } })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : "Saved result unavailable"); });
    return () => { active = false; };
  }, [enabled, read]);
  useEffect(() => {
    if (!enabled || report?.status !== "updating" || error) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const result = await read();
        if (!active) return;
        setReport(result);
        if (result.status === "updating") timer = setTimeout(poll, 3000);
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Saved result unavailable");
      }
    };
    timer = setTimeout(poll, 3000);
    return () => { active = false; clearTimeout(timer); };
  }, [enabled, read, report?.status, error]);
  const update = async (action: () => Promise<T>) => {
    setRequesting(true);
    setError(null);
    try { setReport(await action()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Update failed"); }
    finally { setRequesting(false); }
  };
  return { report, error, update, busy: requesting || (report?.status === "updating" && !error) };
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="rounded-lg border border-dashed border-border-strong px-5 py-8 text-sm leading-7 text-text-secondary">{children}</div>;
}

function MetricTable({ rows, zh }: { rows: { name: string; metrics: EvaluationObject }[]; zh: boolean }) {
  return <div className="overflow-x-auto"><table className="w-full min-w-[500px] text-left text-sm">
    <thead className="border-b border-border-subtle text-xs text-text-secondary"><tr>
      {[zh ? "评价对象" : "Portfolio", zh ? "总收益" : "Return", zh ? "年化收益" : "Annual return", "Sharpe", zh ? "最大回撤" : "Drawdown"].map(name => <th key={name} className="py-3 pr-5 font-medium">{name}</th>)}
    </tr></thead><tbody>{rows.map(row => <tr key={row.name} className="border-b border-border-subtle/60">
      <th className="py-4 pr-5 font-medium">{row.name}</th><td className="font-mono">{pct(row.metrics.total_return)}</td>
      <td className="font-mono">{pct(row.metrics.annualized_return)}</td><td className="font-mono">{number(row.metrics.sharpe, 4)}</td>
      <td className="font-mono">{pct(valueNumber(row.metrics.max_drawdown) === null ? null : Math.abs(valueNumber(row.metrics.max_drawdown)!))}</td>
    </tr>)}</tbody>
  </table></div>;
}

type PlotPoint = { date: string; equity: number | null; benchmark: number | null };
function curvePoints(value: unknown): PlotPoint[] {
  return objects(value).filter(row => typeof row.date === "string" && Number.isFinite(Date.parse(row.date))).map(row => ({
    date: text(row.date), equity: valueNumber(row.equity), benchmark: valueNumber(row.benchmark),
  }));
}

function Curve({ points: data, mainName, comparisonName = "QQQ", percent = false, zh }: {
  points: PlotPoint[]; mainName: string; comparisonName?: string; percent?: boolean; zh: boolean;
}) {
  if (!data.length) return <Empty>{zh ? "尚无可绘制的真实曲线。" : "No saved curve is available."}</Empty>;
  const points = [...data].sort((a, b) => Date.parse(a.date) - Date.parse(b.date));
  const values = points.flatMap(point => [point.equity, point.benchmark]).filter((value): value is number => value !== null);
  if (!values.length) return <Empty>{zh ? "净值尚不可核对，曲线留空。" : "Curve values are unavailable."}</Empty>;
  const minimum = Math.min(...values), maximum = Math.max(...values);
  const padding = (maximum - minimum) * 0.08 || Math.max(Math.abs(maximum) * 0.01, 1);
  const low = minimum - padding, high = maximum + padding;
  const first = Date.parse(points[0].date), last = Date.parse(points[points.length - 1].date);
  const x = (date: string) => 76 + (Date.parse(date) - first) / (last - first || 1) * 792;
  const y = (value: number) => 20 + (high - value) / (high - low) * 218;
  const path = (key: "equity" | "benchmark") => {
    let drawing = false;
    return points.map(point => {
      const value = point[key];
      if (value === null) { drawing = false; return ""; }
      const command = drawing ? "L" : "M"; drawing = true;
      return `${command}${x(point.date).toFixed(2)},${y(value).toFixed(2)}`;
    }).join(" ");
  };
  return <figure className="mt-6 rounded-lg border border-border-subtle bg-bg-base p-4">
    <figcaption className="mb-3 flex flex-wrap gap-5 text-xs"><span className="text-[var(--color-hermes)]">● {mainName}</span><span className="text-text-secondary">● {comparisonName}</span><span className="text-text-secondary">{percent ? (zh ? "累计变化（%）" : "Change (%)") : (zh ? "净值（USD）" : "Equity (USD)")}</span></figcaption>
    <svg viewBox="0 0 900 280" className="w-full" role="img" aria-label={`${mainName} / ${comparisonName}, ${points[0].date} – ${points[points.length - 1].date}`}>
      {[0, 0.5, 1].map(ratio => { const value = low + ratio * (high - low); return <g key={ratio}>
        <line x1={76} x2={868} y1={y(value)} y2={y(value)} stroke="var(--color-border-subtle)"/>
        <text x={66} y={y(value) + 4} textAnchor="end" fill="var(--color-text-secondary)" fontSize="11">{percent ? `${value.toFixed(1)}%` : value.toLocaleString("en-US", { maximumFractionDigits: 0 })}</text>
      </g>; })}
      <path d={path("benchmark")} stroke="var(--color-text-secondary)" strokeWidth="1.7" fill="none" strokeDasharray="5 4"/>
      <path d={path("equity")} stroke="var(--color-hermes)" strokeWidth="2.5" fill="none"/>
      {points.length <= 40 ? points.filter(point => point.equity !== null).map(point => <circle key={point.date} cx={x(point.date)} cy={y(point.equity!)} r={3} fill="var(--color-hermes)"><title>{point.date}: {point.equity!.toFixed(2)}</title></circle>) : null}
      <text x={76} y={264} fill="var(--color-text-secondary)" fontSize="11">{points[0].date}</text>
      <text x={868} y={264} textAnchor="end" fill="var(--color-text-secondary)" fontSize="11">{points[points.length - 1].date}</text>
    </svg>
  </figure>;
}

function YearTable({ value, zh }: { value: unknown; zh: boolean }) {
  const rows = objects(value);
  if (!rows.length) return null;
  return <details className="mt-5 border-t border-border-subtle pt-3"><summary className="app-touch-target cursor-pointer py-2 text-sm font-medium">{zh ? "逐年表现" : "Yearly results"}</summary>
    <div className="overflow-x-auto"><table className="w-full min-w-[440px] text-left text-sm"><thead className="text-xs text-text-secondary"><tr>{[zh ? "年份" : "Year", zh ? "策略收益" : "Return", "QQQ", "Sharpe", zh ? "最大回撤" : "Drawdown"].map(name => <th key={name} className="py-3">{name}</th>)}</tr></thead><tbody>{rows.map(row => <tr key={text(String(row.year))} className="border-t border-border-subtle"><td className="py-3">{String(row.year)}</td><td className="font-mono">{pct(object(row.metrics).total_return)}</td><td className="font-mono">{pct(object(row.benchmark_metrics).total_return)}</td><td className="font-mono">{number(object(row.metrics).sharpe)}</td><td className="font-mono">{pct(object(row.metrics).max_drawdown)}</td></tr>)}</tbody></table></div>
  </details>;
}

function ReferenceSection({ report, selected, onSelect, zh }: { report: ResearchEvaluation; selected: string; onSelect: (key: string) => void; zh: boolean }) {
  const reference = object(report.reference), rows = objects(reference.rows);
  const universe = strings(reference.universe).length ? strings(reference.universe) : strings(object(report.source).universe);
  const universeNames: Record<string, string> = { SPY: "标普500", QQQ: "纳斯达克100", IWM: "罗素2000小盘股", DIA: "道琼斯工业平均", VTI: "美国全市场", EFA: "发达市场除美加", EEM: "新兴市场", TLT: "美国长期国债", GLD: "黄金", SLV: "白银", USO: "原油期货", VNQ: "美国房地产", XLK: "美国科技板块", XLF: "美国金融板块", XLE: "美国能源板块", XLV: "美国医疗保健板块", XLI: "美国工业板块", XLY: "美国可选消费板块", XLP: "美国必需消费板块", XLU: "美国公用事业板块", XLB: "美国原材料板块", XLC: "美国通信服务板块" };
  const active = rows.find(row => row.key === selected) ?? rows[0];
  if (!active) return <Empty>{report.key ? (zh ? "这项研究单独进行滚动和因子增量评价。固定参考页仅覆盖登记因子与策略模板。" : "This research has separate rolling and incremental evaluation.") : (zh ? "尚无固定规则参考结果。点击上方按钮后才会运行；打开页面不会启动回测。" : "Run an evaluation explicitly to create fixed-rule reference results.")}</Empty>;
  const daily = rows.filter(row => row.frequency !== "monthly").map(row => row.reason === "draft_has_no_executable_strategy" ? { ...row, status: "not_implemented" } : row);
  const monthly = rows.filter(row => row.frequency === "monthly");
  return <section className="space-y-6">
    <div><h2 className="text-xl font-semibold">{zh ? "原 ETF 配置的诊断记录" : "Original ETF configuration diagnostics"}</h2><p className="mt-2 max-w-4xl text-sm leading-7 text-text-secondary">{zh ? "保留此前每天选 3 只 ETF、次日开盘成交的固定用法，便于追溯。它只衡量这套 ETF 排名规则，不能代表个股动量、指数择时或全部因子的有效性；按适用场景定义的研究请看“按用途研究”。QQQ 是同期对照，不是统一的合格线。" : "This preserves the original daily Top-3 ETF rule for diagnosis. It does not represent stock momentum, index timing or every factor's effectiveness. Purpose-specific methods are in Purpose-led studies; QQQ is a comparison, not a pass criterion."}</p><p className="mt-3 text-xs leading-7 text-text-secondary">{zh ? "实际 ETF 范围：" : "Actual ETF universe: "}{universe.length ? universe.map(symbol => `${symbol}${zh && universeNames[symbol] ? `（${universeNames[symbol]}）` : ""}`).join(" · ") : (zh ? "该历史记录未提供标的名单，不能推定。" : "The saved record does not include its universe.")}</p><p className="mt-2 text-xs leading-6 text-text-secondary">{zh ? "当前 MACD 跨标的比较使用价格归一化柱值；旧版本结果需更新后才能用于当前实现。" : "Current MACD cross-instrument rankings use price-normalized histogram values; old results need an explicit update."}</p></div>
    <div className="overflow-x-auto"><table className="w-full min-w-[680px] text-left text-sm"><thead className="border-b border-border-subtle text-xs text-text-secondary"><tr>{[zh ? "参考组合" : "Reference", zh ? "扣费后总收益" : "Net return", zh ? "同期 QQQ" : "Same-window QQQ", "Sharpe", zh ? "最大回撤" : "Drawdown", zh ? "状态" : "Status"].map(name => <th key={name} className="py-3 pr-4 font-medium">{name}</th>)}</tr></thead><tbody>{daily.map(row => <tr key={text(row.key)} className={`border-b border-border-subtle/60 ${row.key === active.key ? "bg-bg-surface-muted/50" : ""}`}><th className="pr-4 text-left font-medium"><button type="button" className="app-touch-target py-3 text-left hover:text-[var(--color-hermes)]" onClick={() => onSelect(text(row.key))}>{label(row.key, zh)}</button></th><td className="font-mono">{pct(object(row.metrics).total_return)}</td><td className="font-mono">{pct(object(row.benchmark_metrics).total_return)}</td><td className="font-mono">{number(object(row.metrics).sharpe)}</td><td className="font-mono">{pct(object(row.metrics).max_drawdown)}</td><td className="text-xs text-text-secondary">{statusName(row.status, zh)}</td></tr>)}</tbody></table></div>
    {monthly.length ? <p className="text-xs leading-6 text-text-secondary">{zh ? "月频多空毛收益未计借券和成交成本，不放入上方扣费后对照表；可在下方选择查看。" : "Monthly long-short gross returns omit borrowing and trading costs and are kept outside the net-return table."}</p> : null}
    <div className="border-t border-border-subtle pt-6"><label className="flex flex-wrap items-center gap-3 text-sm font-medium">{zh ? "查看具体用法" : "Inspect a reference"}<select value={text(active.key)} onChange={event => onSelect(event.target.value)} className="app-touch-target max-w-full rounded-md border border-border-strong bg-bg-base px-3 font-normal">{rows.map(row => <option key={text(row.key)} value={text(row.key)}>{label(row.key, zh)}{row.frequency === "monthly" ? (zh ? " · 月频毛收益" : " · monthly gross") : ""}</option>)}</select></label><p className="mt-3 text-sm leading-7 text-text-secondary">{text(active.rule)}</p>
      {active.reason ? <p className="mt-2 text-sm text-warning">{active.reason === "draft_has_no_executable_strategy" ? (zh ? "该研究仍是草稿，尚无对应执行器；不是行情缺失。" : "This draft has no executable strategy; market data is not the blocker.") : text(active.reason)}</p> : null}
      {active.status === "available" ? <><MetricTable zh={zh} rows={[{ name: label(active.key, zh), metrics: object(active.metrics) }, { name: "QQQ", metrics: object(active.benchmark_metrics) }]}/><p className="mt-3 text-xs leading-6 text-text-secondary">{active.frequency === "monthly" ? (zh ? "月频多空毛收益；QQQ 保留其实际入场成本，不能把这组差异解读为净优势。" : "Monthly gross long-short results; QQQ includes entry costs, so differences are not net alpha.") : (zh ? "双方同一窗口，佣金 1 bp、滑点 5 bp，现金利息和 Sharpe 无风险收益按 0。QQQ 只在首日买入；零波动时 Sharpe 留空。" : "Same window, 1 bp commission and 5 bp slippage. Cash and risk-free returns are zero. QQQ enters once; zero-volatility Sharpe is undefined.")}</p><Curve points={curvePoints(active.curve)} mainName={label(active.key, zh)} zh={zh}/><YearTable value={active.by_year} zh={zh}/></> : <Empty>{zh ? "没有可核验的结果，不能用别的策略填入这些指标。" : "No matching result; another strategy's metrics cannot substitute."}</Empty>}
    </div>
  </section>;
}

function FoldTable({ rows, paired, zh }: { rows: EvaluationObject[]; paired: boolean; zh: boolean }) {
  if (!rows.length) return null;
  return <div className="mt-6 overflow-x-auto"><table className="w-full min-w-[760px] text-left text-xs"><thead className="border-b border-border-subtle text-text-secondary"><tr>{[zh ? "分段" : "Fold", zh ? "训练区间" : "Training", zh ? "验证区间" : "Validation", zh ? "测试区间" : "Test", "Rank IC", ...(paired ? [zh ? "加入后 IC" : "Added IC"] : []), zh ? "测试样本" : "Test samples"].map(name => <th key={name} className="py-3 pr-4 font-medium">{name}</th>)}</tr></thead><tbody>{rows.map((row, index) => { const segments = object(row.segments); const tests = object(segments.test); return <tr key={index} className="border-b border-border-subtle/60"><td className="py-4 pr-4">{index + 1}<p className="mt-1 text-text-secondary">{statusName(row.status, zh)}</p></td>{["train", "valid", "test"].map(part => <td key={part} className="pr-4 font-mono leading-6">{text(object(segments[part]).start)}<br/>{text(object(segments[part]).end)}</td>)}<td className="font-mono">{number(object(object(row.baseline_signals).test).rank_ic, 4)}</td>{paired ? <td className="font-mono">{number(object(object(row.augmented_signals).test).rank_ic, 4)}</td> : null}<td className="font-mono">{number(tests.n_rows, 0)}<p className="mt-1 text-text-secondary">{number(tests.n_dates, 0)} {zh ? "日" : "days"}</p></td></tr>; })}</tbody></table></div>;
}

function SelectionPartitions({ value, zh }: { value: unknown; zh: boolean }) {
  const partitions = object(value);
  if (!Object.keys(partitions).length) return null;
  return <section className="my-6 rounded-lg border border-border-strong p-4 sm:p-5">
    <h3 className="text-base font-semibold">{zh ? "按原数据截止日期分开复核" : "Review periods before and after the recorded data cutoff"}</h3>
    <p className="mt-2 text-xs leading-6 text-text-secondary">{zh ? "日期在原数据截止日之后，不代表数据从未参与研究；缺少冻结与数据使用边界证据时，仍属回顾性复核。这两区只计算预测分数与后续收益的关系，未计算独立扣费后组合表现。" : "Dates after the recorded data cutoff do not prove unseen data. Without frozen research and data-use boundaries this is retrospective review, with signal statistics only and no separate net-cost portfolio returns."}</p>
    <div className="mt-3 overflow-x-auto"><table className="w-full min-w-[570px] text-left text-xs"><thead className="border-b border-border-subtle text-text-secondary"><tr>{[zh ? "分区" : "Partition", zh ? "覆盖日期" : "Dates", zh ? "交易日 / 样本" : "Days / rows", "Rank IC", zh ? "加入后 IC" : "Added IC", zh ? "独立净收益" : "Net return"].map(name => <th key={name} className="py-3 pr-3 font-medium">{name}</th>)}</tr></thead><tbody>{(["historical", "post_selection_reanalysis"] as const).map(key => {
      // Legacy field names cannot establish an unseen research holdout.
      const row = object(partitions[key] ?? (key === "post_selection_reanalysis" ? partitions.forward_oos : undefined));
      return <tr key={key} className="border-b border-border-subtle/60"><th className="py-4 pr-3 text-left font-medium">{key === "historical" ? (zh ? "原数据截止日及之前" : "Before the recorded cutoff") : (zh ? "原数据截止日之后" : "After the recorded cutoff")}</th><td className="pr-3 font-mono leading-6">{text(row.start)}<br/>{text(row.end)}</td><td className="font-mono">{number(row.n_dates, 0)} / {number(row.n_rows, 0)}</td><td className="font-mono">{number(object(row.baseline_signal_metrics).rank_ic, 4)}</td><td className="font-mono">{number(object(row.augmented_signal_metrics).rank_ic, 4)}</td><td className="text-text-secondary">{zh ? "未计算" : "Not computed"}</td></tr>;
    })}</tbody></table></div>
  </section>;
}

function PredictionCoverage({ cases, zh }: { cases: { name: string; result: EvaluationObject }[]; zh: boolean }) {
  const gaps = cases.map(row => ({ ...row, missing: strings(object(row.result.prediction_coverage).missing_dates) })).filter(row => row.missing.length);
  return <>{gaps.map(row => <div key={row.name} className="my-4 rounded-lg border border-warning/50 px-4 py-3 text-sm leading-7 text-warning"><p>{row.name} · {zh ? `${row.missing.length} 个交易日没有测试预测，未计算跨缺口的组合收益。信号统计仍可查看。` : `${row.missing.length} test prediction dates are missing; a portfolio is not simulated across those gaps.`}</p><details><summary className="cursor-pointer py-2 text-xs">{zh ? "查看缺失日期" : "Missing dates"}</summary><p className="break-words font-mono text-[11px]">{row.missing.join(", ")}</p></details></div>)}</>;
}

function RollingSection({ report, selectedFactor, onSelect, incremental, zh }: {
  report: ResearchEvaluation; selectedFactor: string; onSelect: (key: string) => void; incremental: boolean; zh: boolean;
}) {
  const rolling = object(report.rolling), methodology = object(rolling.methodology);
  const comparisons = objects(rolling.comparisons);
  const comparison = comparisons.find(row => row.factor_id === selectedFactor) ?? comparisons[0];
  if (!Object.keys(rolling).length || (!objects(rolling.folds).length && !comparisons.length)) return <Empty>{zh ? "滚动验证尚未得到可用结果。已完成的固定参考会继续保留，不把它冒充样本外验证。" : "Rolling results are not available. Completed fixed references remain separate."}</Empty>;
  if (incremental && !comparison) return <Empty>{zh ? "尚无完成的同样本因子增量对照。" : "No paired factor-contribution result is available."}</Empty>;
  const focusedResearch = Boolean(report.key && comparison);
  const portfolio = incremental || focusedResearch ? object(comparison?.augmented) : object(rolling.baseline);
  const baseline = object(comparison?.baseline);
  const folds = incremental || focusedResearch ? objects(comparison?.folds) : objects(rolling.folds);
  const partitions = object(incremental || focusedResearch ? comparison?.partitions : rolling.partitions);
  return <section>
    <h2 className="text-xl font-semibold">{incremental ? (zh ? "加上这个因子，究竟改变了什么" : "What changes when this factor is added?") : (zh ? "按时间向前滚动验证" : "Walk forward through time")}</h2>
    <p className="mt-3 max-w-4xl text-sm leading-7 text-text-secondary">{zh ? "模型只用训练段估计参数和标准化，验证段与测试段分开。每段重新训练后预测后面的测试数据；测试预测统一交给实际撮合引擎，按次日开盘执行。" : "Model parameters and normalization are fitted on training data only. Validation and later test periods stay separate; test forecasts execute at the next open."}</p>
    <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-xs text-text-secondary">{[[zh ? "训练" : "Train", methodology.train_days], [zh ? "验证" : "Validation", methodology.valid_days], [zh ? "测试 / 步长" : "Test / step", methodology.test_days], [zh ? "区间间隔" : "Gap", methodology.purge_days]].map(([name, value]) => <span key={String(name)}>{String(name)} <strong className="font-mono font-normal text-text-primary">{number(value, 0)}</strong> {zh ? "交易日" : "sessions"}</span>)}<span>Qlib · {text(methodology.model)}</span></div>
    <p className="mt-4 rounded-lg border border-border-subtle px-4 py-3 text-xs leading-6 text-text-secondary">{zh ? "这是滚动模型测试，不证明公式发现过程已做到样本外。旧公式筛选时期的回放只算历史复核；后续日期也需要真实积累，不能由旧回测代替。" : "Rolling model tests are not proof of out-of-sample formula discovery. Replaying the original selection period remains historical review."}{rolling.selection_end ? ` ${zh ? "原记录的数据截止日期（不证明公式已在当时冻结）" : "Original recorded data cutoff (not a proven formula freeze)"} ${text(rolling.selection_end).slice(0, 10)}。` : ""}</p>
    <SelectionPartitions value={partitions} zh={zh}/>
    {Object.keys(partitions).length ? <h3 className="mb-3 text-sm font-semibold text-warning">{zh ? "以下为全部测试时段汇总，包含历史复核时段，不是前向区间收益" : "Whole-test-period aggregate, including historical review — not forward-period returns"}</h3> : null}
    {comparison?.duplicate_of && (incremental || focusedResearch) ? <div className="my-4 rounded-lg border border-warning/50 px-4 py-3 text-sm leading-7 text-warning">{zh ? `这项特征与 ${label(comparison.duplicate_of, zh)} 在共同样本上完全重复，不是新增信息。` : `This feature duplicates ${label(comparison.duplicate_of, false)} on the paired samples.`}<p className="mt-1 text-xs">{text(comparison.note, zh ? "重复列会改变 Ridge 的有效正则化，指标变化不能解释为发现了新的信号。" : "Duplicating a column changes Ridge regularization, not the information available.")}</p></div> : null}
    <PredictionCoverage cases={[{ name: zh ? "原基线" : "Baseline", result: incremental ? baseline : portfolio }, ...(incremental ? [{ name: zh ? "加入后" : "Augmented", result: portfolio }] : [])]} zh={zh}/>
    {incremental ? <>
      <label className="mt-6 flex flex-wrap items-center gap-3 text-sm font-medium">{zh ? "待加入的因子" : "Added factor"}<select className="app-touch-target max-w-full rounded-md border border-border-strong bg-bg-base px-3 font-normal" value={text(comparison?.factor_id)} onChange={event => onSelect(event.target.value)}>{comparisons.map(row => <option key={text(row.factor_id)} value={text(row.factor_id)}>{label(row.factor_id, zh)}</option>)}</select></label>
      {comparison ? <><p className="mt-3 text-xs leading-6 text-text-secondary">{zh ? "前后严格使用同样的样本、区间与成本。基线" : "Matched samples, windows and costs. Baseline"} · {strings(comparison.baseline_features).map(key => label(key, zh)).join(" + ")}<br/>{zh ? "加入后" : "Augmented"} · {strings(comparison.augmented_features).map(key => label(key, zh)).join(" + ")}</p><MetricTable zh={zh} rows={[{ name: zh ? "原基线模型" : "Baseline model", metrics: object(baseline.metrics) }, { name: zh ? "加入该因子" : "With factor", metrics: object(portfolio.metrics) }, { name: "QQQ", metrics: object(portfolio.benchmark_metrics) }]}/><dl className="my-5 grid gap-4 sm:grid-cols-3">{[[zh ? "总收益变化（百分点）" : "Return change (pp)", valueNumber(object(comparison.delta).total_return) === null ? "—" : number(valueNumber(object(comparison.delta).total_return)! * 100, 2)], [zh ? "Sharpe 变化" : "Sharpe change", number(object(comparison.delta).sharpe, 4)], [zh ? "回撤变化（百分点）" : "Drawdown change (pp)", valueNumber(object(comparison.delta).max_drawdown) === null ? "—" : number(valueNumber(object(comparison.delta).max_drawdown)! * 100, 2)]].map(([name, value]) => <div key={name} className="border-l border-border-strong pl-4"><dt className="text-xs text-text-secondary">{name}</dt><dd className="mt-2 font-mono text-xl">{value}</dd></div>)}</dl><p className="text-xs text-text-secondary">{zh ? "变化为加入后减去加入前；回撤变化为负才表示回撤减小。单次增量结果不构成因果或未来收益保证。" : "Delta is augmented minus baseline; a negative drawdown delta means a smaller drawdown."}</p></> : null}
    </> : <div className="mt-5"><MetricTable zh={zh} rows={[{ name: focusedResearch ? (zh ? "含当前研究因子的模型" : "Model with research factor") : (zh ? "三因子基线模型" : "Three-factor baseline"), metrics: object(portfolio.metrics) }, { name: "QQQ", metrics: object(portfolio.benchmark_metrics) }]}/></div>}
    {["available", "ready", "partial"].includes(text(portfolio.status)) && curvePoints(portfolio.curve).length ? <Curve points={curvePoints(portfolio.curve)} mainName={incremental ? (zh ? "加入因子后" : "With factor") : (zh ? "滚动测试组合" : "Rolling portfolio")} zh={zh}/> : <p className="mt-5 text-sm text-warning">{text(portfolio.reason, zh ? "这一组尚无可用组合结果。" : "No usable portfolio result for this case.")}</p>}
    <FoldTable rows={folds} paired={incremental || focusedResearch} zh={zh}/>
    {incremental && comparison?.reason ? <p className="mt-3 text-xs text-warning">{text(comparison.reason)}</p> : null}
  </section>;
}

function cleanCitations(value: unknown) {
  return text(value, "").replace(/\[(coverage|performance|costs|windows|signals|prediction)\]/g, "").trim();
}

function PaperSection({ report, zh }: { report: PaperEvaluation; zh: boolean }) {
  const facts = object(report.facts), metrics = object(facts.metrics), period = object(facts.period);
  const analysis = object(report.analysis), windows = object(facts.window_comparison);
  const capitalReturn = metrics.return_method === "net_profit_over_allocated_capital";
  const plot = objects(facts.observation_series).map(row => ({ date: text(row.date), equity: valueNumber(row.sleeve_pct), benchmark: capitalReturn ? null : valueNumber(row.spy_pct) }));
  return <section>
    <h2 className="text-xl font-semibold">{zh ? "已发生的模拟运行，分清变化与原因" : "Review observed paper performance"}</h2>
    <p className="mt-3 text-sm leading-7 text-text-secondary" data-testid="paper-evidence-status">
      {zh ? "事实记录：" : "Facts: "}{report.fact_archive_status === "archived"
        ? (zh ? "已单独封存，AI 解读失败也会保留。" : "Archived separately and retained if AI interpretation fails.")
        : report.fact_archive_status === "legacy_not_separately_archived"
          ? (zh ? "历史记录尚未单独封存。" : "Legacy record, not separately archived.")
          : (zh ? "尚无可核对的独立事实包。" : "No independently verifiable fact packet yet.")}
      {" "}{zh ? "AI 解读：" : "AI interpretation: "}{report.interpretation_status === "available"
        ? (zh ? "已保存。" : "Saved.")
        : report.interpretation_status === "failed"
          ? (zh ? "本次失败；不代表模拟成交或估值记录丢失。" : "Failed for this report; this does not imply missing fills or valuations.")
          : (zh ? "尚未完成。" : "Not completed.")}
      {report.facts_status === "partial" ? (zh ? " 事实仍有缺项，以下按实际覆盖展示。" : " Facts remain partial; coverage is shown below.") : null}
    </p>
    {facts.performance_scope === "cumulative_sleeve_history_across_versions" ? <p className="mt-3 rounded-md border border-warning/50 px-4 py-3 text-sm leading-7 text-warning">{zh ? "这里包含升级前后多个策略版本的整仓累计表现，不能当作新公式单独的业绩。旧持仓和盈亏已保留；当前版本的独立净值起点与表现尚未单独计算。" : "This is cumulative sleeve performance across strategy versions, not the new formula's standalone record. Existing holdings and P&L are preserved; a separate current-version NAV baseline and performance are not yet calculated."}</p> : null}
    <p className="mt-3 text-sm leading-7 text-text-secondary">{zh ? "使用已提交的模拟成交和真实日线价格估值，未成交日也可估值，但不会因此生成成交记录。缺价时不是完整日净值；不计算日频 Sharpe，也不把净值下跌直接解释为预测能力下降。" : "Committed fills and real daily closes value existing holdings between trades; valuations do not create fills. Missing prices leave gaps, with no daily Sharpe or prediction-decay claim."}</p>
    <p className="mt-3 text-xs text-text-secondary">{text(period.start)} → {text(period.end)} · {number(period.observation_count, 0)} {zh ? "个真实成交日" : "days with fills"} · {number(period.valuation_count, 0)} {zh ? "个有效估值日" : "valid valuation dates"} · {zh ? "覆盖策略数" : "Covered strategies"} {number(period.covered_sleeve_count, 0)}</p>
    {strings(period.missing_valuation_dates).length ? <p className="mt-2 text-xs text-warning">{zh ? "缺价日期（未填补）" : "Missing prices (not filled)"} {strings(period.missing_valuation_dates).join("、")}</p> : null}
    <dl className="my-6 grid gap-x-7 gap-y-5 sm:grid-cols-2 xl:grid-cols-4">{[[capitalReturn ? zh ? "累计盈亏 / 累计投入" : "Profit / allocated capital" : zh ? "观察期间收益" : "Observed return", points(metrics.sleeve_return_pct)], [zh ? "累计投入" : "Allocated capital", money(metrics.allocated_cash_usd)], [zh ? "累计盈亏" : "Cumulative profit", money(metrics.net_profit_usd)], [zh ? "已记佣金" : "Recorded commission", money(metrics.commission_usd)]].map(([name, value]) => <div key={name} className="border-l border-border-strong pl-4"><dt className="text-xs text-text-secondary">{name}</dt><dd className="mt-2 font-mono text-2xl">{value}</dd></div>)}</dl>
    <p className="text-xs leading-6 text-text-secondary">{zh ? "累计盈亏率不是时间加权收益。仅资金未变化时，另列首个成交收盘起算收益" : "Profit / capital is not time-weighted return. With unchanged capital only, return since first fill close"} {points(metrics.observation_return_pct)} · SPY {points(metrics.spy_return_pct)} · {zh ? "累计换手" : "Cumulative turnover"} {number(metrics.turnover, 3)}</p>
    <p className="text-xs leading-6 text-text-secondary">{text(metrics.turnover_definition, "")} {text(metrics.cost_definition, "")}</p>
    {analysis.summary ? <section className="my-6 border-y border-border-subtle py-6"><h3 className="text-base font-semibold">{zh ? "Grok 模拟复盘" : "Grok review"}</h3><p className="mt-2 text-[11px] text-text-secondary">{text(analysis.model)} · {text(analysis.reasoning_effort)} · {text(analysis.generated_at).slice(0, 10)}</p><p className="mt-4 text-[15px] leading-8">{cleanCitations(analysis.summary)}</p><div className="mt-5 grid gap-6 lg:grid-cols-2">{[[zh ? "已观察到什么" : "Observed", analysis.observations], [zh ? "可以怎样解释" : "Interpretation", analysis.explanations]].map(([name, entries]) => <section key={String(name)}><h4 className="text-sm font-medium">{String(name)}</h4><ul className="mt-3 space-y-2 text-sm leading-7 text-text-secondary">{strings(entries).map((entry, index) => <li key={index}>{cleanCitations(entry)}</li>)}</ul></section>)}</div></section> : <Empty>{zh ? "尚无可用的 AI 复盘。下面保留已核验事实；partial 状态可能只是观察覆盖有限，不表示模型连接失败。" : "No AI review is available. Partial observation coverage does not itself mean a connection failure."}</Empty>}
    <Curve points={plot} mainName={capitalReturn ? zh ? "累计盈亏 / 累计投入" : "Profit / allocated capital" : zh ? "策略观察收益" : "Observed strategy return"} comparisonName="SPY" percent zh={zh}/>
    <p className="mt-2 text-xs text-text-secondary">{zh ? "估值仅使用真实价格，不填造缺失行情。新增分配本金不计为盈利；不同资金口径的 SPY 不叠加到累计盈亏率曲线上。" : "Valuations use actual prices only. New capital is not profit; SPY is not overlaid on a different capital-return basis."}</p>
    <section className="mt-6"><h3 className="text-base font-semibold">{zh ? "最近两个观察区间" : "Latest observation intervals"}</h3><p className="mt-2 text-xs leading-6 text-text-secondary">{text(windows.reason)}</p><div className="mt-3 overflow-x-auto"><table className="w-full min-w-[450px] text-left text-sm"><thead className="text-xs text-text-secondary"><tr>{[zh ? "区间" : "Window", zh ? "自然日" : "Calendar days", zh ? "收益" : "Return", zh ? "佣金" : "Commission"].map(name => <th className="py-3" key={name}>{name}</th>)}</tr></thead><tbody>{[object(windows.previous), object(windows.current)].filter(row => row.start).map(row => <tr key={text(row.start)} className="border-t border-border-subtle"><td className="py-3">{text(row.start)} → {text(row.end)}</td><td>{number(row.calendar_days, 0)}</td><td className="font-mono">{points(row.return_pct)}</td><td className="font-mono">{money(row.commission_usd)}</td></tr>)}</tbody></table></div></section>
    {windows.status === "available" && Object.keys(object(windows.changes)).length ? <div className="mt-4 rounded-lg border border-border-subtle px-4 py-3 text-xs leading-7 text-text-secondary"><p>{zh ? "当前区间减去前一区间（不是每日变化）" : "Current interval minus previous interval, not daily change"}</p><p>{zh ? "收益差" : "Return difference"} <span className="font-mono text-text-primary">{number(object(windows.changes).return_percentage_points, 2)}</span> {zh ? "个百分点" : "pp"} · {zh ? "佣金差" : "Commission difference"} <span className="font-mono text-text-primary">{money(object(windows.changes).commission_usd)}</span> · {zh ? "换手差" : "Turnover difference"} <span className="font-mono text-text-primary">{number(object(windows.changes).turnover)}</span></p></div> : null}
    <details className="mt-5 border-t border-border-subtle pt-3"><summary className="app-touch-target cursor-pointer py-2 text-sm font-medium">{zh ? "尚不能确定的内容与证据" : "Limits and evidence"}</summary><ul className="my-3 space-y-2 text-xs leading-6 text-text-secondary">{[...strings(facts.limitations), ...strings(analysis.limitations)].map((entry, index) => <li key={index}>{cleanCitations(entry)}</li>)}</ul>{objects(facts.evidence).map(row => <p key={text(row.id)} className="py-1 text-xs text-text-secondary">[{text(row.id)}] {text(row.source)}</p>)}</details>
  </section>;
}

function WideScorecardSummary({ report, zh }: { report: FactorScorecards; zh: boolean }) {
  const data = object(report.data_acceptance), wide = object(report.wide_run);
  if (!Object.keys(wide).length) return null;
  const months = objects(data.monthly_coverage);
  const widths = months.map(row => valueNumber(row.month_end_observed)).filter((n): n is number => n !== null);
  const coverage = months.map(row => valueNumber(row.daily_row_coverage)).filter((n): n is number => n !== null);
  const sources = object(data.source_groups);
  const descriptions: Record<string, string> = {
    terminal_returns_unverified: "退市最后一段收益尚未核验完整。",
    independent_membership_completeness_unverified: "历史成员来源尚未得到独立的完整性验证。",
    historical_listing_or_ticker_periods_partially_unknown: "部分历史上市日期和代码有效期仍未知。",
    conservative_research_eligibility_not_legal_listing_history: "未知日期使用保守研究起点，不冒充真实上市记录。",
    cross_source_equivalence_not_universal: "跨源对拍只适用于已检查的股票和日期。",
    futu_volume_basis_provider_native_not_cross_source_certified: "不同来源的成交量仍有统计差异，不视为逐笔相同。",
  };
  // Quarantined reasons keep their free-form English detail verbatim: it is a technical
  // note, not a label to half-translate into the surrounding Chinese sentence.
  const describeQuarantined = (rest: string) => {
    const cut = rest.indexOf(":");
    const symbol = cut === -1 ? rest : rest.slice(0, cut);
    const detail = cut === -1 ? "" : rest.slice(cut + 1);
    if (!zh) return detail ? `Quarantined ${symbol} — technical reason: ${detail}` : `Quarantined ${symbol}`;
    return detail ? `隔离标的 ${symbol}（技术原因原文：${detail}）` : `隔离标的 ${symbol}`;
  };
  const describe = (reason: string) => zh ? descriptions[reason] ?? (reason.startsWith("quarantined:") ? describeQuarantined(reason.slice(12)) : reason.startsWith("invalid_or_zero_volume_rows:") ? `已排除无效价格或零成交量记录：${reason.split(":")[1]}` : reason) : reason;
  // The payload states its own authority and research status next to formal_ready; both
  // stay visible so a coverage pass is never read as an admission or allocation.
  const authority = text(data.authority, "");
  const researchStatus = text(data.research_status, "");
  const restrictions = strings(data.usage_restrictions);
  const authorityNotes: Record<string, [string, string]> = {
    formal_research_only: ["数据仅授权用于正式研究，不含模拟准入或资金分配。", "Authorised for formal research only; no admission or capital allocation."],
    diagnostic_only: ["数据仅用于诊断，不作为正式研究结论。", "Diagnostic use only; not a formal research conclusion."],
  };
  const researchStatusNotes: Record<string, [string, string]> = {
    ready: ["研究输入就绪。", "Research inputs ready."],
    partial_known_source_limits: ["仍保留已知来源限制。", "Known source limits remain."],
    blocked: ["存在尚未解决的数据缺口。", "Unresolved data gaps remain."],
  };
  const authorityNote = authorityNotes[authority]?.[zh ? 0 : 1];
  const researchStatusNote = researchStatusNotes[researchStatus]?.[zh ? 0 : 1];
  return <section className="mb-6 rounded-lg border border-border-strong bg-bg-surface/50 p-4 sm:p-5" aria-label={zh ? "历史股票池数据范围" : "Wide-universe data coverage"}>
    <h2 className="text-base font-semibold">{zh ? "历史股票池研究" : "Wide-universe historical research"} · {report.factors?.length ?? 0} {zh ? "项因子" : "objects"}</h2>
    <p className="mt-2 text-sm leading-7">{data.formal_ready === true ? (zh ? "行情覆盖率已达到本次研究要求" : "Research input coverage requirements met") : (zh ? "研究输入验收仍有缺项" : "Research input requirements remain incomplete")}；{zh ? "结果保留来源与样本限制，不代表策略已通过验证或已分配模拟资金。" : "Source and sample limits remain; this is not strategy admission or capital allocation."}</p>
    <p className="mt-2 text-xs text-text-secondary">{strings(wide.signal_window).join(" → ")} · {zh ? "月末历史成员范围" : "Historical month-end membership"}</p>
    <dl className="my-4 grid grid-cols-2 gap-4 lg:grid-cols-4">{[
      [zh ? "有效价格序列（含基准）" : "Price series incl. benchmark", number(data.loaded, 0)],
      [zh ? "隔离或缺失" : "Quarantined or missing", number(data.skipped, 0)],
      [zh ? "最小月末股票数" : "Minimum month-end breadth", widths.length ? number(Math.min(...widths), 0) : "—"],
      [zh ? "最低月日线覆盖" : "Minimum monthly daily coverage", coverage.length ? pct(Math.min(...coverage)) : "—"],
    ].map(([name, value]) => <div key={name}><dt className="text-xs text-text-secondary">{name}</dt><dd className="mt-1 font-mono text-xl">{value}</dd></div>)}</dl>
    <p className="text-xs leading-7 text-text-secondary">{Object.entries(sources).map(([name, item]) => `${name === "tiingo" ? "Tiingo" : name === "futu" ? "Futu" : name}: ${number(object(item).symbols, 0)}`).join(" · ")} · {zh ? "每只股票固定一家数据源，未拼接两家的价格。" : "Each symbol keeps one whole source series."}</p>
    <p className="mt-1 text-xs leading-7 text-text-secondary">{zh ? "校验按钮只检查这份已保存结果；新研究须另行计算并导入。" : "Verify checks this saved result only; a new study requires a separate run and import."}</p>
    <details className="mt-3 border-t border-border-subtle pt-2"><summary className="app-touch-target cursor-pointer py-2 text-sm">{zh ? "逐月覆盖与已知限制" : "Monthly coverage and known limits"}</summary>
      <ul className="my-3 space-y-2 text-xs leading-6 text-text-secondary">{strings(data.known_source_limits).map(reason => <li key={reason}>{describe(reason)}</li>)}</ul>
      <div className="overflow-x-auto"><table className="w-full min-w-[400px] text-left text-xs"><thead><tr>{[zh ? "月份" : "Month", zh ? "月末股票数" : "Month-end stocks", zh ? "全成员日线覆盖" : "Full-member daily coverage"].map(title => <th key={title} className="py-2 font-medium">{title}</th>)}</tr></thead><tbody>{months.map(row => <tr key={text(row.month)} className="border-t border-border-subtle"><td className="py-2">{text(row.month)}</td><td>{number(row.month_end_observed, 0)}</td><td>{pct(row.daily_row_coverage)}</td></tr>)}</tbody></table></div>
      {authority || researchStatus ? <p className="mt-3 border-t border-border-subtle pt-2 text-xs leading-6 text-text-secondary">{zh ? "数据授权" : "Data authority"} <code className="font-mono">{authority || "—"}</code>{authorityNote ? ` · ${authorityNote}` : ""} · {zh ? "研究状态" : "Research status"} <code className="font-mono">{researchStatus || "—"}</code>{researchStatusNote ? ` · ${researchStatusNote}` : ""}</p> : null}
      {restrictions.length ? <div className="mt-3 border-t border-border-subtle pt-2"><p className="text-xs leading-6 text-text-secondary">{zh ? `这份数据保留 ${restrictions.length} 条使用限制，下面按原文逐条列出（英文技术表述不逐词改写）：` : `The dataset keeps ${restrictions.length} usage restrictions, listed verbatim:`}</p><ul className="my-2 space-y-1 text-xs leading-6 text-text-secondary">{restrictions.map(reason => <li key={reason} className="break-words"><code className="font-mono">{reason}</code></li>)}</ul></div> : null}
    </details>
  </section>;
}

function ScorecardSection({ report, zh }: { report: FactorScorecards; zh: boolean }) {
  const methodology = object(report.methodology), provenance = object(report.provenance), factors = objects(report.factors);
  const wide = object(report.run).kind === "wide_universe" || Object.keys(object(report.wide_run)).length > 0;
  const catalog = new Map(objects(report.factor_catalog).map(item => [text(item.factor_id), item]));
  const coverage = new Map(objects(report.factor_coverage).map(item => [text(item.factor_id), item]));
  const name = (key: unknown) => text(catalog.get(text(key))?.[zh ? "name_zh" : "name_en"], label(key, zh));
  const shortDigest = (value: unknown) => { const raw = text(value, ""); return raw ? `${raw.slice(0, 12)}…` : "—"; };
  const horizons = (block: EvaluationObject) => Object.keys(object(block.horizons)).sort((a, b) => Number(a) - Number(b));
  const calendarInference = factors.some(block => Object.values(object(block.horizons)).some(h => object(object(h).inference).method === "calendar_overlap_floor_v1"));
  const yesNo = (value: unknown) => value === true ? (zh ? "是" : "yes") : value === false ? (zh ? "否" : "no") : "—";
  // `turnover_per_step` is stored as {top, bottom, mean}; older decks stored a bare scalar.
  const turnoverMean = (value: unknown) => valueNumber(value) ?? valueNumber(object(value).mean);
  if (report.status === "unavailable" && !factors.length) {
    if (wide) return <Empty>{zh ? `无法校验已选股票池记分卡（${text(report.reason)}）。保留原研究选择，请恢复完整的冻结产物后再校验。` : `The selected wide scorecard cannot be verified (${text(report.reason)}). Restore its complete frozen artifacts before verifying again.`}</Empty>;
    return <Empty>{zh
      ? `尚无因子记分卡结果（${text(report.reason, "no_scorecard_run")}）。点击上方“运行因子记分卡”后才会计算；打开页面不会启动计算。`
      : `No factor scorecard is stored (${text(report.reason, "no_scorecard_run")}). Run it explicitly above; opening this page computes nothing.`}</Empty>;
  }
  // An unavailable block without a sleeve return series is not the same as missing
  // data: nothing was compared, and the stored reason says exactly that.
  const marginalStatus = (block: EvaluationObject) => {
    const contribution = object(block.marginal_contribution);
    if (contribution.status === "unavailable" && contribution.reason === "sleeve_returns_not_provided") {
      return zh ? "未做组合对比（未提供组合收益）" : "Portfolio comparison not run (sleeve returns not provided)";
    }
    return statusName(contribution.status, zh);
  };
  return <section>
    <WideScorecardSummary report={report} zh={zh}/>
    <h2 className="text-xl font-semibold">{zh ? "因子记分卡（研究评价口径）" : "Factor scorecard (evaluation deck)"}</h2>
    <p className="mt-3 max-w-4xl text-sm leading-7 text-text-secondary">{zh ? "只用开盘到开盘的前向收益：信号日收盘可知，次一交易日开盘入场，持有 h 日后开盘出场。逐日标签与 Qlib 评价口径逐行一致，全部为毛口径、未计任何成本；多空做空腿假设无摩擦卖空（无借券、可得性与 RegSHO 限制）。这里衡量的是信号与后续收益的关系，不是可交易收益承诺。" : "Open-to-open forward returns only: signals are known at the close, entry is the next session's open and exit is the open h sessions later. Labels stay row-aligned with the Qlib definition, gross of all costs; the short leg assumes frictionless shorting. This measures signal-to-return association, not a tradeable return claim."}</p>
    <p className="mt-2 text-xs leading-6 text-text-secondary">{text(methodology.price_basis, "open_to_open")} · {zh ? "持有区间" : "Horizons"} {Array.isArray(methodology.horizons) ? methodology.horizons.join(" / ") : "—"} · {zh ? "分位" : "Quantiles"} {number(methodology.quantiles, 0)} · {zh ? "基准" : "Benchmark"} {text(methodology.benchmark_symbol, "SPY")} · {calendarInference ? (zh ? "统计滞后按实际信号重叠与样本长度确定，日频和月频分别计算。" : "HAC lags use actual signal overlap and sample size, respecting daily versus monthly observations.") : text(methodology.nw_lag_rule, "—")}</p>
    <p className="mt-1 text-xs leading-6 text-text-secondary">{zh ? "可交易性" : "Tradeable claim"} {yesNo(methodology.tradeable_claim)} · {zh ? "成本口径" : "Costs"} {text(methodology.costs, "none_evaluation_only")} · {text(methodology.short_assumption, "")}</p>
    {report.stale ? <p role="status" className="mt-3 rounded-lg border border-warning/50 px-4 py-3 text-sm leading-7 text-warning">{wide ? (zh ? "评分代码已更新，当前保留旧版冻结结果；校验不会重算，新结果需要另行计算并导入。" : "Scoring code changed. This frozen result remains historical; verification does not recompute it.") : zh ? "实现代码已更新，这份记分卡是旧版本结果；重新运行后才能用于当前实现。" : "The implementation changed; this deck predates it. Re-run before relying on it."}</p> : null}
    <details className="mt-4 border-t border-border-subtle pt-3"><summary className="app-touch-target cursor-pointer py-2 text-xs text-text-secondary">{zh ? "口径与指纹" : "Methodology and digests"}</summary><div className="space-y-1 py-3 text-xs leading-6 text-text-secondary"><p>{zh ? "口径版本" : "Methodology"} {text(provenance.methodology_version, "—")} · {zh ? "前向收益 schema" : "Forward-return schema"} {text(provenance.forward_return_schema_version, "—")}</p><p>{zh ? "日历" : "Calendar"} {text(methodology.calendar, "—")} · {text(methodology.gap_rules, "—")}</p><p className="break-all font-mono">{zh ? "输入指纹" : "Input digest"} {shortDigest(provenance.input_digest)} · {zh ? "源码指纹" : "Source digest"} {shortDigest(provenance.source_digest)}</p><p>{zh ? "库内对照因子" : "Peer factors"} {Array.isArray(provenance.peer_factor_ids) ? provenance.peer_factor_ids.length : 0}</p></div></details>
    {wide ? <nav aria-label={zh ? "研究对象索引" : "Research object index"} className="mt-5 flex flex-wrap gap-2">{factors.map(block => <a key={text(block.factor_id)} href={`#scorecard-${text(block.factor_id)}`} className="app-touch-target rounded-md border border-border-subtle px-3 py-2 text-xs hover:text-[var(--color-hermes)]">{name(block.factor_id)}</a>)}</nav> : null}
    <div className="mt-6 space-y-8">{factors.map((block, index) => <section id={`scorecard-${text(block.factor_id)}`} key={text(block.factor_id, String(index))} className="scroll-mt-6 border-t border-border-subtle pt-5">
      <h3 className="text-base font-semibold">{name(block.factor_id)}</h3>
      {catalog.has(text(block.factor_id)) ? <><p className="mt-2 text-sm leading-7 text-text-secondary">{text(catalog.get(text(block.factor_id))?.[zh ? "purpose_zh" : "purpose_en"], "")}</p><p className="mt-1 break-all font-mono text-[11px] text-text-secondary">{text(block.factor_id)} · {catalog.get(text(block.factor_id))?.frequency === "month_end" ? (zh ? "月末信号" : "Month-end signals") : (zh ? "日频信号" : "Daily signals")}</p></> : null}
      {block.reason ? <p className="mt-2 text-xs text-warning">{block.reason === "no_eligible_factor_values" ? (zh ? "历史长度或完整样本不足，保留该对象但未计算指标。" : "Insufficient history or complete samples; this object remains unevaluated.") : text(block.reason)}</p> : null}
      <p className="mt-1 text-xs text-text-secondary">{zh ? "排序规则：" : "Direction: "}{zh ? (block.direction === "lower_is_better" ? "数值越低越优先" : block.direction === "higher_is_better" ? "数值越高越优先" : "未明确指定") : text(block.direction, "not specified")}</p>
      <div className="mt-3 overflow-x-auto"><table className="w-full min-w-[880px] text-left text-xs">
        <thead className="border-b border-border-subtle text-text-secondary"><tr>{[zh ? "持有交易日" : "Hold sessions", "IC", "Rank IC", "NW t", "NW lag", zh ? "有效信号期" : "Signal periods", zh ? "覆盖" : "Coverage", zh ? "分位单调" : "Monotonic", zh ? "多空年化" : "LS annualized", zh ? "多空 NW t" : "LS NW t", zh ? "换手 / 步" : "Turnover / step"].map(name => <th key={name} className="py-3 pr-3 font-medium">{name}</th>)}</tr></thead>
        <tbody>{horizons(block).map(horizon => { const horizonBlock = object(object(block.horizons)[horizon]); const ic = object(horizonBlock.ic), ls = object(horizonBlock.long_short), turnover = object(horizonBlock.turnover), quantiles = object(horizonBlock.quantiles); return <tr key={horizon} className="border-b border-border-subtle/60">
          <td className="py-3 pr-3 font-mono">{horizon}</td><td className="font-mono">{number(ic.ic_mean, 4)}</td><td className="font-mono">{number(ic.rank_ic_mean, 4)}</td><td className="font-mono">{number(ic.nw_t, 3)}</td><td className="font-mono">{number(ic.nw_lag, 0)}</td><td className="font-mono">{number(ic.n_days, 0)}</td><td className="font-mono">{pct(object(horizonBlock.coverage).coverage ?? ic.coverage)}</td><td className="font-mono">{yesNo(quantiles.quantile_monotonic)}</td><td className="font-mono">{pct(ls.spread_annualized)}</td><td className="font-mono">{number(ls.spread_t_nw, 3)}</td><td className="font-mono">{number(turnoverMean(turnover.turnover_per_step), 3)}</td>
        </tr>; })}</tbody>
      </table></div>
      {horizons(block).some(h => object(object(object(block.horizons)[h]).inference).lag_unit === "signal_observations") ? <p className="mt-2 text-xs leading-6 text-text-secondary">{zh ? "NW lag 按信号期计数，持有区间按交易日计数；月末信号的有效期数不等于连续每日观察数。" : "NW lag counts signal observations; holding periods count trading sessions. Month-end observations are not consecutive daily observations."}</p> : null}
      {horizons(block).some(h => object(object(object(block.horizons)[h]).long_short).annualization_reason) ? <p className="mt-2 text-xs leading-6 text-text-secondary">{zh ? "非日频信号未换算成年收益；保留每个持有区间的统计值与 NW t，不能当成连续持仓净值。" : "Non-daily signals are not annualized as a daily portfolio; holding-period statistics and NW t remain available."}</p> : null}
      {coverage.has(text(block.factor_id)) ? <details className="mt-3"><summary className="app-touch-target cursor-pointer py-2 text-xs text-text-secondary">{zh ? "样本缺口与固定定义" : "Sample gaps and fixed definition"}</summary><p className="text-xs leading-7 text-text-secondary">{zh ? "历史预热或缺价排除" : "Warmup or missing-input exclusions"}: {number(coverage.get(text(block.factor_id))?.warmup_or_missing_input_rows, 0)}</p>{Object.entries(object(coverage.get(text(block.factor_id))?.horizons)).map(([h, details]) => <p key={h} className="text-xs leading-7 text-text-secondary">{h} {zh ? "日" : "days"} · {zh ? "有效样本" : "Valid samples"} {number(object(details).valid_rows, 0)} · {zh ? "尾部尚未成熟" : "Immature tail labels"} {number(object(details).label_tail_insufficient, 0)}</p>)}<p className="mt-2 break-all font-mono text-xs text-text-secondary">{text(catalog.get(text(block.factor_id))?.definition, "")}</p></details> : null}
      <p className="mt-3 text-xs leading-6 text-text-secondary"><span className="font-medium">{zh ? "库内最大相关" : "Max library correlation"}: </span>{number(object(block.correlation).max_abs_factor_correlation, 3)} · {text(object(block.correlation).max_correlation_factor_id, "—")} · {number(object(block.correlation).n_peers, 0)} {zh ? "个对照因子" : "peers"}</p>
      <p className="mt-1 text-xs leading-6 text-text-secondary"><span className="font-medium">{zh ? "对现有组合的边际贡献" : "Marginal contribution"}: </span>{marginalStatus(block)} · ΔSharpe {number(object(block.marginal_contribution).marginal_sharpe_delta, 3)}</p>
      {object(block.marginal_contribution).reason === "non_daily_signal_portfolio_required" ? <p className="mt-1 text-xs leading-6 text-text-secondary">{zh ? "月末信号还没有可比的日收益组合，暂不计算边际贡献。" : "A comparable daily portfolio return series is required before evaluating marginal contribution for non-daily signals."}</p> : null}
      {object(block.marginal_contribution).reason === "sleeve_returns_not_provided" ? <p className="mt-1 text-xs leading-6 text-text-secondary">{zh ? "这份记录没有提供组合收益序列，未做与现有组合的对比；不代表因子本身无效。" : "No sleeve return series was provided, so no comparison against the existing portfolio was run."}</p> : null}
    </section>)}</div>
    {!factors.length ? <Empty>{zh ? "这份记分卡没有因子区块。" : "This deck has no factor blocks."}</Empty> : null}
  </section>;
}

export function ResearchEvaluationView({ locale, researchKey = null, initialFactor, initialTab,
  initialReport = null, initialPaperReport = null, initialScorecardReport = null }: {
  locale: Locale; researchKey?: string | null; initialFactor?: string; initialTab?: string;
  initialReport?: ResearchEvaluation | null; initialPaperReport?: PaperEvaluation | null;
  initialScorecardReport?: FactorScorecards | null;
}) {
  const zh = locale === "zh";
  const [tab, setTab] = useState<Tab>(TABS.includes(initialTab as Tab) ? initialTab as Tab : researchKey ? "rolling" : initialFactor ? "reference" : "studies");
  const selectTab = (nextTab: Tab) => {
    setTab(nextTab);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", nextTab);
    // Next's native history integration updates the language links as well.
    // Passing its internal history state would bypass that integration.
    window.history.replaceState(null, "", url.toString());
  };
  const [referenceKey, setReferenceKey] = useState(initialFactor ? (initialFactor.includes(":") ? initialFactor : `factor:${initialFactor}`) : "factor:momentum");
  const [factor, setFactor] = useState(initialFactor?.replace(/^factor:/, "") ?? "momentum");
  const readResearch = useCallback(() => getResearchEvaluation(researchKey), [researchKey]);
  const readPaper = useCallback(() => getPaperEvaluation(), []);
  const readScorecards = useCallback(() => getFactorScorecards(), []);
  const isDefinition = Boolean(researchKey?.startsWith("research:strategy-"));
  const research = useSavedReport(readResearch, isDefinition || (tab !== "paper" && tab !== "studies" && tab !== "scorecards"), initialReport);
  const paper = useSavedReport(readPaper, tab === "paper", initialPaperReport);
  const scorecards = useSavedReport(readScorecards, tab === "scorecards", initialScorecardReport);
  const frozenWideScorecard = object(scorecards.report?.run).kind === "wide_universe";
  const scorecardData = object(scorecards.report?.data_acceptance);
  const scorecardSignalWindow = strings(object(scorecards.report?.wide_run).signal_window);
  const scorecardSource = text(scorecardData.provider, "");
  // The scorecard tab reports the deck's own source and window; the research report's
  // window describes a different run and must not stand in for it.
  const scorecardProvenance = tab !== "scorecards" ? null : scorecardSource && scorecardSignalWindow.length
    ? `${zh ? "数据来源" : "Source"} ${scorecardSource} · ${scorecardSignalWindow.join(" → ")}`
    : scorecardSource ? `${zh ? "数据来源" : "Source"} ${scorecardSource}`
      : scorecardSignalWindow.length ? scorecardSignalWindow.join(" → ") : null;
  const report = research.report && (research.report.key ?? null) === researchKey ? research.report : null;
  const active = tab === "paper" ? paper : tab === "scorecards" ? scorecards : research;
  const activeReport: { status: string; updated_at?: string | null; error?: string | null } | null =
    tab === "paper" ? paper.report : tab === "scorecards" ? scorecards.report : report;
  if (isDefinition) {
    const source = object(report?.source);
    return <div className="mx-auto w-full max-w-[1280px] px-4 py-6 sm:px-7">
      <Link href={localizePath("/collection", locale)} className="app-touch-target inline-flex items-center gap-2 text-sm text-text-secondary"><ArrowLeft size={14}/>{zh ? "策略与因子" : "Strategies & factors"}</Link>
      <h1 className="mt-6 text-2xl font-semibold">{text(source.title, zh ? "策略验证记录" : "Strategy validation record")}</h1>
      <p className="mt-3 text-sm leading-7 text-text-secondary">{text(source.description)}</p>
      <p className="mt-4 text-sm leading-7">{zh ? "这是完整策略的历史验证，保留原本的因子权重、持仓比例和调仓频率。继续研究需使用这份策略自己的验证流程，不会改成旧单因子参考组合。" : "Historical validation of this complete strategy, preserving its weights, exposure and schedule. Continue through the matching strategy's validation, not the legacy factor reference protocol."}</p>
      <p className="mt-3 break-all font-mono text-xs text-text-secondary">{researchKey}</p>
      {research.error || report?.error ? <p role="alert" className="mt-4 text-sm text-warning">{research.error ?? report?.error}</p> : null}
      {objects(source.evidence).map((evidence, index) => <section key={`${text(evidence.engine)}-${index}`} className="mt-7 border-t border-border-subtle pt-4">
        <h2 className="text-lg font-medium">{text(evidence.engine)} · {zh ? "已保存历史结果" : "Saved historical result"}</h2>
        <p className="mt-2 text-xs text-text-secondary">{text(evidence.start)} → {text(evidence.end)} · {text(evidence.run_id)}</p>
        <MetricTable zh={zh} rows={[{ name: text(source.title), metrics: object(evidence.metrics) }]}/>
        <p className="mt-2 text-xs leading-6 text-text-secondary">{text(evidence.note)}</p>
      </section>)}
      {!objects(source.evidence).length ? <Empty>{zh ? "没有可核对的专属验证记录，指标保持为空。" : "No verified matching record; metrics remain unavailable."}</Empty> : null}
      <ul className="mt-5 space-y-2 text-sm leading-7 text-text-secondary">{strings(report?.warnings).map(note => <li key={note}>{note}</li>)}</ul>
      <div className="mt-5 flex flex-wrap gap-3">{objects(source.links).filter(link => text(link.href).startsWith("/strategy-library?")).map(link => <Link key={text(link.href)} href={localizePath(text(link.href), locale)} className="app-touch-target inline-flex items-center rounded-md border border-border-strong px-4 text-sm text-[var(--color-hermes)]">{text(link.label)}<ArrowUpRight size={14}/></Link>)}</div>
    </div>;
  }
  const tabNames = zh ? { studies: "按用途研究", reference: "原 ETF 诊断", rolling: "滚动验证", increment: "因子增量", paper: "模拟复盘", scorecards: "因子记分卡" } : { studies: "Purpose-led studies", reference: "Original ETF diagnostics", rolling: "Rolling validation", increment: "Factor contribution", paper: "Paper review", scorecards: "Factor scorecard" };
  return <div className="mx-auto w-full max-w-[1500px] px-4 py-6 sm:px-7 lg:px-9">
    <Link href={localizePath("/collection", locale)} className="app-touch-target inline-flex items-center gap-2 text-xs text-text-secondary hover:text-text-primary"><ArrowLeft size={14}/>{zh ? "策略与因子" : "Strategies & factors"}</Link>
    <header className="my-5 flex flex-wrap items-start justify-between gap-5"><div><h1 className="text-3xl font-semibold tracking-tight">{zh ? "策略研究与回测" : "Strategy research & backtests"}</h1><p className="mt-3 text-sm leading-7 text-text-secondary">{zh ? "比较不同策略的收益与风险，逐期查看选股排名、目标持仓和成交，再决定哪些想法值得继续研究。" : "Compare strategy returns and risk, inspect historical rankings, holdings and fills, then decide what to research next."}</p>{researchKey ? <p className="mt-2 break-all font-mono text-[11px] text-text-secondary">{researchKey}</p> : null}</div>{tab !== "studies" ? <button type="button" disabled={active.busy} onClick={() => void (tab === "paper" ? paper.update(refreshPaperEvaluation) : tab === "scorecards" ? scorecards.update(() => refreshFactorScorecards()) : research.update(() => refreshResearchEvaluation(researchKey)))} className="app-touch-target inline-flex items-center gap-2 rounded-md bg-[var(--color-hermes)] px-5 py-2 text-sm font-medium text-bg-base disabled:cursor-wait disabled:opacity-60"><RefreshCw size={16} className={active.busy ? "motion-safe:animate-spin" : ""}/>{active.busy ? (zh ? "正在更新…" : "Updating…") : tab === "paper" ? (zh ? "更新模拟复盘" : "Update paper review") : tab === "scorecards" ? (frozenWideScorecard ? (zh ? "校验已保存记分卡" : "Verify saved scorecard") : (zh ? "运行因子记分卡" : "Run factor scorecard")) : (zh ? "运行真实数据评价" : "Run real-data evaluation")}</button> : null}</header>
    <nav className="mb-5 flex flex-wrap gap-1 border-b border-border-subtle pb-4" aria-label={zh ? "评价分类" : "Evaluation sections"}>{TABS.map(value => <button type="button" key={value} aria-pressed={tab === value} onClick={() => selectTab(value)} className={`app-touch-target rounded-md px-5 text-sm ${tab === value ? "bg-bg-surface-muted font-medium text-[var(--color-hermes)]" : "text-text-secondary hover:bg-bg-surface"}`}>{tabNames[value]}</button>)}</nav>
    {tab === "studies" ? <StrategyStudiesView locale={locale}/> : <>
    <div className="mb-6 flex flex-wrap gap-x-5 gap-y-2 text-xs text-text-secondary"><span>{tab === "paper" && activeReport?.status === "partial" && object(paper.report?.analysis).summary ? (zh ? "已有复盘 · 观察覆盖有限" : "Review saved · limited observations") : statusName(activeReport?.status ?? "not_started", zh)}</span>{activeReport?.updated_at ? <span>{zh ? "保存于" : "Saved"} {activeReport.updated_at.replace("T", " ").slice(0, 19)} UTC</span> : null}{tab === "scorecards" && scorecards.report?.generated_at ? <span>{zh ? "生成于" : "Generated"} {text(scorecards.report.generated_at).replace("T", " ").slice(0, 19)} UTC</span> : null}{scorecardProvenance ? <span>{scorecardProvenance}</span> : tab !== "paper" && tab !== "scorecards" && object(report?.source).data_start ? <span>{text(object(object(report?.source).request).provider, "Futu")} · {text(object(report?.source).data_start)} → {text(object(report?.source).data_end)}</span> : null}</div>
    {active.error || activeReport?.error ? <div role="alert" className="mb-6 rounded-lg border border-warning/50 bg-warning/5 px-4 py-3 text-sm leading-7 text-warning">{active.error ?? activeReport?.error}</div> : null}
    {active.busy ? <p role="status" className="mb-5 text-sm text-text-secondary">{tab === "paper" ? (zh ? "正在核对模拟事实并生成解读；不会生成交易。" : "Reviewing saved observations; no trades are created.") : text(tab === "scorecards" ? scorecards.report?.progress : report?.progress, zh ? "正在读取状态，完成的部分会保留。" : "Reading progress; completed results are retained.")}</p> : null}
    {!activeReport ? <Empty>{active.error ? (zh ? "暂时无法读取已保存结果，未填入任何示例数据。" : "Saved results unavailable; no sample results substituted.") : (zh ? "正在读取已保存结果…" : "Loading saved results…")}</Empty> : tab === "paper" ? <PaperSection report={paper.report!} zh={zh}/> : tab === "scorecards" ? <ScorecardSection report={scorecards.report!} zh={zh}/> : tab === "reference" ? <ReferenceSection report={report!} selected={referenceKey} onSelect={setReferenceKey} zh={zh}/> : <RollingSection report={report!} selectedFactor={factor} onSelect={setFactor} incremental={tab === "increment"} zh={zh}/>}
    {tab !== "paper" && tab !== "scorecards" && report ? <details className="mt-8 border-t border-border-subtle pt-3"><summary className="app-touch-target cursor-pointer py-2 text-xs text-text-secondary">{zh ? "运行依据与记录" : "Run evidence"}</summary><div className="space-y-2 py-3 text-xs leading-6 text-text-secondary">{strings(report.warnings).map((warning, index) => <p key={index}>{warning}</p>)}<p className="break-all font-mono">{report.run_id}</p><p className="break-all font-mono">{zh ? "输入指纹" : "Input digest"}: {report.input_digest}</p><p className="break-all font-mono">{zh ? "源码指纹" : "Source digest"}: {report.source_digest}</p><p>{zh ? "固定观察范围不是历史逐日成分股全集，不按此结果自动启用策略。" : "This fixed universe is not a point-in-time market universe. Results do not automatically enable a strategy."}</p></div></details> : null}
    </>}
  </div>;
}

export function ItemEvaluationSummary({ itemKey, locale, initialReport = null }: {
  itemKey: string; locale: Locale; initialReport?: ResearchEvaluation | null;
}) {
  const zh = locale === "zh", isResearch = itemKey.startsWith("research:");
  const requestKey = isResearch ? itemKey : null;
  const read = useCallback(() => getResearchEvaluation(requestKey), [requestKey]);
  const state = useSavedReport(read, true, initialReport);
  const report = state.report && (state.report.key ?? null) === requestKey ? state.report : null;
  const comparison = objects(object(report?.rolling).comparisons).find(row => row.factor_id === `candidate::${itemKey.slice("research:".length)}`);
  const row = isResearch ? object(comparison?.augmented) : objects(object(report?.reference).rows).find(item => item.key === itemKey);
  const usable = report?.status !== "stale" && row?.status === "available";
  const partitions = isResearch ? object(comparison?.partitions) : {};
  const href = isResearch ? `/research-evaluation?key=${encodeURIComponent(itemKey)}` : `/research-evaluation?factor=${encodeURIComponent(itemKey)}`;
  return <section className="mt-6 border-t border-border-subtle pt-5" aria-label={zh ? "后续真实评价" : "Reference evaluation"}>
    <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="text-base font-semibold">{isResearch ? (zh ? "后续滚动评价" : "Follow-up rolling evaluation") : (zh ? "真实数据参考回测" : "Real-data reference backtest")}</h3><Link prefetch={false} href={localizePath(href, locale)} className="app-touch-target inline-flex items-center gap-1 text-xs text-[var(--color-hermes)]">{zh ? "查看完整评价" : "Full evaluation"}<ArrowUpRight size={13}/></Link></div>
    {Object.keys(partitions).length && report?.status !== "stale" ? <SelectionPartitions value={partitions} zh={zh}/> : usable ? <><MetricTable zh={zh} rows={[{ name: isResearch ? (zh ? "加入研究因子的模型" : "Model with research factor") : (zh ? "对应参考用法" : "Matching reference"), metrics: object(row?.metrics) }, { name: "QQQ", metrics: object(row?.benchmark_metrics) }]}/><p className="mt-3 text-xs leading-6 text-text-secondary">{isResearch ? (zh ? "当前显示该研究因子参与的滚动模型，不是原始历史双引擎回放；公式发现阶段不因此获得样本外证明。" : "This rolling model includes the exact research factor; it is distinct from the original dual-engine replay.") : row?.frequency === "monthly" ? (zh ? "月频多空毛收益，未计借券与成交成本，不能与日频扣费结果混比。" : "Monthly gross long-short results exclude borrowing and trading costs.") : (zh ? "这是该条目的固定参考组合，与相同窗口的 QQQ 对照；不借用其他因子的指标。" : "The exact item's fixed reference portfolio, compared with QQQ over the same window.")}</p></> : <p className="mt-3 text-sm leading-7 text-text-secondary">{report?.status === "stale" ? (zh ? "代码已更新，当前实现尚无对应的新评价；旧记录可在详情中查看。" : "The implementation changed; a new matching evaluation is needed.") : (zh ? "这项内容尚无可用的对应评价。可进入完整评价页查看原因并显式运行；打开此处不会启动模型或回测。" : "No matching evaluation is available. Inspect and explicitly run it on the full page.")}</p>}
    {state.error ? <p className="mt-2 text-xs text-warning">{state.error}</p> : null}
  </section>;
}
