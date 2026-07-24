import type { Locale } from "@/lib/locale";
import type { HermesArtifactKind } from "@/lib/api";

export type ArtifactLocaleCopy = {
  title: string;
  hint: string;
  status: string;
  generated: string;
  portfolioRisk: string;
  prediction: string;
  marketForesight: string;
  weeklyReview: string;
  opportunityReview: string;
  automationStatus: string;
  grossExposure: string;
  topHolding: string;
  historicalRisk: string;
  confidence: string;
  horizon: string;
  candidates: string;
  candidatesAria: string;
  proposalOnly: string;
  direction: string;
  outcomeReturn: string;
  directionBrier: string;
  noScoredPredictions: string;
  period: string;
  safetyAlerts: string;
  uniqueSignals: string;
  reviewDrafts: string;
  reviewConfirmed: string;
  predictionsCreated: string;
  predictionsScored: string;
  predictionHits: string;
  opportunitiesObserved: string;
  missedOpportunities: string;
  coverageUnknown: string;
  limitations: string;
  totalOpportunities: string;
  acted: string;
  open: string;
  deferred: string;
  actionFailed: string;
  declined: string;
  notActionable: string;
  unknown: string;
  missNoDecision: string;
  missActWithoutAction: string;
  missDeferExpired: string;
  automationFresh: string;
  automationDegraded: string;
  automationJobsAria: string;
  expectedSchedule: string;
  freshnessBudget: string;
  lastAttempt: string;
  lastSuccess: string;
  freshUntil: string;
  lastRun: string;
  notification: string;
  neverRun: string;
  stale: string;
  failed: string;
  fresh: string;
  notRequired: string;
  delivered: string;
  queued: string;
  fallbackPersisted: string;
  deliveryUnknown: string;
  proposalSummary: string;
  timelineAria: string;
  sourceAria: string;
  portfolioRiskSource: string;
  predictionSource: string;
  marketForesightSource: string;
  weeklyReviewSource: string;
  opportunitySummarySource: string;
  automationStatusSource: string;
  emptyTitle: string;
  emptyDescription: string;
  degradedTitle: string;
  degradedDescription: string;
  degradedEmptyDescription: string;
  noUsableTitle: string;
  noUsableDescription: string;
  unavailableTitle: string;
  unavailableDescription: string;
  technicalDetails: string;
  keyEvidence: string;
  conclusion: string;
  automationHealthyLine: (healthy: number, total: number) => string;
  automationAttentionLine: (healthy: number, total: number) => string;
  automationUnavailableLine: string;
  exceptionsAria: string;
};

