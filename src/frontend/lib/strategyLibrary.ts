import { apiRequest } from "./apiClient";
import { ensureOwnerSession, ownerPostJson } from "./hermes/workspaceClient";
import { localizePath, type Locale } from "./locale";
import type { PaperRuntimeStatus } from "./api";

export type StrategyLibraryStatus =
  | "draft" | "validating" | "validation_failed" | "validated" | "paper_running" | "stale" | "superseded";

export type StrategyLibraryDefinition = {
  kind: "profile" | "formula" | "factor_blend";
  symbols: string[];
  benchmark_symbol: string;
  rebalance: "daily" | "weekly" | "monthly";
  top_n: number;
  max_weight_per_symbol?: number;
  target_gross_exposure?: number;
  normalization?: string;
  factors?: { factor_id: string; lookback: number; direction: string; weight: number; expression?: string | null }[];
  formula?: { expression: string } | null;
  profile_snapshot?: { family?: string; formation?: string; rules?: string[] } | null;
};

export type StrategyValidation = {
  status?: string;
  definition_digest?: string;
  simulation_allocation_usd?: number;
  platform_metrics?: Record<string, number | null>;
  // Sibling of platform_metrics: nested active blocks (active return / TE / IR /
  // beta-alpha / alpha_t / Sharpe CI / paired block bootstrap). Never merged into
  // the numeric platform_metrics index signature.
  active_metrics?: Record<string, unknown> | null;
  qlib?: Record<string, unknown>;
  comparison?: { accepted?: boolean; daily_return_correlation?: number | null; terminal_nav_difference_bps?: number | null };
  gates?: Record<string, unknown>;
  blockers?: unknown[];
  run_id?: string;
  start?: string;
  end?: string;
  signal_analysis?: StrategySignalAnalysis | null;
};

type StrategySignalMetrics = {
  rank_ic?: number | null; ic?: number | null; samples?: number | null; periods?: number | null;
};

export type StrategySignalAnalysis = {
  status?: string; reason?: unknown; scope?: unknown;
  score?: { all?: StrategySignalMetrics; recent?: StrategySignalMetrics; splits?: unknown };
  components?: { factor_id: string; all?: StrategySignalMetrics; recent?: StrategySignalMetrics }[];
  correlations?: { features?: string[]; matrix?: (number | null)[][]; method?: string; periods?: number | null };
  leave_one_out?: { factor_id: string; rank_ic_delta_full_minus_without?: number | null; paired_samples?: number | null }[];
  ridge?: {
    status?: string; reason?: unknown; folds?: unknown[]; fixed_score_metrics?: StrategySignalMetrics;
    ridge_metrics?: StrategySignalMetrics; rank_ic_delta?: number | null; matched_samples?: number | null;
  };
};

export type StrategyLibraryEntry = {
  strategy_id: string;
  title: string;
  definition_digest: string;
  created_at: string;
  definition: StrategyLibraryDefinition;
  origin: { type: string; run_id: string; profile_id?: string | null };
  status: StrategyLibraryStatus;
  validation: StrategyValidation | null;
  candidate_id?: string | null;
  sleeve_id?: string | null;
  error?: unknown;
  execution_ready?: boolean;
  activation_blockers?: string[];
  admission_v2?: {
    mode?: string; status?: string; validated_tier?: string; reasons?: string[];
    intent_kind?: string; target_sleeve_id?: string;
  } | null;
  performance_scope?: string;
  replaced_by?: string | null;
  research_evidence?: Record<string, unknown> | null;
  paper_runtime?: PaperRuntimeStatus | null;
};

// Mirrors the backend paper-evaluation scope string; the frontend must not restate
// the literal at each call site or it can drift from the report it interprets.
export const PERFORMANCE_SCOPE_CUMULATIVE_SLEEVE_HISTORY = "cumulative_sleeve_history_across_versions";

export type StrategySaveSource =
  | { type: "study"; runId: string; profileId: string }
  | { type: "backtest"; runId: string };

