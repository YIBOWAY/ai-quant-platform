import type { Locale } from "@/lib/locale";

export type CandidatePresentationInput = {
  candidate_id?: string | null;
  factor_id?: string | null;
  objective?: string | null;
  universe?: string[] | null;
  status?: string | null;
  display_name?: string | null;
  display_name_zh?: string | null;
  summary_zh?: string | null;
  activation_eligibility?: {
    eligible: boolean;
    reason: string | null;
  } | null;
};

export type CandidatePresentation = {
  name: string;
  summary: string;
  activationNote?: string;
};

const legacyChinesePresentation: Record<string, CandidatePresentation> = {
  "artifact-d489583fb04bdc04": {
    name: "21 日横截面动量策略",
    summary: "在 SPY、QQQ、NVDA、AAPL 中比较 21 日横截面动量，模拟运行中并按每日信号执行。",
  },
  "artifact-a604ad9ad2792c32": {
    name: "低配置横截面选股因子",
    summary: "在 SPY、QQQ、IWM、DIA 中验证横截面选股因子，当前停在已验证候选。",
  },
};

const legacyFactorNamesZh: Record<string, string> = {
  d34_a729eaa08c87d0e9a03b5e16: "21 日横截面动量策略",
  d34_4eb6fc0baf6a51693334004f: "低配置横截面选股因子",
  d34_1db5c7ea145724552d6e0fbe: "历史测试因子",
  d34_8efab9721018ce5911ee4098: "历史测试因子",
  d34_d2b11f17dbea9a4cb2df8d7a: "历史测试因子",
};

function clean(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed || null;
}

function chineseFallbackName(input: CandidatePresentationInput): string {
  const symbols = (input.universe ?? []).filter(Boolean).slice(0, 3);
  return symbols.length ? `${symbols.join("、")} 标的因子候选` : "已验证因子候选";
}

function chineseFallbackSummary(input: CandidatePresentationInput): string {
  return input.status === "hung"
    ? "该因子正在模拟运行，技术身份可在下方展开查看。"
    : "该因子已完成研究验证，尚未启用模拟运行。";
}

function englishFallbackName(input: CandidatePresentationInput): string {
  const symbols = (input.universe ?? []).filter(Boolean).slice(0, 3);
  return symbols.length
    ? `${symbols.join(", ")} factor candidate`
    : "Verified factor candidate";
}

const activationNotes = {
  zh: {
    dsr_performance_required: "仅供研究复核；缺少可用于模拟运行准入的收益序列。",
    dsr_failed: "仅供研究复核；统计稳健性未通过当前要求。",
    correlated_duplicate: "仅供研究复核；与正在运行的策略过于相似。",
    cost_unmeasured_blocked: "仅供研究复核；缺少交易成本评估，暂不能启用模拟运行。",
    cost_sensitivity_failed: "仅供研究复核；计入交易成本后不适合模拟运行。",
    correlation_unmeasured_blocked: "已有模拟仓缺少可比较的日期或收益原件，暂不能判断重复风险。",
    peer_sleeve_unavailable: "已有模拟仓的仓位记录缺失，需要核对原仓身份后才能新增资金。",
    peer_sleeve_lineage_mismatch: "已有模拟仓与候选身份不一致，需要核对原仓记录。",
    peer_book_status_mismatch: "已有模拟仓的状态记录不一致，暂不能新增资金。",
    peer_holdings_state_mismatch: "持仓明细与账户中的实际持仓不一致，需核对原记录后再新增资金。",
    peer_account_unavailable: "暂时无法完整核对已有仓的账户和持仓来源，不能把它当作空仓。",
    new_capital_quality_failed: "当前完整试验族、验证原件或质量要求未满足，暂不能新增模拟资金。",
    family_evidence_incomplete: "同一试验族还有缺失证据或样本不足，需要补齐原件后重新评价。",
    quality_evidence_unavailable: "当前验证原件无法完整核对，需按原身份补齐或重验；保留已有研究记录。",
    unfunded_tier: "当前评价等级只允许保留研究或观察，不具备新增模拟资金资格。",
    preflight_on_enable: "首次启用时将执行完整资格预检，通过后才会开始模拟运行。",
  },
  en: {
    dsr_performance_required: "Research review only; return history is missing for activation.",
    dsr_failed: "Research review only; statistical robustness did not pass.",
    correlated_duplicate: "Research review only; too similar to a strategy already running.",
    cost_unmeasured_blocked: "Research review only; trading costs could not be assessed.",
    cost_sensitivity_failed: "Research review only; not suitable for simulated running after trading costs.",
    correlation_unmeasured_blocked: "Existing paper exposure lacks comparable dates or original returns.",
    peer_sleeve_unavailable: "An existing paper sleeve is missing; verify its identity before new funding.",
    peer_sleeve_lineage_mismatch: "An existing sleeve and candidate have inconsistent identities.",
    peer_book_status_mismatch: "Existing sleeve status records conflict; new funding is blocked.",
    peer_holdings_state_mismatch: "Sleeve holdings disagree with the account; reconcile original records before new funding.",
    peer_account_unavailable: "Existing account and holding attribution cannot be verified; this is not evidence of an empty sleeve.",
    new_capital_quality_failed: "Current family, original evidence or minimum quality is insufficient for new paper capital.",
    family_evidence_incomplete: "The comparable trial family lacks evidence or sufficient samples; complete the originals before re-evaluation.",
    quality_evidence_unavailable: "Current originals cannot be fully verified. Complete or revalidate the same identity; existing research is retained.",
    unfunded_tier: "The current grade permits research or observation only, without new paper funding.",
    preflight_on_enable: "Enabling runs the full eligibility preflight first; simulated running starts only if it passes.",
  },
} as const;

