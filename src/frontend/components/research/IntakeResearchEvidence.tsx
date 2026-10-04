import type { Locale } from "@/lib/locale";
import { strategyIssueText, type StrategyLibraryEntry } from "@/lib/strategyLibrary";

const record = (value: unknown): Record<string, unknown> => value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
const rows = (value: unknown) => Array.isArray(value) ? value.map(record) : [];
const string = (value: unknown, fallback = "—") => typeof value === "string" && value ? value : fallback;
const number = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? value.toFixed(4) : "—";
const strings = (value: unknown) => Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];

export function intakeLocalValidationCompleted(entry: StrategyLibraryEntry): boolean {
  const evidence = entry.research_evidence;
  if (!evidence || evidence.definition_digest !== entry.definition_digest) return false;
  const current = rows(record(evidence.admission).variants).find(value => value.variant === evidence.variant);
  return Boolean(current?.validation_run_id) && ["validated", "validation_failed", "paper_running"].includes(string(current?.status));
}

function reason(value: unknown, zh: boolean) {
  const messages: Record<string, string> = {
    factor_scorecard_not_recorded_for_this_input: "该输入尚无因子级记分卡，历史组合结果仍保留。下一步在同一冻结输入上补因子评价。",
    factor_receipt_integrity_failed: "因子评价文件或身份校验失败。须恢复原冻结文件后再使用指标。",
    intake_evidence_unavailable: "研究证据暂时无法读取。请核对原作业文件，不能据此判断通过。",
    intake_pair_not_comparable: "原组合与增强组合没有完整的同输入对照，暂不能判断增量。",
    intake_baseline_required: "缺少指定的原组合对照，尚未评价组合增量。",
    intake_increment_objective_required: "原记录未提前声明增量目标，不能事后认定达标。",
    intake_increment_objective_not_met: "加入因子后未达到事先声明的改善目标。",
    intake_increment_metric_missing: "比较指标缺失；先恢复同输入的原始验证结果。",
    multiple_years_required: "跨年样本不足，稳定性尚未评价。",
    existing_admission_rejected_fixed_local_combination: "该固定本地组合未通过原准入检查。",
    review_existing_evidence_before_any_new_protocol: "先复核现有证据，再决定新的研究设计。",
    declared_fields_unavailable: "声明需要的数据字段尚未提供。",
  };
  return zh ? messages[string(value)] ?? strategyIssueText(value, "zh") : string(value, "Evidence unavailable");
}