export type StrategyFactorOption = {
  factor_id: string; label: string; expression: string | null; lookback: number;
  direction: "higher_is_better" | "lower_is_better"; origin: unknown;
  research_only?: boolean;
  source_refs?: { strategy_id: string; title: string; source_type?: string; saved_status?: string }[];
};

export type StrategyComposeRequest = {
  kind: "factor_blend"; title: string; symbols: string[]; benchmark_symbol: string;
  rebalance: "daily" | "weekly" | "monthly"; top_n: number;
  normalization: "rank" | "zscore"; max_weight_per_symbol: number;
  target_gross_exposure: number; min_order_value: number;
  factors: { factor_id: string; expression: string | null; lookback: number;
    direction: "higher_is_better" | "lower_is_better"; weight: number }[];
};

const DIGEST = /^[0-9a-f]{64}$/i;
const record = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : {};

export function studySaveSource(runId: unknown, profileId: unknown, status: unknown): StrategySaveSource | null {
  return status === "available" && typeof runId === "string" && runId.length > 0
    && typeof profileId === "string" && profileId.length > 0
    ? { type: "study", runId, profileId } : null;
}

export function discoverySaveSource(discovery: unknown, result: unknown): StrategySaveSource | null {
  const saved = record(result);
  return studySaveSource(record(discovery).origin_run_id, record(saved.profile).id, saved.status);
}

export function getStrategyLibrary(signal?: AbortSignal) {
  return apiRequest<{ items: StrategyLibraryEntry[]; data_needs?: StrategyDataNeed[]; data_needs_error?: string }>("/api/strategy-library", { signal });
}

export type StrategyDataNeed = {
  job_id: string; proposal_id: string; status: "waiting_data"; expression?: string;
  executable_strategy_count: number; created_at?: string;
  research_design?: {
    source_title?: string; source_urls?: string[]; adaptation_note?: string;
    hypothesis_card?: { mechanism?: string; falsifiable_prediction?: string; required_fields?: string[]; test_protocol?: string; adaptation_diff?: string; data_need_ids?: string[] };
    data_needs?: { reason?: string; fields?: string[]; data_need_ids?: string[]; next_step?: string }[];
  };
};

export function getSavedStrategy(strategyId: string, signal?: AbortSignal) {
  return apiRequest<StrategyLibraryEntry>(`/api/strategy-library/${encodeURIComponent(strategyId)}`, { signal });
}

export function getStrategyFactorOptions(signal?: AbortSignal) {
  return apiRequest<{ factors: StrategyFactorOption[] }>("/api/strategy-library/factor-options", { signal });
}

export function parseStrategySymbols(raw: string): string[] {
  const symbols = raw.split(/[,，\s]+/).map(value => value.trim().toUpperCase()).filter(Boolean);
  if (!symbols.length || new Set(symbols).size !== symbols.length) throw new Error("strategy_composition_symbols_invalid");
  return symbols;
}

export class StrategyMutationError extends Error {
  constructor(message: string, public readonly outcomeUnknown: boolean) {
    super(message);
    this.name = "StrategyMutationError";
  }
}

async function mutate(path: string, body: unknown): Promise<StrategyLibraryEntry> {
  await ensureOwnerSession();
  try {
    return await ownerPostJson<StrategyLibraryEntry>(path, body);
  } catch (reason) {
    const error = record(reason);
    const status = typeof error.status === "number" ? error.status : undefined;
    throw new StrategyMutationError(
      reason instanceof Error ? reason.message : "Strategy request failed",
      error.code === "outcome_unknown" || status === undefined || status >= 500,
    );
  }
}

export function saveStrategyVersion(source: StrategySaveSource, title?: string) {
  const name = title?.trim();
  return source.type === "study"
    ? mutate("/api/strategy-library/import-study", {
        run_id: source.runId, profile_id: source.profileId, ...(name ? { title: name } : {}),
      })
    : mutate("/api/strategy-library/import-backtest", {
        run_id: source.runId, ...(name ? { title: name } : {}),
      });
}

