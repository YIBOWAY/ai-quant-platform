"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { ArrowUpRight, BookmarkPlus, ChevronDown, RefreshCw } from "lucide-react";
import { localizePath, type Locale } from "@/lib/locale";
import { IntakeResearchEvidence, intakeLocalValidationCompleted } from "./IntakeResearchEvidence";
import { PaperRuntimeEvidence } from "./PaperRuntimeEvidence";
import {
  canEnableSavedStrategy, enableSavedStrategy, getStrategyLibrary, saveStrategyVersion,
  strategyIssueText, strategyLibraryNeedsPoll, strategyOriginHref, StrategyMutationError,
  validateSavedStrategy, type StrategyLibraryEntry, type StrategyLibraryStatus, type StrategySaveSource,
  composeStrategy, getStrategyFactorOptions, parseStrategySymbols,
  type StrategyComposeRequest, type StrategyFactorOption,
  type StrategySignalAnalysis,
  type StrategyDataNeed,
  PERFORMANCE_SCOPE_CUMULATIVE_SLEEVE_HISTORY,
} from "@/lib/strategyLibrary";

const STATUS: Record<StrategyLibraryStatus, [string, string]> = {
  draft: ["已保存 · 待验证", "Saved · not validated"],
  validating: ["验证中", "Validating"],
  validation_failed: ["验证未通过", "Validation failed"],
  validated: ["验证通过 · 待启用", "Validated · not enabled"],
  paper_running: ["已启用 · 运行证据另列", "Enabled · execution evidence below"],
  stale: ["版本已变化", "Version changed"],
  superseded: ["已由新版本接续 · 历史保留", "Superseded · history preserved"],
};
const percent = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value) ? "—" : `${(value * 100).toFixed(2)}%`;
const numeric = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value) ? "—" : value.toFixed(3);
const buttonClass = "app-touch-target inline-flex items-center justify-center gap-2 rounded-md border px-4 py-2 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-hermes)] disabled:cursor-not-allowed disabled:opacity-50";
const inputClass = "app-touch-target w-full rounded-md border border-border-strong bg-bg-base px-3 py-2 text-sm text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--color-hermes)] disabled:opacity-45";

