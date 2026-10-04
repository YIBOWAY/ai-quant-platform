import type { Tone } from "@/components/hermes/artifacts/formatters";
import type { Locale } from "@/lib/locale";

import type {
  HermesResultAggregateReadStatus,
  HermesResultAuthority,
  HermesResultFreshness,
  HermesResultItemReadStatus,
  HermesResultKind,
  HermesResultWarning,
} from "./resultsTypes";

type ResultPresentationItem = {
  kind: HermesResultKind;
  resource_id: string;
  display_title: string;
  summary?: string | null;
  display_title_zh?: string | null;
  summary_zh?: string | null;
  status: string;
  freshness: HermesResultFreshness;
  occurred_at: string;
};

const legacyResultTitlesZh: Record<string, string> = {
  "factor-reproduce_arxiv_1904_04912_classical_mul-6fc8e027a7":
    "经典多周期 MACD 时间序列动量复现",
  "factor-research_proxy_of_arxiv_2511_12490_drift-d719757028":
    "漂移状态反转因子研究代理",
  "factor-implement_and_validate_an_operational_us-f0e6ea4fa1":
    "短期反转与长期动量 ETF 代理",
};

function containsChinese(value: string | null | undefined): boolean {
  return typeof value === "string" && /[\u3400-\u9fff]/u.test(value);
}

function localizedDate(value: string): string {
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) return "";
  return parsed.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: "Asia/Shanghai",
  });
}

const labels = {
  en: {
    kinds: {
      backtest: "Backtest",
      factor: "Factor run",
      paper: "Paper run",
      replication: "Replication",
      experiment: "Experiment",
      factor_candidate: "Factor candidate",
      portfolio_risk: "Portfolio risk",
      prediction: "Prediction",
      market_foresight: "Market foresight",
      weekly_review: "Weekly review",
      opportunity_summary: "Opportunity summary",
      automation_status: "Automation status",
    },
    sources: {
      platform_runs: "Platform runs",
      platform_experiments: "Platform experiments",
      platform_candidates: "Platform candidates",
      hqa_artifact_feed: "HQA artifact feed",
      platform_run_links: "Exact run links",
    },
    authorities: {
      platform_run_artifact: "Platform run artifact",
      platform_experiment_artifact: "Platform experiment artifact",
      platform_candidate_repository: "Platform candidate repository",
      hqa_artifact_manifest: "HQA artifact manifest",
    },
  },
  zh: {
    kinds: {
      backtest: "回测",
      factor: "因子运行",
      paper: "模拟运行",
      replication: "策略复现",
      experiment: "实验",
      factor_candidate: "因子候选",
      portfolio_risk: "组合风险",
      prediction: "预测",
      market_foresight: "市场前瞻",
      weekly_review: "每周复盘",
      opportunity_summary: "机会摘要",
      automation_status: "自动化状态",
    },
    sources: {
      platform_runs: "平台运行产物",
      platform_experiments: "平台实验产物",
      platform_candidates: "平台候选仓库",
      hqa_artifact_feed: "HQA 产物源",
      platform_run_links: "精确运行关联",
    },
    authorities: {
      platform_run_artifact: "平台运行权威产物",
      platform_experiment_artifact: "平台实验权威产物",
      platform_candidate_repository: "平台候选权威仓库",
      hqa_artifact_manifest: "HQA 权威清单",
    },
  },
} as const;

export function resultKindLabel(kind: HermesResultKind, locale: Locale): string {
  return labels[locale].kinds[kind];
}

export function resultSourceLabel(source: string, locale: Locale): string {
  const known = labels[locale].sources as Record<string, string>;
  return known[source] ?? source;
}

const statusLabels: Record<Locale, Record<string, string>> = {
  en: {
    available: "Available",
    degraded: "Degraded",
    empty: "Empty",
    unavailable: "Unavailable",
    pending: "Pending",
    approved: "Approved",
    rejected: "Rejected",
    completed: "Completed",
    failed: "Failed",
    fresh: "Fresh",
    stale: "Stale",
    unknown: "Unknown",
    corrupt: "Corrupt",
    missing: "Missing",
  },
  zh: {
    available: "可用",
    degraded: "已降级",
    empty: "空",
    unavailable: "不可用",
    pending: "待定",
    approved: "已批准",
    rejected: "已拒绝",
    completed: "已完成",
    failed: "失败",
    fresh: "当前有效",
    stale: "已过期",
    unknown: "状态待确认",
    corrupt: "数据损坏",
    missing: "记录缺失",
  },
};

/** Localized label for an item status value; unknown values pass through. */
export function resultStatusLabel(status: string, locale: Locale): string {
  return statusLabels[locale][status] ?? (locale === "zh" ? "状态待确认" : status);
}