export function composeStrategy(request: StrategyComposeRequest) {
  if (!request.title.trim()) throw new Error("strategy_composition_title_required");
  if (!request.symbols.length || new Set(request.symbols).size !== request.symbols.length
    || !Number.isInteger(request.top_n) || request.top_n < 1 || request.top_n > request.symbols.length) {
    throw new Error("strategy_composition_symbols_invalid");
  }
  if (!request.factors.length || new Set(request.factors.map(item => item.factor_id)).size !== request.factors.length
    || request.factors.some(item => !Number.isInteger(item.lookback) || item.lookback < 1 || item.lookback > 1260 || !Number.isFinite(item.weight))
    || request.factors.every(item => item.weight === 0)) throw new Error("strategy_composition_factors_invalid");
  if (!Number.isFinite(request.max_weight_per_symbol) || request.max_weight_per_symbol <= 0 || request.max_weight_per_symbol > 1
    || !Number.isFinite(request.target_gross_exposure) || request.target_gross_exposure < 0 || request.target_gross_exposure > 1
    || !Number.isFinite(request.min_order_value) || request.min_order_value < 0) throw new Error("strategy_composition_limits_invalid");
  return mutate("/api/strategy-library/compose", { ...request, title: request.title.trim() });
}

export function validateSavedStrategy(entry: StrategyLibraryEntry) {
  if (!DIGEST.test(entry.definition_digest)) throw new Error("strategy_definition_digest_missing");
  return mutate(`/api/strategy-library/${encodeURIComponent(entry.strategy_id)}/validate`, {
    expected_digest: entry.definition_digest,
  });
}

export function canEnableSavedStrategy(entry: StrategyLibraryEntry): boolean {
  return entry.status === "validated" && DIGEST.test(entry.definition_digest)
    && entry.admission_v2?.intent_kind !== "replacement"
    && !entry.admission_v2?.target_sleeve_id
    && entry.execution_ready !== false
    && entry.validation?.definition_digest === entry.definition_digest
    && entry.validation.comparison?.accepted === true
    && (entry.validation.blockers?.length ?? 0) === 0
    && Boolean(entry.candidate_id) && !entry.sleeve_id;
}

export function enableSavedStrategy(entry: StrategyLibraryEntry) {
  if (!canEnableSavedStrategy(entry)) throw new Error("strategy_validation_required");
  return mutate(`/api/strategy-library/${encodeURIComponent(entry.strategy_id)}/enable`, {
    expected_digest: entry.definition_digest,
  });
}

export function strategyLibraryNeedsPoll(items: StrategyLibraryEntry[] | null): boolean {
  return Boolean(items?.some(entry => entry.status === "validating"));
}

export function strategyOriginHref(entry: StrategyLibraryEntry, locale: Locale): string {
  if (entry.origin.type === "backtest") {
    return localizePath(`/backtest/${encodeURIComponent(entry.origin.run_id)}`, locale);
  }
  if (entry.origin.profile_id) {
    return `/api/strategy-studies/${encodeURIComponent(entry.origin.run_id)}/profiles/${encodeURIComponent(entry.origin.profile_id)}`;
  }
  return localizePath("/research-evaluation?tab=studies", locale);
}