export function IntakeResearchEvidence({ entry, locale }: { entry: StrategyLibraryEntry; locale: Locale }) {
  const evidence = entry.research_evidence;
  if (!evidence) return null;
  const zh = locale === "zh";
  const design = record(evidence.research_design), local = record(design.local_factor), portfolio = record(design.portfolio);
  const card = record(design.hypothesis_card), disposition = record(evidence.disposition);
  const factor = record(evidence.factor_evaluation), stability = record(factor.stability), redundancy = record(factor.redundancy);
  const increment = record(evidence.portfolio_increment), admission = record(evidence.admission), identity = record(evidence.identity);
  const current = rows(admission.variants).find(value => value.variant === evidence.variant);
  const bound = evidence.definition_digest === entry.definition_digest;
  const factorReady = bound && Object.keys(record(factor.horizons)).length > 0;
  const localCompleted = intakeLocalValidationCompleted(entry);
  const blocked = strings(current?.blockers);
  const parallel = admission.mode === "parallel";
  const baseline = evidence.variant === "baseline";
  const selection = ({ bottom: zh ? "最低分" : "Bottom", positive_top: zh ? "正分优先" : "Positive top", top: zh ? "最高分" : "Top" } as Record<string, string>)[string(portfolio.selection)] ?? string(portfolio.selection);
  const names: Record<string, string> = { symbols: "股票池", benchmark_symbol: "基准", rebalance: "调仓频率", top_n: "选股数量", normalization: "评分方法", selection: "方向", max_weight_per_symbol: "单股上限", target_gross_exposure: "总仓位", min_order_value: "最小订单", factor_weights: "因子权重" };
  return <section className="mt-4 border-t border-border-subtle pt-4" aria-label={zh ? "Grok 研究验证链" : "Grok research evidence chain"}>
    <h3 className="text-sm font-medium">{zh ? "这项研究究竟完成了什么" : "What this research actually completed"}</h3>
    {baseline ? <p className="mt-2 text-xs leading-6 text-warning">{zh ? "本页是本次比较的原组合。下面的因子评价属于新增因子，原组合没有包含它；原组合的验证、准入与模拟记录仍单独列示。" : "This page is the baseline portfolio. The factor evidence below belongs to the added factor, which is absent from this baseline; baseline validation, admission and paper evidence remain separate."}</p> : null}
    {baseline && localCompleted ? <p className="mt-1 text-xs leading-6 text-text-secondary">{zh ? "本轮对照验证结果见下方；原策略条目状态未更新。验证完成不等于准入通过。" : "The completed comparison validation is recorded below; the original strategy entry status was not updated. Completion does not imply admission passed."}</p> : null}
    <dl className="mt-2 grid gap-x-4 gap-y-1 text-xs leading-6 sm:grid-cols-[auto_1fr]">
      <dt className="text-text-secondary">{zh ? "材料可送测" : "Materials for testing"}</dt><dd>{design.materials_status === "waiting_data" ? (zh ? "材料待补，尚不可送测" : "Required data is missing; not ready for testing") : design.materials_status === "ready_for_local_test" ? (zh ? "符合本地送测要求；原方法尚未独立核实" : "Ready for local testing; original method not independently verified") : design.materials_status === "legacy_v1_local_formula_only_original_method_unknown" ? (zh ? "旧版本地公式材料已保存；原方法材料不完整" : "Legacy local formula saved; original method evidence is incomplete") : evidence.job_id ? (zh ? "已保存本地投递记录；原方法尚未独立核实" : "Local submission saved; original method not independently verified") : reason(evidence.reason, zh)}</dd>
      <dt className="text-text-secondary">{zh ? "本地验证" : "Local validation"}</dt><dd>{localCompleted ? (zh ? "已保存本版本验证结果，质量结论另列" : "Validation result saved for this version; quality decision below") : (zh ? "本页未取得同版本完整验证结果" : "Matching version validation unavailable")}</dd>
      <dt className="text-text-secondary">{zh ? "准入" : "Admission"}</dt><dd>{blocked.length ? (zh ? "原准入检查未通过" : "Original admission checks failed") : current?.status === "validated" || current?.status === "paper_running" ? (zh ? "原检查结果已保存；实际启用另列" : "Original check result saved; enablement is separate") : (zh ? "尚无可确认的准入通过结果" : "No confirmed admission pass")}{parallel ? (zh ? "；新规则仅并列对照" : "; new rules are comparison only") : ""}</dd>
    </dl>
    {!bound ? <p className="mt-2 text-xs text-warning">{zh ? "研究与页面版本身份不一致，以下指标不作该版本的验证凭据。" : "Research and page version identities differ; these metrics do not validate this version."}</p> : null}
    {blocked.length ? <p className="mt-2 text-xs leading-6 text-warning">{blocked.map(value => strategyIssueText(value, locale)).join(" · ")}</p> : null}
    <details className="mt-2" open={factorReady}><summary className="app-touch-target cursor-pointer py-2 text-xs text-text-secondary">{zh ? "因子本身 → 指定组合增量 → 准入依据" : "Factor evidence → portfolio increment → admission evidence"}</summary>
      <div className="space-y-4 text-xs leading-6">
        <div><h4 className="font-medium">{zh ? "研究对象与交易方案" : "Research object and trading recipe"}</h4>
          <p className="mt-1 text-text-secondary">{zh ? "论文原方法、本地价量代理、完整交易组合分别记录；有来源链接不等于已复现原文。" : "Original method, local OHLCV proxy and full portfolio are separate objects; a citation does not establish reproduction."}</p>
          {design.source_title ? <p>{zh ? "提交来源" : "Submitted source"} · {string(design.source_title)}</p> : null}
          {design.adaptation_note ? <p className="text-text-secondary">{zh ? "本地改编说明" : "Local adaptation"} · {string(design.adaptation_note)}</p> : <p className="text-text-secondary">{zh ? "本页未取得改编说明，不能据此认定完整复现。" : "An adaptation description is not available here; full reproduction is not established."}</p>}
          {Object.keys(card).length ? <details><summary className="app-touch-target cursor-pointer py-1 text-text-secondary">{zh ? "已保存的研究假设卡" : "Saved hypothesis card"}</summary><dl className="space-y-1">{Object.entries({ mechanism: zh ? "预期机制" : "Mechanism", who_loses: zh ? "预期收益由谁承担" : "Who bears the cost", falsifiable_prediction: zh ? "可证伪预测" : "Falsifiable prediction", test_protocol: zh ? "预先测试方案" : "Test protocol", prior_evidence: zh ? "已有证据" : "Prior evidence", expressibility: zh ? "本地可实现范围" : "Local expressibility", adaptation_diff: zh ? "与来源方法的差异" : "Adaptation differences" }).map(([key, label]) => card[key] ? <div key={key}><dt className="text-text-secondary">{label}</dt><dd className="break-words">{string(card[key])}</dd></div> : null)}<div><dt className="text-text-secondary">{zh ? "需要的字段" : "Required fields"}</dt><dd>{strings(card.required_fields).join(" · ") || "—"}</dd></div></dl></details> : null}
          {local.expression ? <code className="mt-1 block break-all">{string(local.expression)}</code> : <p>{zh ? "旧记录未保存完整研究设计；不能事后补写成已预先冻结。" : "No complete design was saved; it cannot be retroactively labeled pre-frozen."}</p>}
          {local.direction ? <p>{zh ? "方向" : "Direction"} · {local.direction === "higher_is_better" ? (zh ? "得分越高越优" : "Higher scores rank first") : string(local.direction)} · {zh ? "完整历史窗口" : "Required history"} {typeof factor.lookback === "number" ? factor.lookback : "—"} {zh ? "日" : "days"}</p> : null}
          {Object.keys(portfolio).length ? <><p>{baseline ? (zh ? "比较对象：加入因子后的完整组合" : "Comparison target: full augmented portfolio") : (zh ? "完整组合" : "Full portfolio")} · {strings(portfolio.symbols).length} {zh ? "股" : "symbols"} · {({ daily: zh ? "每日" : "Daily", weekly: zh ? "每周" : "Weekly", monthly: zh ? "每月" : "Monthly" } as Record<string, string>)[string(portfolio.rebalance)] ?? string(portfolio.rebalance)} · {selection} {String(portfolio.top_n ?? "—")} · {string(portfolio.start)} → {string(portfolio.end)} · {zh ? "佣金/滑点" : "Commission/slippage"} {String(portfolio.commission_bps ?? "—")} / {String(portfolio.slippage_bps ?? "—")} bp</p><p className="break-words text-text-secondary">{zh ? "股票池" : "Universe"} · {strings(portfolio.symbols).join(" · ")}</p><p className="break-words text-text-secondary">{zh ? "因子评分权重（非持仓比例）" : "Factor score weights (not position weights)"} · {Object.entries(record(portfolio.factor_weights)).map(([key, value]) => `${key}: ${String(value)}`).join(" · ")}</p></> : null}
          {strings(design.inherited_defaults).length ? <p className="text-warning">{zh ? "以下项目沿用默认值，不能视为原论文设定" : "Inherited defaults, not the original paper's method"} · {strings(design.inherited_defaults).map(value => zh ? names[value] ?? value : value).join("、")}</p> : null}
          {design.frozen_before_evaluation === false ? <p className="text-warning">{zh ? "既有提案隔离复算，不是新研究或自然模拟结果。本说明为旧记录事后补充，未改变原判定，也不证明当时已预先声明。" : "This is an isolated replay of an existing proposal, not new research or natural paper results. The description was added retrospectively; original decisions and predeclaration status are unchanged."}</p> : null}
          {rows(design.data_needs).length ? <div className="text-warning"><p>{zh ? "待补的数据与方法材料" : "Outstanding data and method requirements"}</p>{rows(design.data_needs).map((need, index) => <p key={index}>{strings(need.fields).join(" · ") || string(need.reason)}{strings(need.data_need_ids).length ? ` · ${strings(need.data_need_ids).join(" · ")}` : ""} · {need.next_step === "provide_declared_fields_and_pit_contract_before_testing" ? (zh ? "先提供声明字段和历史时点口径，再送测；不替换成价量代理。" : "Supply declared fields and point-in-time rules before testing; no OHLCV proxy substitution.") : (zh ? "补齐原方法、改编差异与测试方案后复核。" : "Complete the original method, adaptations and protocol for review.")}</p>)}</div> : null}
          {strings(design.source_urls).filter(url => /^https?:\/\//.test(url)).map((url, index) => <a key={url} href={url} target="_blank" rel="noreferrer" className="mr-4 inline-block text-[var(--color-hermes)] hover:underline">{zh ? "提交者提供的来源" : "Submitted source"} {index + 1}</a>)}
        </div>
        <div><h4 className="font-medium">{zh ? "1. 因子本身的预测与分组表现" : "1. Factor prediction and group behavior"}</h4>
          <p className="text-text-secondary">{zh ? "排序相关性（Rank IC）表示分数与未来收益的排序关系；分组标签与组合收益分开。" : "Rank IC measures score versus future-return ranks; group labels are separate from portfolio returns."}</p>
          {factorReady ? <div className="mt-2 overflow-x-auto"><table className="w-full min-w-[380px] text-left"><thead><tr>{[zh ? "未来天数" : "Horizon", "Rank IC", zh ? "有效期数" : "Periods", zh ? "分组单调" : "Monotonic groups"].map(name => <th key={name} className="border-b border-border-subtle py-2 pr-3 font-normal text-text-secondary">{name}</th>)}</tr></thead><tbody>{Object.entries(record(factor.horizons)).map(([horizon, value]) => { const block = record(value), ic = record(block.ic), groups = record(block.quantiles); return <tr key={horizon}><td className="py-2">{horizon}</td><td>{number(ic.rank_ic_mean)}</td><td>{String(ic.n_days ?? "—")}</td><td>{typeof groups.quantile_monotonic === "boolean" ? groups.quantile_monotonic ? (zh ? "是" : "Yes") : (zh ? "否" : "No") : "—"}</td></tr>; })}</tbody></table></div> : <p className="text-warning">{reason(factor.reason ?? evidence.reason, zh)}</p>}
          <p>{zh ? "跨时段稳定性" : "Time stability"} · {stability.status === "ready" ? (zh ? `已分 ${new Set(rows(stability.by_year).map(value => value.year)).size} 个年份描述；不等于独立留出通过` : "Yearly descriptions saved; not an independent holdout pass") : reason(stability.reason ?? factor.reason, zh)}</p>
          {factorReady && rows(stability.by_year).length ? <details><summary className="app-touch-target cursor-pointer py-1 text-text-secondary">{zh ? "逐年 Rank IC" : "Rank IC by year"}</summary><ul>{rows(stability.by_year).map((row, index) => <li key={index}>{String(row.year ?? "—")} · {String(row.horizon ?? "—")} {zh ? "日" : "days"} · {number(row.rank_ic_mean)} · {String(row.n_days ?? "—")} {zh ? "期" : "periods"}</li>)}</ul></details> : null}
          <p>{zh ? "与已声明基线因子的最大相关" : "Maximum correlation with declared baseline factors"} · {factorReady ? number(redundancy.max_abs_factor_correlation) : "—"}{redundancy.reason ? ` · ${reason(redundancy.reason, zh)}` : ""}</p>
        </div>
        <div><h4 className="font-medium">{zh ? "2. 对指定组合的增量" : "2. Increment to the specified portfolio"}</h4>
          <p className="text-text-secondary">{zh ? "这里只比较原组合与加入后的完整组合，收益不是单因子的收益。" : "This compares complete baseline and augmented portfolios; returns are not standalone factor returns."}</p>
          {bound && rows(increment.checks).length ? <ul className="mt-1 space-y-1">{rows(increment.checks).map((check, i) => <li key={i}>{string(check.metric)} · {number(check.baseline)} → {number(check.augmented)} · {zh ? "改善" : "Improvement"} {number(check.improvement)} / {zh ? "要求" : "Required"} {number(check.minimum)} · {check.passed === true ? (zh ? "该项达标" : "This check passed") : (zh ? "该项未达标" : "This check failed")}</li>)}</ul> : <p>{reason(increment.reason, zh)}</p>}
        </div>
        <div><h4 className="font-medium">{zh ? "3. 准入依据" : "3. Admission evidence"}</h4><p>{zh ? "因子记分卡不自动授予模拟资金。增量、双引擎、统计质量、重复度、成本及当前版本资格仍按原规则分别检查。" : "A factor scorecard grants no paper capital. Increment, two-engine checks, quality, duplication, costs and current-version qualification retain their existing rules."}</p></div>
        {disposition.action ? <div><h4 className="font-medium">{zh ? "本项研究结论与下一步" : "Disposition and next step"}</h4><p>{({ build_data: zh ? "建设数据或补齐评价材料" : "Build data or complete evaluation evidence", archive_hypothesis: zh ? "归档该冻结假设，保留失败依据" : "Archive this frozen hypothesis and retain failure evidence", continue_research: zh ? "继续研究，先复核已有依据" : "Continue research after reviewing existing evidence" } as Record<string, string>)[string(disposition.action)] ?? string(disposition.action)} · {reason(disposition.reason, zh)}</p><p className="text-text-secondary">{zh ? "结论只针对这套冻结因子与组合；尚不能推断整个研究方向或原论文无效。保留原方向和窗口，不通过改名、反向或换窗口重复投递。" : "This applies only to the frozen factor and portfolio, not the whole research direction or original paper. Retain the direction and window; do not resubmit renamed or reversed variants."}</p></div> : null}
        <details><summary className="app-touch-target cursor-pointer py-1 text-text-secondary">{zh ? "输入与文件身份" : "Input and receipt identity"}</summary><div className="break-all font-mono text-[10px] text-text-secondary">{Object.entries(identity).map(([key, value]) => <p key={key}>{key}: {typeof value === "string" ? value : JSON.stringify(value)}</p>)}<p>factor_receipt_sha256: {string(evidence.factor_receipt_sha256)}</p></div></details>
      </div>
    </details>
  </section>;
}