const en: ArtifactLocaleCopy = {
  title: "Artifacts",
  hint: "Latest read-only outputs from Hermes research employees.",
  status: "status",
  generated: "Generated",
  portfolioRisk: "Portfolio risk",
  prediction: "Prediction",
  marketForesight: "Market foresight",
  weeklyReview: "Weekly review",
  opportunityReview: "Opportunity review",
  automationStatus: "Automation status",
  grossExposure: "Gross exposure",
  topHolding: "Largest holding",
  historicalRisk: "Historical risk",
  confidence: "Confidence",
  horizon: "Horizon",
  candidates: "Candidates",
  candidatesAria: "Foresight prediction candidates",
  proposalOnly: "Proposal only · human confirmation required",
  direction: "Direction",
  outcomeReturn: "Outcome return",
  directionBrier: "Direction Brier",
  noScoredPredictions: "No scored predictions yet",
  period: "Period",
  safetyAlerts: "Safety alerts",
  uniqueSignals: "Unique signals",
  reviewDrafts: "Review drafts",
  reviewConfirmed: "Reviews confirmed",
  predictionsCreated: "Predictions created",
  predictionsScored: "Predictions scored",
  predictionHits: "Prediction hits",
  opportunitiesObserved: "Opportunities observed",
  missedOpportunities: "Missed opportunities",
  coverageUnknown: "Coverage unknown",
  limitations: "Limitations",
  totalOpportunities: "Total opportunities",
  acted: "Acted",
  open: "Open",
  deferred: "Deferred",
  actionFailed: "Action failed",
  declined: "Declined",
  notActionable: "Not actionable",
  unknown: "Unknown",
  missNoDecision: "No decision",
  missActWithoutAction: "Act without action",
  missDeferExpired: "Deferred then expired",
  automationFresh: "Fresh · schedules are current",
  automationDegraded: "Degraded · attention required",
  automationJobsAria: "Automation job freshness",
  expectedSchedule: "Expected schedule",
  freshnessBudget: "Freshness budget",
  lastAttempt: "Last attempt",
  lastSuccess: "Last success",
  freshUntil: "Fresh until",
  lastRun: "Last run",
  notification: "Notification",
  neverRun: "Never run",
  stale: "Stale",
  failed: "Failed",
  fresh: "Fresh",
  notRequired: "Not required",
  delivered: "Delivered",
  queued: "Queued",
  fallbackPersisted: "Fallback persisted",
  deliveryUnknown: "Delivery unknown",
  proposalSummary: "Read-only summary · trading disabled",
  timelineAria: "Research artifact timeline",
  sourceAria: "Artifact source status",
  portfolioRiskSource: "Portfolio risk source",
  predictionSource: "Prediction ledger",
  marketForesightSource: "Market foresight source",
  weeklyReviewSource: "Weekly review source",
  opportunitySummarySource: "Opportunity summary source",
  automationStatusSource: "Automation status source",
  emptyTitle: "No research artifacts yet",
  emptyDescription: "Hermes jobs can populate this read-only shelf after their first run.",
  degradedTitle: "Artifact shelf is degraded",
  degradedDescription: "Some sources are unavailable; healthy artifacts remain visible.",
  degradedEmptyDescription: "Artifact sources are unavailable and no usable output could be loaded.",
  noUsableTitle: "No usable artifacts are available",
  noUsableDescription: "Run Hermes jobs again after the artifact sources recover.",
  unavailableTitle: "Artifacts unavailable",
  unavailableDescription:
    "Hermes artifact sources could not be read. Existing platform pages remain read-only.",
  technicalDetails: "Technical details",
  keyEvidence: "Key evidence",
  conclusion: "Conclusion",
  automationHealthyLine: (healthy, total) => `Automation ${healthy}/${total} healthy`,
  automationAttentionLine: (healthy, total) => `Automation ${healthy}/${total} healthy`,
  automationUnavailableLine: "Automation source unavailable",
  exceptionsAria: "Automation exceptions",
};