export function FactorComposer({ locale, onSaved, initialOptions = null }: {
  locale: Locale; onSaved: (entry: StrategyLibraryEntry) => void;
  initialOptions?: StrategyFactorOption[] | null;
}) {
  const zh = locale === "zh";
  const [options, setOptions] = useState(initialOptions);
  const [selected, setSelected] = useState<Record<string, { weight: string; lookback: string; direction: StrategyFactorOption["direction"] }>>({});
  const [title, setTitle] = useState("");
  const [symbols, setSymbols] = useState("");
  const [benchmark, setBenchmark] = useState("SPY");
  const [rebalance, setRebalance] = useState<StrategyComposeRequest["rebalance"]>("monthly");
  const [normalization, setNormalization] = useState<StrategyComposeRequest["normalization"]>("rank");
  const [topN, setTopN] = useState("3");
  const [nameCap, setNameCap] = useState("100");
  const [exposure, setExposure] = useState("100");
  const [minOrder, setMinOrder] = useState("0");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false), [uncertain, setUncertain] = useState(false);
  const pending = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    getStrategyFactorOptions(controller.signal).then(value => {
      if (!controller.signal.aborted) setOptions(value.factors);
    }).catch(reason => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Factor options unavailable");
    });
    return () => controller.abort();
  }, []);
  const choose = (option: StrategyFactorOption, checked: boolean) => setSelected(current => {
    const next = { ...current };
    if (checked) next[option.factor_id] = { weight: "1", lookback: String(option.lookback), direction: option.direction };
    else delete next[option.factor_id];
    return next;
  });
  const update = (id: string, patch: Partial<(typeof selected)[string]>) =>
    setSelected(current => ({ ...current, [id]: { ...current[id], ...patch } }));
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (pending.current || uncertain) return;
    pending.current = true; setBusy(true); setError(null);
    try {
      const request: StrategyComposeRequest = {
        kind: "factor_blend", title, symbols: parseStrategySymbols(symbols),
        benchmark_symbol: benchmark.trim().toUpperCase(), rebalance, normalization,
        top_n: Number(topN), max_weight_per_symbol: Number(nameCap) / 100,
        target_gross_exposure: Number(exposure) / 100, min_order_value: Number(minOrder),
        factors: (options ?? []).filter(option => Boolean(selected[option.factor_id])).map(option => ({
          factor_id: option.factor_id, expression: option.expression,
          lookback: Number(selected[option.factor_id].lookback),
          direction: selected[option.factor_id].direction, weight: Number(selected[option.factor_id].weight),
        })),
      };
      onSaved(await composeStrategy(request));
    } catch (reason) {
      const unknown = reason instanceof StrategyMutationError && reason.outcomeUnknown;
      setUncertain(unknown);
      setError(unknown ? (zh ? "保存状态尚未确认。请刷新策略记录核对，当前表单不会重复提交。" : "Save outcome is unknown. Refresh strategy records; this form will not resubmit.") : strategyIssueText(reason instanceof Error ? reason.message : reason, locale));
    } finally { pending.current = false; setBusy(false); }
  };
  return <form onSubmit={event => void save(event)} className="mb-6 border-y border-[var(--color-hermes)]/50 py-5" aria-label={zh ? "组合因子" : "Compose factors"}>
    <h2 className="text-lg font-semibold">{zh ? "组合因子" : "Compose factors"}</h2>
    <p className="mt-2 text-sm leading-7 text-text-secondary">{zh ? "把已保存公式与注册因子一起评分，选定股票池和持仓规则，保存为一条待验证策略。" : "Blend saved formulas with registered factors, choose your universe and position rules, then save a strategy for validation."}</p>
    <p className="mt-2 text-xs leading-6 text-[var(--color-hermes)]">{zh ? "因子评分权重决定各信号的贡献，不是下单持仓比例。入选标的等权，再按单标的与总仓位上限留出现金。" : "Factor weights control signal contributions, not order allocations. Selected instruments are equally weighted, subject to per-name and total exposure caps; the remainder stays in cash."}</p>
    <fieldset disabled={busy || uncertain} className="mt-4 space-y-5">
      <legend className="sr-only">{zh ? "组合参数" : "Composition parameters"}</legend>
      <div className="grid gap-4 sm:grid-cols-2"><label className="space-y-1 text-xs text-text-secondary">{zh ? "策略名称" : "Strategy name"}<input className={inputClass} required maxLength={200} value={title} onChange={event => setTitle(event.target.value)}/></label><label className="space-y-1 text-xs text-text-secondary">{zh ? "股票池代码，逗号分隔" : "Universe symbols, comma separated"}<input className={inputClass} required value={symbols} placeholder="AAPL, MSFT, NVDA" onChange={event => setSymbols(event.target.value)}/></label></div>
      <fieldset><legend className="mb-2 text-sm font-medium">{zh ? "选择要组合的因子" : "Choose factors to combine"}</legend>
        {options === null ? <p role="status" className="py-4 text-xs text-text-secondary">{zh ? "正在读取可用因子…" : "Loading available factors…"}</p> : options.length === 0 ? <p className="py-4 text-xs text-text-secondary">{zh ? "暂无可用因子。已保存的公式会与注册因子一起列在这里。" : "No factors available. Saved formulas appear here alongside registered factors."}</p> : options.map(option => {
          const choice = selected[option.factor_id];
          return <div key={option.factor_id} className="grid gap-3 border-t border-border-subtle py-3 sm:grid-cols-[minmax(180px,1fr)_110px_130px_140px]">
            <div><label className="app-touch-target flex cursor-pointer items-center gap-3 text-sm"><input type="checkbox" className="size-4 accent-[var(--color-hermes)]" checked={Boolean(choice)} onChange={event => choose(option, event.target.checked)}/><span className="break-words">{option.label}<span className="ml-2 text-xs text-text-secondary">{option.expression ? (zh ? "已保存公式" : "Saved formula") : (zh ? "注册因子" : "Registered factor")}</span></span></label>{option.expression ? <code className="block break-all text-[11px] leading-6 text-text-secondary">{option.expression}</code> : null}{option.research_only ? <p className="text-[11px] leading-6 text-text-secondary">{zh ? "可继续组合研究，不代表单因子已验证有效。" : "Reusable for research; standalone effectiveness is not established."}</p> : null}{option.source_refs?.length ? <details className="text-[11px] text-text-secondary"><summary className="cursor-pointer py-1">{zh ? `查看 ${option.source_refs.length} 份来源策略` : `${option.source_refs.length} source strategies`}</summary>{option.source_refs.map(source => <a key={source.strategy_id} href={`#strategy-${encodeURIComponent(source.strategy_id)}`} className="block py-1 text-[var(--color-hermes)] hover:underline">{source.title}</a>)}</details> : null}</div>
            <label className="space-y-1 text-xs text-text-secondary">{zh ? "评分权重" : "Signal weight"}<input aria-label={`${option.label} ${zh ? "评分权重" : "signal weight"}`} className={inputClass} disabled={!choice} type="number" step="any" required value={choice?.weight ?? "1"} onChange={event => update(option.factor_id, { weight: event.target.value })}/></label>
            <label className="space-y-1 text-xs text-text-secondary">{option.expression ? (zh ? "完整历史（日）" : "History (days)") : (zh ? "回看（日）" : "Lookback (days)")}<input aria-label={`${option.label} ${zh ? "历史窗口" : "history window"}`} className={inputClass} disabled={!choice} type="number" min={1} max={1260} step={1} required value={choice?.lookback ?? option.lookback} onChange={event => update(option.factor_id, { lookback: event.target.value })}/></label>
            <label className="space-y-1 text-xs text-text-secondary">{zh ? "信号方向" : "Direction"}<select aria-label={`${option.label} ${zh ? "信号方向" : "direction"}`} className={inputClass} disabled={!choice} value={choice?.direction ?? option.direction} onChange={event => update(option.factor_id, { direction: event.target.value as StrategyFactorOption["direction"] })}><option value="higher_is_better">{zh ? "越高越优" : "Higher is better"}</option><option value="lower_is_better">{zh ? "越低越优" : "Lower is better"}</option></select></label>
          </div>;
        })}
        <p className="mt-2 text-xs leading-6 text-text-secondary">{zh ? "注册因子的回看参数参与计算。已保存公式内的窗口保持原值，完整历史天数不能短于公式所需数据。只在全部选中因子均有数据的标的中评分。" : "Registered lookbacks affect calculation. Saved formulas keep their embedded windows; required history cannot be shorter than the formula needs. Scores use only instruments with all selected factors available."}</p>
      </fieldset>
      <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-4">
        <label className="space-y-1 text-xs text-text-secondary">{zh ? "调仓频率" : "Rebalance"}<select className={inputClass} value={rebalance} onChange={event => setRebalance(event.target.value as StrategyComposeRequest["rebalance"])}><option value="daily">{zh ? "每日" : "Daily"}</option><option value="weekly">{zh ? "每周" : "Weekly"}</option><option value="monthly">{zh ? "每月" : "Monthly"}</option></select></label>
        <label className="space-y-1 text-xs text-text-secondary">{zh ? "选股数量 Top N" : "Selection count Top N"}<input className={inputClass} type="number" min={1} step={1} required value={topN} onChange={event => setTopN(event.target.value)}/></label>
        <label className="space-y-1 text-xs text-text-secondary">{zh ? "统一评分尺度" : "Score normalization"}<select className={inputClass} value={normalization} onChange={event => setNormalization(event.target.value as StrategyComposeRequest["normalization"])}><option value="rank">{zh ? "百分位排名（rank）" : "Percentile rank"}</option><option value="zscore">{zh ? "标准分（z-score）" : "Z-score"}</option></select></label>
        <label className="space-y-1 text-xs text-text-secondary">{zh ? "比较基准" : "Benchmark"}<input className={inputClass} required value={benchmark} onChange={event => setBenchmark(event.target.value)}/></label>
        <label className="space-y-1 text-xs text-text-secondary">{zh ? "单标的持仓上限 %" : "Per-name position cap %"}<input className={inputClass} type="number" min={0.01} max={100} step="any" required value={nameCap} onChange={event => setNameCap(event.target.value)}/></label>
        <label className="space-y-1 text-xs text-text-secondary">{zh ? "总仓位上限 %" : "Total exposure cap %"}<input className={inputClass} type="number" min={0} max={100} step="any" required value={exposure} onChange={event => setExposure(event.target.value)}/></label>
        <label className="space-y-1 text-xs text-text-secondary">{zh ? "最小交易金额 $" : "Minimum order $"}<input className={inputClass} type="number" min={0} step="any" required value={minOrder} onChange={event => setMinOrder(event.target.value)}/></label>
      </div>
      <div className="flex flex-wrap items-center gap-4"><button type="submit" disabled={busy || uncertain || !Object.keys(selected).length} className={`${buttonClass} border-[var(--color-hermes)] bg-[var(--color-hermes)] text-bg-base`}>{busy ? (zh ? "正在保存…" : "Saving…") : (zh ? "保存组合，等待验证" : "Save composition for validation")}</button><p className="text-xs text-text-secondary">{zh ? "保存不会启动调参、验证或模拟运行。" : "Saving does not tune, validate or enable paper simulation."}</p></div>
    </fieldset>
    {error ? <p role="alert" className="mt-3 text-sm leading-6 text-warning">{error}</p> : null}
  </form>;
}