const REASONS: Record<string, string> = {
  qualification_missing: "尚未取得本次数据和实现对应的完整检查记录。",
  qualification_recipes_not_enabled: "这套检查流程尚未配置启用，未授予模拟运行资格。",
  qualification_dataset_unsupported: "本次数据集不在已验证范围内，不能套用其他数据的通过结果。",
  qualification_dataset_universe_unsupported: "本次股票名单不在这份检查记录覆盖的范围内。",
  qualification_fixed_check_timeout: "检查程序超时，本次结果尚未确认。",
  qualification_production_busy: "已有检查正在进行，稍后将按重试安排继续。",
  admission_v2_authority_disabled: "新检查仍用于并列对照，尚未切换为模拟运行的准入规则。",
  admission_v2_code_changed: "检查后计算实现发生变化，需要对当前实现重新检查。",
  admission_v2_baseline_input_mismatch: "原策略与新策略使用的数据不一致，暂不能作改善程度的比较。",
  admission_v2_qualification_preflight_required: "尚未完成本次启用前的检查，不会据旧结果直接启用。",
  replacement_authority_disabled: "现有模拟仓的版本更新条件尚未满足，原仓未因此切换。",
  strategy_version_replaced: "这条版本已由新版本接续，历史记录保留，不能再作为当前版本启用。",
  trial_run_id_conflict: "研究记录的身份或统计与已有记录冲突，验证已停止，未启用模拟。",
  strategy_definition_schema_changed: "旧版本未保存完整的计算规则，需要重新保存并验证；历史结果保留供复查。",
  strategy_definition_schedule_unavailable: "策略验证可用，但自动日程尚未支持完整的开盘调仓检查，暂不能启用。",
  strategy_validation_receipt_requires_refresh: "验证文件或计算实现已变化，请重新验证当前策略版本。",
  candidate_validation_changed: "本次验证与原候选记录不同，请保存本次验证对应的新候选。",
  dsr_failed: "考虑已尝试方案数量后的统计质量检查未通过。",
  correlated_duplicate: "与已运行策略的收益过于接近，未通过重复度检查。",
  cost_sensitivity_failed: "提高交易成本后的检查未通过。",
  backtest_history_snapshot_missing_rerun_required: "旧回测未保存指标初始化行情。请重跑一次真实回测后再保存策略。",
  strategy_validation_required: "这条固定版本尚未通过验证。",
  strategy_content_digest_mismatch: "保存内容与固定版本不一致，请从原记录重新保存。",
  strategy_algorithm_source_mismatch: "冻结计算规则与当前实现不一致，原版本不能生成新信号。",
  strategy_factor_source_mismatch: "因子实现已更新，请从原记录保存新版本。",
  strategy_benchmark_calendar_incomplete: "基准行情缺少交易日，暂时无法验证。",
  strategy_calendar_price_session_mismatch: "行情日期与交易日历不一致。",
  strategy_no_signal_with_complete_history: "完整历史不足，尚无可用于验证的信号。",
  qlib_unavailable: "Qlib 验证结果尚不可用。",
  dsr_below_threshold: "策略质量检查未通过。",
  max_hung_correlation: "与已运行策略的相关性未通过检查。",
  strategy_whole_share_not_supported: "当前模拟执行暂不支持这条策略的整股规则。",
  strategy_composition_title_required: "请填写组合名称。",
  strategy_composition_symbols_invalid: "请填写不重复的股票代码，选股数量不能超过股票池数量。",
  strategy_composition_factors_invalid: "请至少选择一个因子，填写有效的历史窗口，且权重不能全部为零。",
  strategy_composition_limits_invalid: "仓位上限须在 0–100% 内，单标的上限须大于 0，最小交易金额不能为负。",
  strategy_formula_factor_lookback_too_short: "公式的完整历史窗口短于公式所需数据，请增加天数。",
  strategy_formula_factor_id_mismatch: "该公式与保存的因子版本不一致，请刷新可选因子。",
};

export function strategyIssueText(value: unknown, locale: Locale): string {
  if (value === null || value === undefined || value === "") return "";
  const item = record(value);
  const raw = typeof value === "string" ? value
    : typeof item.message === "string" ? item.message
      : typeof item.reason === "string" ? item.reason
        : typeof item.code === "string" ? item.code : "Validation detail unavailable";
  if (locale !== "zh") return raw;
  for (const [prefix, label] of [
    ["qualification_data:", "数据检查"],
    ["qualification_review:", "计算规则检查"],
    ["qualification_consumer:", "模拟运行接线检查"],
  ]) {
    if (raw.startsWith(prefix)) {
      const reason = raw.slice(prefix.length);
      return `${label}尚未取得有效结果：${REASONS[reason] ?? reason}`;
    }
  }
  return REASONS[raw] ?? raw;
}
