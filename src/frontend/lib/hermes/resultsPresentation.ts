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

export function resultWarningText(warning: HermesResultWarning): string {
  return [warning.source, warning.code, warning.kind, warning.resource_id]
    .filter((value): value is string => Boolean(value))
    .join(" · ");
}