export function SaveStrategyButton({ source, locale, title }: {
  source: StrategySaveSource | null; locale: Locale; title?: string;
}) {
  const zh = locale === "zh";
  const pending = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const save = async () => {
    if (!source || pending.current || uncertain) return;
    pending.current = true; setBusy(true); setError(null);
    try {
      const entry = await saveStrategyVersion(source, title);
      window.location.assign(localizePath(`/strategy-library?strategy=${encodeURIComponent(entry.strategy_id)}`, locale));
    } catch (reason) {
      const unknown = reason instanceof StrategyMutationError && reason.outcomeUnknown;
      setUncertain(unknown);
      setError(unknown
        ? (zh ? "保存状态尚未确认，请到我的策略查看记录。" : "Save outcome is unknown. Check My strategies before another attempt.")
        : strategyIssueText(reason instanceof Error ? reason.message : reason, locale));
    } finally { pending.current = false; setBusy(false); }
  };
  return <div className="space-y-2">
    <button type="button" disabled={!source || busy || uncertain} onClick={() => void save()}
      className={`${buttonClass} border-[var(--color-hermes)] text-[var(--color-hermes)]`}
      title={zh ? "保存当前公式与参数的固定版本，然后前往我的策略验证。" : "Save this exact formula and parameter version, then validate it in My strategies."}>
      <BookmarkPlus size={16}/>{busy ? (zh ? "正在保存…" : "Saving…") : (zh ? "保存到我的策略" : "Save to My strategies")}
    </button>
    {error ? <p role="alert" className="max-w-xl text-xs leading-6 text-warning">{error} {uncertain ? <Link className="underline" href={localizePath("/strategy-library", locale)}>{zh ? "查看我的策略" : "Open My strategies"}</Link> : null}</p> : null}
  </div>;
}