const zh: ArtifactLocaleCopy = {
  title: "产物货架",
  hint: "Hermes 研究员工最新生成的只读产物。",
  status: "状态",
  generated: "生成时间",
  portfolioRisk: "组合风险",
  prediction: "预测",
  marketForesight: "市场推演",
  weeklyReview: "周报复盘",
  opportunityReview: "机会复盘",
  automationStatus: "自动化状态",
  grossExposure: "总敞口",
  topHolding: "最大持仓",
  historicalRisk: "历史风险",
  confidence: "置信度",
  horizon: "预测期限",
  candidates: "候选预测",
  candidatesAria: "市场推演候选预测",
  proposalOnly: "仅提案 · 待人工确认",
  direction: "方向",
  outcomeReturn: "结果收益",
  directionBrier: "方向 Brier 分数",
  noScoredPredictions: "暂无已评分预测",
  period: "统计区间",
  safetyAlerts: "安全告警",
  uniqueSignals: "去重信号",
  reviewDrafts: "复盘草稿",
  reviewConfirmed: "已确认复盘",
  predictionsCreated: "新建预测",
  predictionsScored: "已评分预测",
  predictionHits: "预测命中",
  opportunitiesObserved: "已观察机会",
  missedOpportunities: "错过机会",
  coverageUnknown: "覆盖状态未知",
  limitations: "局限说明",
  totalOpportunities: "机会总数",
  acted: "已行动",
  open: "待处理",
  deferred: "已延期",
  actionFailed: "行动失败",
  declined: "已拒绝",
  notActionable: "不可行动",
  unknown: "状态未知",
  missNoDecision: "未决策",
  missActWithoutAction: "决定行动但无行动记录",
  missDeferExpired: "延期后过期",
  automationFresh: "运行正常 · 调度均在时效内",
  automationDegraded: "已降级 · 需要检查",
  automationJobsAria: "自动化任务时效",
  expectedSchedule: "预期调度",
  freshnessBudget: "时效预算",
  lastAttempt: "最近尝试",
  lastSuccess: "最近成功",
  freshUntil: "保鲜截止",
  lastRun: "最近运行",
  notification: "通知状态",
  neverRun: "从未运行",
  stale: "已过期",
  failed: "失败",
  fresh: "正常",
  notRequired: "无需通知",
  delivered: "已送达",
  queued: "排队中",
  fallbackPersisted: "已写入本地兜底",
  deliveryUnknown: "送达状态未知",
  proposalSummary: "只读汇总 · 禁止交易",
  timelineAria: "研究产物时间线",
  sourceAria: "产物来源状态",
  portfolioRiskSource: "组合风险来源",
  predictionSource: "预测账本",
  marketForesightSource: "市场推演来源",
  weeklyReviewSource: "周报复盘来源",
  opportunitySummarySource: "机会复盘来源",
  automationStatusSource: "自动化状态来源",
  emptyTitle: "暂无研究产物",
  emptyDescription: "Hermes 任务首次运行后，会把只读产物放到这里。",
  degradedTitle: "产物货架已降级",
  degradedDescription: "部分来源不可用；仍保留展示可正常读取的产物。",
  degradedEmptyDescription: "产物来源不可用，当前未能加载任何可用产物。",
  noUsableTitle: "当前没有可用产物",
  noUsableDescription: "请在产物来源恢复后重新运行 Hermes 任务。",
  unavailableTitle: "产物不可用",
  unavailableDescription: "当前无法读取 Hermes 产物来源；平台其他页面仍保持只读。",
  technicalDetails: "技术细节",
  keyEvidence: "关键证据",
  conclusion: "结论",
  automationHealthyLine: (healthy, total) => `自动化 ${healthy}/${total} 正常`,
  automationAttentionLine: (healthy, total) => `自动化 ${healthy}/${total} 正常`,
  automationUnavailableLine: "自动化源不可用",
  exceptionsAria: "自动化异常",
};

const byLocale: Record<Locale, ArtifactLocaleCopy> = { en, zh };

export function artifactCopy(locale: Locale): ArtifactLocaleCopy {
  return byLocale[locale] ?? en;
}

export function sourceLabel(kind: HermesArtifactKind, locale: Locale) {
  const text = artifactCopy(locale);
  if (kind === "portfolio_risk") return text.portfolioRiskSource;
  if (kind === "prediction") return text.predictionSource;
  if (kind === "market_foresight") return text.marketForesightSource;
  if (kind === "weekly_review") return text.weeklyReviewSource;
  if (kind === "opportunity_summary") return text.opportunitySummarySource;
  if (kind === "automation_status") return text.automationStatusSource;
  return kind;
}

export function automationJobLabel(
  job: "daily_close" | "freshness" | "weekly" | "notification_drain" | string,
  locale: Locale,
) {
  const labels =
    locale === "zh"
      ? {
          daily_close: "每日收盘研究",
          freshness: "时效巡检",
          weekly: "每周复盘",
          notification_drain: "通知投递",
        }
      : {
          daily_close: "Daily-close research",
          freshness: "Freshness monitor",
          weekly: "Weekly review",
          notification_drain: "Notification delivery",
        };
  if (job in labels) return labels[job as keyof typeof labels];
  return job;
}

export function automationStatusLabel(
  status: "fresh" | "stale" | "failed" | "never_run" | string,
  locale: Locale,
) {
  const text = artifactCopy(locale);
  if (status === "fresh") return text.fresh;
  if (status === "stale") return text.stale;
  if (status === "failed") return text.failed;
  if (status === "never_run") return text.neverRun;
  return status;
}

export function notificationStatusLabel(
  status:
    | "delivered"
    | "queued"
    | "fallback_persisted"
    | "not_required"
    | "delivery_unknown"
    | string,
  locale: Locale,
) {
  const text = artifactCopy(locale);
  if (status === "delivered") return text.delivered;
  if (status === "queued") return text.queued;
  if (status === "fallback_persisted") return text.fallbackPersisted;
  if (status === "delivery_unknown") return text.deliveryUnknown;
  if (status === "not_required") return text.notRequired;
  return status;
}