export function resultReadStatusLabel(
  status: HermesResultItemReadStatus | HermesResultAggregateReadStatus,
  locale: Locale,
): string {
  const labels: Record<Locale, Record<string, string>> = {
    en: {
      available: "Readable",
      degraded: "Degraded",
      empty: "Empty",
      missing: "Missing",
      corrupt: "Corrupt",
      unavailable: "Unavailable",
    },
    zh: {
      available: "可读取",
      degraded: "部分可用",
      empty: "暂无记录",
      missing: "记录缺失",
      corrupt: "数据损坏",
      unavailable: "不可读取",
    },
  };
  return labels[locale][status] ?? (locale === "zh" ? "读取状态待确认" : status);
}

export function resultFreshnessLabel(
  freshness: HermesResultFreshness,
  locale: Locale,
): string {
  const labels: Record<Locale, Record<HermesResultFreshness, string>> = {
    en: {
      fresh: "Current",
      stale: "Historical snapshot · expired",
      not_applicable: "Not time-sensitive",
      unknown: "Freshness unknown",
    },
    zh: {
      fresh: "当前有效",
      stale: "历史快照 · 已过期",
      not_applicable: "不按时效判断",
      unknown: "时效待确认",
    },
  };
  return labels[locale][freshness];
}

export function resultDisplayTitle(item: ResultPresentationItem, locale: Locale): string {
  if (locale === "en") return item.display_title;
  if (item.display_title_zh?.trim()) return item.display_title_zh.trim();
  const exact = legacyResultTitlesZh[item.resource_id];
  if (exact) return exact;
  if (containsChinese(item.display_title)) return item.display_title;
  if (item.kind === "automation_status") {
    return item.freshness === "stale" ? "自动化历史快照" : "自动化状态";
  }
  if (item.kind === "weekly_review") {
    return `每周复盘${localizedDate(item.occurred_at) ? ` · ${localizedDate(item.occurred_at)}` : ""}`;
  }
  if (item.kind === "opportunity_summary") {
    return `机会复盘${localizedDate(item.occurred_at) ? ` · ${localizedDate(item.occurred_at)}` : ""}`;
  }
  if (item.kind === "portfolio_risk") return "组合风险";
  if (item.kind === "backtest" && item.display_title.startsWith("cross_sectional_top_n")) {
    const symbols = item.display_title.split("·")[1]?.trim().replaceAll(", ", "、");
    return `横截面 Top-N${symbols ? ` · ${symbols}` : ""}`;
  }
  return resultKindLabel(item.kind, locale);
}

export function resultSummaryText(item: ResultPresentationItem, locale: Locale): string | null {
  if (locale === "en") return item.summary ?? null;
  if (item.summary_zh?.trim()) return item.summary_zh.trim();
  if (containsChinese(item.summary)) return item.summary ?? null;
  if (item.kind === "automation_status" && item.freshness === "stale") {
    return "该记录已经过期，不能代表当前自动化运行状态。";
  }
  const summaries: Record<HermesResultKind, string> = {
    backtest: "已保存的回测结果。",
    factor: "已保存的因子运行结果。",
    paper: "已保存的模拟运行结果。",
    replication: "已保存的策略复现结果。",
    experiment: "已保存的研究实验结果。",
    factor_candidate: "已保存的因子候选记录。可展开技术信息核对原始身份。",
    portfolio_risk: "账户持仓与风险概览。",
    prediction: "已保存的市场预测记录。",
    market_foresight: "已保存的市场观察记录。",
    weekly_review: "该记录来自历史每周复盘。",
    opportunity_summary: "该记录来自历史机会复盘。",
    automation_status: "自动化运行状态摘要。",
  };
  return summaries[item.kind];
}

export function resultAuthorityLabel(
  authority: HermesResultAuthority,
  locale: Locale,
): string {
  return labels[locale].authorities[authority];
}

export function resultReadStatusTone(
  status: HermesResultItemReadStatus | HermesResultAggregateReadStatus,
): Tone {
  if (status === "available") return "success";
  if (status === "degraded") return "warning";
  if (status === "empty") return "neutral";
  return "danger";
}

export function resultFreshnessTone(freshness: HermesResultFreshness): Tone {
  if (freshness === "fresh") return "success";
  if (freshness === "stale") return "warning";
  return "neutral";
}

export function resultWarningText(warning: HermesResultWarning, locale: Locale = "en"): string {
  if (locale === "zh") {
    const known: Record<string, string> = {
      result_corrupt: "有一条结果记录已损坏。",
      result_missing: "有一条结果记录缺失。",
      source_unavailable: "有一个结果来源暂不可用。",
      source_scan_limit_exceeded: "结果来源未能完整读取，当前列表可能不完整。",
      source_scan_incomplete: "结果来源未能完整读取，当前列表可能不完整。",
      api_unavailable: "结果来源暂不可用。",
      candidate_migration_required: "候选记录需要升级后才能完整读取。",
    };
    return known[warning.code] ?? "结果来源出现异常，请稍后重试。";
  }
  return [warning.source, warning.code, warning.kind, warning.resource_id]
    .filter((value): value is string => Boolean(value))
    .join(" · ");
}