export function FactorContribution({ analysis, locale }: {
  analysis?: StrategySignalAnalysis | null; locale: Locale;
}) {
  const zh = locale === "zh";
  const components = analysis?.components ?? [];
  const ridge = analysis?.ridge;
  const reason = strategyIssueText(analysis?.reason, locale);
  return <details className="group border-t border-border-subtle pt-2">
    <summary className="app-touch-target flex cursor-pointer list-none items-center gap-2 text-sm text-text-primary"><ChevronDown size={14}/>{zh ? "因子贡献与学习模型对照" : "Factor contributions & model comparison"}</summary>
    <p className="mt-2 text-xs leading-6 text-text-secondary">{zh ? "Rank IC 衡量分数与后续收益排序的关系，不等于策略收益。去除对照只比较共同样本；变化为完整组合减去去除后的结果，正值表示该因子在本次对照中改善了排序。" : "Rank IC measures the relationship between scores and subsequent return ranks, not portfolio return. Removal comparisons use matched samples; a positive full-minus-without delta means that factor improved ranking in this comparison."}</p>
    {!analysis ? <p className="py-3 text-xs text-text-secondary">{zh ? "这份验证记录尚未提供因子贡献分析，不能判断各因子的增量价值。" : "This validation has no factor contribution analysis; incremental value is unknown."}</p> : <>
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs"><span>{zh ? "组合 Rank IC" : "Combined Rank IC"} <span className="font-mono">{numeric(analysis.score?.all?.rank_ic)}</span></span><span>{zh ? "近期 Rank IC" : "Recent Rank IC"} <span className="font-mono">{numeric(analysis.score?.recent?.rank_ic)}</span></span><span>{zh ? "共同样本" : "Samples"} <span className="font-mono">{analysis.score?.all?.samples ?? "—"}</span></span></div>
      {reason ? <p className="mt-2 text-xs text-warning">{reason}</p> : null}
      {components.length ? <div className="mt-3 overflow-x-auto"><table className="w-full min-w-[500px] text-left text-xs"><caption className="sr-only">{zh ? "各因子排序与共同样本增量" : "Factor rank correlation and matched-sample contribution"}</caption><thead className="border-b border-border-strong text-text-secondary"><tr>{[zh ? "因子" : "Factor", "Rank IC", zh ? "近期 Rank IC" : "Recent Rank IC", zh ? "加入后的 IC 变化" : "IC delta with factor", zh ? "配对样本" : "Paired samples"].map(label => <th key={label} className="py-2 pr-4 font-medium">{label}</th>)}</tr></thead><tbody>{components.map(component => {
        const removed = analysis.leave_one_out?.find(row => row.factor_id === component.factor_id);
        return <tr key={component.factor_id} className="border-b border-border-subtle"><th className="py-3 pr-4 font-mono font-normal">{component.factor_id}</th><td className="font-mono">{numeric(component.all?.rank_ic)}</td><td className="font-mono">{numeric(component.recent?.rank_ic)}</td><td className="font-mono">{numeric(removed?.rank_ic_delta_full_minus_without)}</td><td className="font-mono">{removed?.paired_samples ?? "—"}</td></tr>;
      })}</tbody></table></div> : <p className="py-3 text-xs text-text-secondary">{zh ? "逐因子数据尚不可用，未估算或补零。" : "Per-factor data is unavailable; no values are estimated or filled with zero."}</p>}
      {analysis.correlations?.periods != null ? <p className="mt-2 text-xs text-text-secondary">{zh ? "因子相关性记录覆盖" : "Factor correlation observations"} {analysis.correlations.periods} {zh ? "个时点。" : "periods."}</p> : null}
    </>}
    <div className="mt-3 border-l-2 border-border-strong pl-4"><h4 className="text-xs font-medium text-text-primary">{zh ? "Ridge 学习模型对照" : "Ridge model comparison"}</h4><p className="mt-1 text-xs leading-6 text-text-secondary">{zh ? "Ridge 仅作为验证对照，不会自动改动当前因子权重、调仓或模拟规则。" : "Ridge is a validation challenger; it does not automatically change factor weights, rebalancing or paper rules."}</p>
      {ridge?.fixed_score_metrics || ridge?.ridge_metrics ? <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2 text-xs"><span>{zh ? "固定组合 Rank IC" : "Fixed blend Rank IC"} <span className="font-mono">{numeric(ridge.fixed_score_metrics?.rank_ic)}</span></span><span>Ridge Rank IC <span className="font-mono">{numeric(ridge.ridge_metrics?.rank_ic)}</span></span><span>{zh ? "变化" : "Delta"} <span className="font-mono">{numeric(ridge.rank_ic_delta)}</span></span><span>{zh ? "匹配样本" : "Matched samples"} {ridge.matched_samples ?? "—"}</span><span>{zh ? "滚动窗口" : "Rolling folds"} {ridge.folds?.length ?? "—"}</span></div> : <p className="mt-2 text-xs text-text-secondary">{strategyIssueText(ridge?.reason, locale) || (zh ? "尚无可用的学习模型对照结果。" : "No learning-model comparison is available yet.")}</p>}
    </div>
  </details>;
}

export function AdmissionEvidence({ receipt, locale }: {
  receipt?: StrategyLibraryEntry["admission_v2"]; locale: Locale;
}) {
  if (!receipt) return null;
  const zh = locale === "zh";
  const parallel = receipt.mode === "parallel";
  const state = ({
    passed: zh ? "检查通过" : "Checks passed",
    not_evaluated: zh ? "检查材料尚不完整" : "Required evidence is incomplete",
    recorded: zh ? "保留研究记录，不配置资金" : "Research record only; unfunded",
    shadow: zh ? "只作观察，不配置资金" : "Shadow evidence only; unfunded",
    failed: zh ? "检查未通过" : "Checks not passed",
  } as Record<string, string>)[receipt.status ?? ""] ?? (zh ? "检查状态未知" : "Check status unknown");
  const tier = ({
    T0: zh ? "T0 · 仅记录" : "T0 · record only",
    T1: zh ? "T1 · 观察级" : "T1 · observation",
    T2: zh ? "T2 · 通过本次分级检查" : "T2 · tier checks passed",
  } as Record<string, string>)[receipt.validated_tier ?? ""];
  return <section className="mt-4 rounded-md border border-border-subtle bg-bg-surface/50 px-4 py-3" aria-label={zh ? "新准入检查记录" : "Versioned admission evidence"}>
    <h3 className="text-sm font-medium">{parallel ? (zh ? "新旧检查并列对照" : "Parallel comparison with existing checks") : (zh ? "新准入检查记录" : "Versioned admission checks")}</h3>
    <p className="mt-2 text-xs leading-6 text-text-secondary">{state}{tier && receipt.status !== "not_evaluated" ? ` · ${tier}` : ""}</p>
    <p className="mt-1 text-xs leading-6 text-text-secondary">{parallel ? (zh ? "这份结果仅用于对照，不改变原准入结论，也不会据此新增模拟资金。" : "This comparison does not replace the existing decision or allocate paper capital.") : (zh ? "检查等级不代表资金已经分配，也不代表已经成交；实际启用与交易仍以模拟记录为准。" : "A check tier is not a cash allocation or a fill; actual activation and trades remain in paper records.")}</p>
    {receipt.intent_kind === "replacement" ? <p className="mt-1 break-words text-xs leading-6 text-text-secondary">{zh ? "用途：更新现有模拟仓的规则，不另开仓或追加本金。目标模拟仓：" : "Purpose: update an existing paper sleeve's recipe, without opening another sleeve or adding capital. Target: "}<code>{receipt.target_sleeve_id ?? "—"}</code>{zh ? "。是否已更新，以该仓的版本记录为准。" : ". Its version history records whether the update actually occurred."}</p> : null}
    {receipt.reasons?.length ? <details className="mt-1"><summary className="app-touch-target cursor-pointer py-1 text-xs text-text-secondary">{zh ? "查看具体原因" : "Check reasons"}</summary><ul className="space-y-1 text-xs leading-6 text-text-secondary">{receipt.reasons.map((reason, i) => <li key={`${i}-${reason}`} className="break-words">{strategyIssueText(reason, locale)}</li>)}</ul></details> : null}
  </section>;
}

function SavedStrategy({ entry, locale, disabled, onAction }: {
  entry: StrategyLibraryEntry; locale: Locale; disabled: boolean;
  onAction: (entry: StrategyLibraryEntry, action: "validate" | "enable") => void;
}) {
  const zh = locale === "zh";
  const definition = entry.definition;
  if (!definition) return <article className="border-b border-border-subtle py-6"><h2 className="text-lg">{entry.title}</h2><p className="mt-2 text-sm text-warning">{zh ? "这条记录缺少策略定义，无法验证或启用；其他策略不受影响。" : "This record is missing its strategy recipe and cannot be validated or enabled."}</p></article>;
  const validation = entry.validation;
  const metrics = validation?.platform_metrics;
  const bound = validation?.definition_digest === entry.definition_digest;
  const blockers = [...(validation?.blockers ?? []), ...(entry.activation_blockers ?? [])];
  const failed = entry.status === "validation_failed" || entry.status === "stale";
  const running = entry.status === "paper_running";
  const replacement = entry.admission_v2?.intent_kind === "replacement" || Boolean(entry.admission_v2?.target_sleeve_id);
  const frequency = definition.profile_snapshot?.family === "rsi_reversion"
    ? (zh ? "每日检查，条件触发" : "Daily conditional entries/exits")
    : ({ daily: zh ? "每日调仓" : "Daily", weekly: zh ? "每周调仓" : "Weekly", monthly: zh ? "每月调仓" : "Monthly" })[definition.rebalance];
  const error = strategyIssueText(entry.error, locale);
  const reasons = [...new Set([error, ...blockers.map(value => strategyIssueText(value, locale))].filter(Boolean))];
  return <article id={`strategy-${entry.strategy_id}`} className="scroll-mt-24 border-b border-border-subtle py-6 target:rounded-md target:bg-[var(--color-hermes-glow)] target:ring-1 target:ring-[var(--color-hermes)]" aria-label={entry.title}>
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-3"><h2 className="break-words text-lg font-semibold">{entry.title}</h2><span className={`text-xs ${failed ? "text-warning" : running || entry.status === "validated" ? "text-success" : "text-text-secondary"}`}>{replacement && entry.status === "validated" ? (zh ? "已验证 · 现有仓版本候选" : "Validated · existing-sleeve version candidate") : STATUS[entry.status]?.[zh ? 0 : 1] ?? entry.status}</span></div>
        {entry.research_evidence?.variant === "baseline" && intakeLocalValidationCompleted(entry) ? <p className="mt-1 text-xs text-[var(--color-hermes)]">{zh ? "本轮对照验证已完成 · 结果见下方，原条目状态保留" : "This comparison validation is complete · see results below; original entry status retained"}</p> : null}
        <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-text-secondary">
          <span>{definition.symbols.length} {zh ? "个标的" : "instruments"}</span><span>{frequency}</span><span>Top {definition.top_n}</span><span>{zh ? "基准" : "Benchmark"} {definition.benchmark_symbol}</span>
        </p>
        <p className="mt-1 text-xs leading-6 text-text-secondary">{zh ? "总仓位上限" : "Exposure cap"} {percent(definition.target_gross_exposure)} · {zh ? "单标的上限" : "Per-name cap"} {percent(definition.max_weight_per_symbol)}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {entry.status === "draft" || entry.status === "validation_failed" ? <button type="button" disabled={disabled} onClick={() => onAction(entry, "validate")} className={`${buttonClass} border-[var(--color-hermes)] text-[var(--color-hermes)]`}>{entry.status === "validation_failed" ? (zh ? "重新验证" : "Validate again") : (zh ? "验证这条策略" : "Validate strategy")}</button> : null}
        {entry.status === "validating" ? <span className="inline-flex items-center gap-2 text-sm text-[var(--color-hermes)]"><RefreshCw size={15} className="motion-safe:animate-spin"/>{zh ? "验证中，结果自动更新" : "Validation in progress"}</span> : null}
        {entry.status === "validated" && !replacement ? <button type="button" disabled={disabled || !canEnableSavedStrategy(entry)} onClick={() => onAction(entry, "enable")} className={`${buttonClass} border-[var(--color-hermes)] bg-[var(--color-hermes)] text-bg-base`}>{zh ? "启用 $10,000 模拟" : "Enable $10,000 paper"}</button> : null}
        {running ? <Link href={localizePath("/paper-trading", locale)} className={`${buttonClass} border-border-strong text-text-primary`}>{zh ? "查看模拟表现" : "View paper performance"}<ArrowUpRight size={14}/></Link> : null}
      </div>
    </div>
    {entry.status === "draft" ? <p className="mt-3 text-xs leading-6 text-text-secondary">{zh ? "规则已保存，尚未通过准入检查，也未分配模拟资金。" : "The recipe is saved; admission checks and paper allocation have not happened."}</p> : null}
    {entry.status === "superseded" ? <p className="mt-3 text-xs leading-6 text-text-secondary">{zh ? "同一模拟仓已改用新版本继续运行；这条旧规则不再用于该仓的日常运行，原验证与成交记录不会删除。" : "The same paper sleeve continues under a new version. This recipe is no longer active there; its original validations and fills are retained."}</p> : null}
    {entry.performance_scope === PERFORMANCE_SCOPE_CUMULATIVE_SLEEVE_HISTORY ? <p className="mt-3 text-xs leading-6 text-warning">{zh ? "模拟仓的累计盈亏包含升级前后的历史，不能作为新公式单独的成绩；当前版本表现仍需单独评价。" : "Cumulative sleeve P&L spans versions and is not the new formula's standalone performance."}</p> : null}
    {entry.status === "stale" ? <p className="mt-3 text-xs leading-6 text-warning">{zh ? "实现或参数已变化。请回原记录重新保存，再验证新版本。" : "Implementation or parameters changed. Save a fresh version from the original record before validation."}</p> : null}
    {entry.status === "validated" && !replacement && !canEnableSavedStrategy(entry) && !entry.activation_blockers?.length ? <p className="mt-3 text-xs leading-6 text-warning">{zh ? "这条版本的完整验证记录尚未确认，请刷新记录后查看。" : "A complete matching validation record is not confirmed. Refresh saved records."}</p> : null}
    {reasons.length ? <ul className="mt-3 space-y-1 text-sm leading-6 text-warning" aria-label={zh ? "未通过原因" : "Validation blockers"}>{reasons.map(reason => <li key={reason}>{reason}</li>)}</ul> : null}
    <AdmissionEvidence receipt={entry.admission_v2} locale={locale}/>
    <IntakeResearchEvidence entry={entry} locale={locale}/>
    {entry.research_evidence || entry.paper_runtime ? <PaperRuntimeEvidence runtime={entry.paper_runtime} locale={locale}/> : null}
    {validation && bound ? <div className="mt-4 flex flex-wrap items-baseline gap-x-6 gap-y-2 border-l-2 border-border-strong pl-4 text-xs">
      <span className="text-text-secondary">{zh ? "验证区间" : "Validation window"} {validation.start ?? "—"} → {validation.end ?? "—"}</span>
      {metrics ? <><span>{zh ? "完整组合回测净收益" : "Full-portfolio backtest return"} <span className="font-mono">{percent(metrics.total_return)}</span></span><span>Sharpe <span className="font-mono">{numeric(metrics.sharpe)}</span></span><span>{zh ? "最大回撤" : "Max drawdown"} <span className="font-mono">{percent(metrics.max_drawdown == null ? null : Math.abs(metrics.max_drawdown))}</span></span></> : null}
      {validation.simulation_allocation_usd ? <span className="text-text-secondary">{zh ? "按模拟资金" : "Evaluation cash"} ${validation.simulation_allocation_usd.toLocaleString("en-US")}</span> : null}
    </div> : null}
    <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-text-secondary">
      {entry.origin.type === "compose" ? <span>{zh ? "自定义因子组合" : "Custom factor composition"}</span> : <a href={strategyOriginHref(entry, locale)} className="app-touch-target inline-flex items-center gap-1 text-[var(--color-hermes)] hover:underline">{entry.origin.type === "backtest" ? (zh ? "原回测记录" : "Original backtest") : (zh ? "原研究记录" : "Original study")}<ArrowUpRight size={13}/></a>}
      <span>{zh ? "保存于" : "Saved"} {entry.created_at.replace("T", " ").slice(0, 16)}</span>
      {running ? <span>{zh ? "启用后按原调仓规则等待自然交易日运行，启用不代表已经成交。" : "Enabled strategies follow their schedule; enabled does not mean filled."}</span> : null}
    </div>
    <details className="group mt-2"><summary className="app-touch-target flex cursor-pointer list-none items-center gap-2 text-xs text-text-secondary"><ChevronDown size={14} className="group-open:rotate-180"/>{zh ? "固定规则与验证详情" : "Fixed recipe & validation details"}</summary>
      <div className="space-y-3 py-2 text-xs leading-6 text-text-secondary">
        <p className="break-words font-mono">{definition.symbols.join(" · ")}</p>
        {definition.formula?.expression ? <code className="block break-all text-text-primary">{definition.formula.expression}</code> : null}
        {definition.profile_snapshot?.formation ? <p>{definition.profile_snapshot.formation}</p> : null}
        {definition.factors?.length ? <ul className="space-y-2">{definition.factors.map(factor => <li key={factor.factor_id}><span className="font-mono text-text-primary">{factor.expression ? (zh ? "公式因子" : "Formula factor") : factor.factor_id}</span> · {factor.expression ? (zh ? "完整历史" : "history") : (zh ? "回看" : "lookback")} {factor.lookback} {zh ? "日" : "days"} · {zh ? "评分权重" : "signal weight"} {factor.weight} · {factor.direction === "lower_is_better" ? (zh ? "越低越优" : "Lower is better") : (zh ? "越高越优" : "Higher is better")}{factor.expression ? <code className="block break-all">{factor.expression}</code> : null}</li>)}</ul> : null}
        {bound && validation?.comparison ? <p>{zh ? "双引擎执行核对" : "Two-engine execution check"} · {validation.comparison.accepted ? (zh ? "通过" : "Passed") : (zh ? "未通过" : "Not passed")} · {zh ? "每日收益相关性" : "Daily return correlation"} {numeric(validation.comparison.daily_return_correlation)} · {zh ? "期末净值差" : "Terminal NAV difference"} {numeric(validation.comparison.terminal_nav_difference_bps)} bp</p> : null}
        {bound ? <FactorContribution analysis={validation?.signal_analysis} locale={locale}/> : null}
        <p>{zh ? "历史验证是固定版本的检查；前瞻表现从冻结后真实产生的模拟记录开始积累。" : "Historical validation checks a fixed version. Prospective performance accumulates from actual paper records after freezing."}</p>
      </div>
    </details>
  </article>;
}

export function WaitingResearchMaterials({ items, error, locale }: {
  items: StrategyDataNeed[]; error?: string | null; locale: Locale;
}) {
  if (!items.length && !error) return null;
  const zh = locale === "zh";
  return <section className="my-5 border-y border-warning/40 py-4" aria-label={zh ? "等待数据的研究材料" : "Research material awaiting data"}>
    <h2 className="text-lg font-medium">{zh ? "等待数据的研究材料" : "Research material awaiting data"}</h2>
    <p className="mt-2 text-xs leading-6 text-text-secondary">{zh ? "这些材料尚未完成本地验证，没有准入或启用结果；补齐原方法需要的数据后才能送测。" : "These materials have not completed local validation, admission or activation. Supply the original method's required data before testing."}</p>
    {error ? <p role="alert" className="mt-2 text-sm text-warning">{zh ? "等待数据的材料暂时无法核验，请检查原作业文件；不能据此判断没有待补材料。" : "Waiting material could not be verified. Inspect the original job files; this is not evidence of an empty queue."}</p> : null}
    {items.map(item => { const design = item.research_design, card = design?.hypothesis_card; return <article key={item.job_id} className="mt-4 border-t border-border-subtle pt-3 text-xs leading-6">
      <h3 className="break-words text-sm font-medium">{item.proposal_id} · {zh ? "材料待补" : "Waiting for data"}</h3>
      <p className="text-warning">{item.executable_strategy_count} {zh ? "个可执行策略 · 未完成本地验证" : "executable strategies · local validation incomplete"}</p>
      {item.expression ? <p className="mt-1">{zh ? "原提议公式（尚未执行）" : "Original proposed formula (not executed)"}<code className="block break-all">{item.expression}</code></p> : null}
      <p>{zh ? "原卡来源" : "Card source"} · {design?.source_title ?? "—"}</p>
      {design?.source_urls?.filter(url => /^https?:\/\//.test(url)).map((url, index) => <a key={url} className="mr-4 inline-block text-[var(--color-hermes)] hover:underline" href={url} target="_blank" rel="noreferrer">{zh ? "提交来源" : "Submitted source"} {index + 1}</a>)}
      {design?.adaptation_note ? <p>{zh ? "改编说明" : "Adaptation"} · {design.adaptation_note}</p> : null}
      {(design?.data_needs ?? []).map((need, index) => <p key={index} className="text-warning">{zh ? "待补字段" : "Missing fields"} · {need.fields?.join(" · ") || "—"}{need.data_need_ids?.length ? ` · ${need.data_need_ids.join(" · ")}` : ""}</p>)}
      <p>{zh ? "下一步：提供声明字段及历史时点口径后再送测；原公式与假设保留，不自动替换成价量代理。" : "Next: supply the declared fields and point-in-time rules before testing. Preserve the formula and hypothesis; do not substitute an OHLCV proxy."}</p>
      {card ? <details><summary className="app-touch-target cursor-pointer py-1 text-text-secondary">{zh ? "查看原研究假设卡" : "View original hypothesis card"}</summary>{card.mechanism ? <p>{zh ? "预期机制" : "Mechanism"} · {card.mechanism}</p> : null}{card.falsifiable_prediction ? <p>{zh ? "可证伪预测" : "Falsifiable prediction"} · {card.falsifiable_prediction}</p> : null}{card.test_protocol ? <p>{zh ? "测试方案" : "Test protocol"} · {card.test_protocol}</p> : null}<p>{zh ? "所需字段" : "Required fields"} · {card.required_fields?.join(" · ") || "—"}</p>{card.adaptation_diff ? <p>{zh ? "改编差异" : "Adaptation differences"} · {card.adaptation_diff}</p> : null}</details> : null}
      <p className="break-all font-mono text-[10px] text-text-secondary">{item.job_id}</p>
    </article>; })}
  </section>;
}

export function StrategyLibraryPanel({ locale, initialItems = null, initialDataNeeds = [] }: {
  locale: Locale; initialItems?: StrategyLibraryEntry[] | null;
  initialDataNeeds?: StrategyDataNeed[];
}) {
  const zh = locale === "zh";
  const [items, setItems] = useState(initialItems);
  const [dataNeeds, setDataNeeds] = useState(initialDataNeeds);
  const [dataNeedsError, setDataNeedsError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [reading, setReading] = useState(initialItems === null);
  const [uncertain, setUncertain] = useState(false);
  const [composing, setComposing] = useState(false);
  const pending = useRef(false), generation = useRef(0);
  const read = useCallback(async (signal?: AbortSignal) => {
    const requestGeneration = ++generation.current;
    try {
      const response = await getStrategyLibrary(signal);
      if (!signal?.aborted && requestGeneration === generation.current) {
        setItems(response.items); setError(null); setUncertain(false);
        setDataNeeds(response.data_needs ?? []);
        setDataNeedsError(response.data_needs_error ?? null);
      }
    } catch (reason) {
      if (!signal?.aborted && requestGeneration === generation.current) setError(reason instanceof Error ? reason.message : "Saved strategies unavailable");
    } finally { if (!signal?.aborted && requestGeneration === generation.current) setReading(false); }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => void read(controller.signal), 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [read]);
  useEffect(() => {
    if (!strategyLibraryNeedsPoll(items) || error || busy) return;
    const controller = new AbortController();
    const timer = setTimeout(() => void read(controller.signal), 3000);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [items, error, busy, read]);
  const locatedStrategy = useRef<string | null>(null);
  useEffect(() => {
    const target = new URLSearchParams(window.location.search).get("strategy");
    if (!target || !/^strategy-[0-9a-f]{24}$/.test(target) || locatedStrategy.current === target
      || !items?.some(entry => entry.strategy_id === target)) return;
    const element = document.getElementById(`strategy-${target}`);
    if (!element) return;
    const historicalSection = element.closest("details");
    if (historicalSection) historicalSection.open = true;
    element.scrollIntoView({ block: "start" });
    locatedStrategy.current = target;
  }, [items]);
  const act = async (entry: StrategyLibraryEntry, action: "validate" | "enable") => {
    if (pending.current || uncertain) return;
    pending.current = true; generation.current += 1; setReading(false); setBusy(entry.strategy_id); setError(null);
    try {
      const updated = await (action === "validate" ? validateSavedStrategy(entry) : enableSavedStrategy(entry));
      setItems(current => (current ?? []).map(item => item.strategy_id === updated.strategy_id ? updated : item));
    } catch (reason) {
      const unknown = reason instanceof StrategyMutationError && reason.outcomeUnknown;
      setUncertain(unknown);
      setError(unknown ? (zh ? "请求状态尚未确认。请刷新记录核对结果，再决定下一步。" : "Request outcome is unknown. Refresh records before another action.") : strategyIssueText(reason instanceof Error ? reason.message : reason, locale));
    } finally { pending.current = false; setBusy(null); }
  };
  const renderEntry = (entry: StrategyLibraryEntry) => <SavedStrategy key={entry.strategy_id} entry={entry} locale={locale} disabled={Boolean(busy) || uncertain} onAction={(item, action) => void act(item, action)}/>;
  const historical = (items ?? []).filter(entry => entry.status === "stale");
  const currentEntries = (items ?? []).filter(entry => entry.status !== "stale");
  // Every saved version can be stale at once (all 25 read as stale). The named main
  // landmark then must still carry content, so the historical list renders inside it.
  const historicalOnly = Boolean(items?.length) && currentEntries.length === 0;
  return <div className="mx-auto w-full max-w-[1280px] px-4 py-6 sm:px-7 lg:px-9">
    <header className="flex flex-wrap items-start justify-between gap-4 border-b border-border-strong pb-5"><div><h1 className="text-3xl font-semibold tracking-tight">{zh ? "我的策略" : "My strategies"}</h1><p className="mt-3 max-w-3xl text-sm leading-7 text-text-secondary">{zh ? "每条记录保存一套固定规则，保留各自的公式、因子参数、仓位和调仓频率。验证通过后，可启用 $10,000 模拟运行。" : "Each record keeps a fixed formula, factor parameters, position rules and rebalance schedule. Validated versions can enable $10,000 paper simulation."}</p></div><button type="button" disabled={reading || Boolean(busy)} onClick={() => { setReading(true); void read(); }} className={`${buttonClass} border-border-strong text-text-secondary`}><RefreshCw size={15} className={reading ? "motion-safe:animate-spin" : ""}/>{zh ? "刷新记录" : "Refresh records"}</button></header>
    <nav className="flex flex-wrap gap-5 py-4 text-sm" aria-label={zh ? "策略工作流" : "Strategy workflow"}><button type="button" aria-expanded={composing} aria-controls="strategy-factor-composer" onClick={() => setComposing(value => !value)} className="app-touch-target inline-flex items-center font-medium text-[var(--color-hermes)] hover:underline">{composing ? (zh ? "收起组合因子" : "Close factor composer") : (zh ? "组合因子" : "Compose factors")}</button><Link className="app-touch-target inline-flex items-center text-[var(--color-hermes)] hover:underline" href={localizePath("/research-evaluation?tab=studies", locale)}>{zh ? "从研究方案保存" : "Save from studies"}</Link><Link className="app-touch-target inline-flex items-center text-[var(--color-hermes)] hover:underline" href={localizePath("/backtest", locale)}>{zh ? "从我的回测保存" : "Save from backtests"}</Link><Link className="app-touch-target inline-flex items-center text-text-secondary hover:underline" href={localizePath("/paper-trading", locale)}>{zh ? "查看模拟盘" : "Paper account"}</Link></nav>
    {composing ? <div id="strategy-factor-composer"><FactorComposer locale={locale} onSaved={entry => { generation.current += 1; setItems(current => [entry, ...(current ?? []).filter(item => item.strategy_id !== entry.strategy_id)]); setReading(false); setComposing(false); }}/></div> : null}
    {error ? <p role="alert" className="mb-3 border-l-2 border-warning px-4 py-3 text-sm leading-6 text-warning">{error}</p> : null}
    <WaitingResearchMaterials items={dataNeeds} error={dataNeedsError} locale={locale}/>
    {items === null ? <p role="status" className="py-8 text-sm text-text-secondary">{error ? (zh ? "暂时无法读取已保存策略。" : "Saved strategies unavailable.") : (zh ? "正在读取已保存策略…" : "Loading saved strategies…")}</p> : items.length === 0 ? <p className="border-y border-border-subtle py-8 text-sm leading-7 text-text-secondary">{zh ? "还没有保存的策略。先在研究方案或回测详情中点击“保存到我的策略”，再回来验证该版本。" : "No saved strategies. Choose Save to My strategies on a study or backtest detail, then validate that version here."}</p> : <section aria-label={zh ? "已保存策略" : "Saved strategies"}>
      {historicalOnly ? <><h2 className="text-base font-medium">{zh ? "历史版本，保留原结果" : "Historical versions — original results retained"} · {historical.length}</h2><p className="mt-2 text-sm leading-7 text-text-secondary">{zh ? "当前没有与已保存规则一致的版本；下面保留的历史记录原始验证与成交结果不会删除。" : "No saved version currently matches its implementation; the historical records below keep their original validations and fills."}</p></> : null}
      {(historicalOnly ? historical : currentEntries).map(renderEntry)}
    </section>}
    {historical.length && !historicalOnly ? <details className="group mt-6 border-t border-border-subtle pt-3"><summary className="app-touch-target flex cursor-pointer list-none items-center gap-2 text-sm text-text-secondary"><ChevronDown size={15} className="group-open:rotate-180"/>{zh ? "历史版本，保留原结果" : "Historical versions — original results retained"} · {historical.length}</summary>{historical.map(renderEntry)}</details> : null}
    {strategyLibraryNeedsPoll(items) ? <p role="status" className="mt-4 text-xs text-text-secondary">{zh ? "验证任务在后台继续，页面每 3 秒读取进度。" : "Validation continues in the background; progress refreshes every 3 seconds."}</p> : null}
  </div>;
}