// Eligibility projections carry this marker when the version may be enabled and the
// full qualification preflight runs at enable time. It is an advisory, not a denial.
export const ACTIVATION_PREFLIGHT_ON_ENABLE = "preflight_on_enable";

export function candidatePresentation(
  input: CandidatePresentationInput,
  locale: Locale,
): CandidatePresentation {
  const rawReason = input.activation_eligibility?.reason;
  const qualityReasons = rawReason?.startsWith("new_capital_quality_failed:")
    ? rawReason.slice("new_capital_quality_failed:".length).split(",") : [];
  const reason = qualityReasons.length
    ? ["quality_evidence_unavailable", "family_evidence_incomplete", "correlation_unmeasured_blocked", "unfunded_tier"]
      .find(value => qualityReasons.includes(value)) ?? "new_capital_quality_failed"
    : rawReason;
  const notes = activationNotes[locale];
  let activationNote: string | undefined;
  if (reason === ACTIVATION_PREFLIGHT_ON_ENABLE) {
    // Reported on an eligible projection: the enable action is allowed, the preflight runs then.
    activationNote = notes[ACTIVATION_PREFLIGHT_ON_ENABLE];
  } else if (input.activation_eligibility?.eligible === false) {
    activationNote =
      reason && reason in notes
        ? notes[reason as keyof typeof notes]
        : locale === "zh"
          ? "仅供研究复核；当前验证结果不允许启用模拟运行。"
          : "Research review only; current validation does not allow simulated running.";
  }
  if (locale === "zh") {
    const suppliedName = clean(input.display_name_zh);
    const suppliedSummary = clean(input.summary_zh);
    const legacy = input.candidate_id ? legacyChinesePresentation[input.candidate_id] : undefined;
    return {
      name:
        suppliedName ??
        legacy?.name ??
        (input.factor_id ? legacyFactorNamesZh[input.factor_id] : undefined) ??
        chineseFallbackName(input),
      summary: suppliedSummary ?? legacy?.summary ?? chineseFallbackSummary(input),
      activationNote,
    };
  }

  return {
    name: clean(input.display_name) ?? englishFallbackName(input),
    summary: clean(input.objective) ?? "Verified research candidate.",
    activationNote,
  };
}

export function factorDisplayName(
  factorId: string | null | undefined,
  fallback: string,
  locale: Locale,
): string {
  if (locale !== "zh") return fallback;
  return (factorId ? legacyFactorNamesZh[factorId] : undefined) ?? fallback;
}
