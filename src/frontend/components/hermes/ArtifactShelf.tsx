import {
  Activity,
  BrainCircuit,
  CalendarCheck,
  ListChecks,
  Telescope,
  Workflow,
} from "lucide-react";

import { EmptyState } from "@/components/EmptyState";
import { Card, SectionTitle, StatusPill } from "@/components/ui/primitives";
import type {
  HermesArtifact,
  HermesArtifactKind,
  HermesArtifactQuality,
  HermesArtifactShelfEnvelope,
} from "@/lib/api";

type Locale = "en" | "zh";
type Tone = "neutral" | "success" | "warning" | "danger" | "info";

const copy = {
  en: {
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
    unavailableDescription: "Hermes artifact sources could not be read. Existing platform pages remain read-only.",
  },
  zh: {
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
  },
} as const;

export type ArtifactShelfProps = {
  envelope: HermesArtifactShelfEnvelope;
  locale: Locale;
};

export function ArtifactShelf({ envelope, locale }: ArtifactShelfProps) {
  const text = copy[locale];

  return (
    <section aria-labelledby="hermes-artifact-shelf-title" className="space-y-3">
      <div id="hermes-artifact-shelf-title">
        <SectionTitle title={text.title} hint={text.hint} />
      </div>
      {envelope.sources.length ? (
        <ul aria-label={text.sourceAria} className="flex flex-wrap gap-2">
          {envelope.sources.map((source) => (
            <li key={source.kind}>
              <StatusPill
                label={sourceLabel(source.kind, locale)}
                value={source.status}
                tone={sourceStatusTone(source.status)}
              />
            </li>
          ))}
        </ul>
      ) : null}
      {envelope.read_status === "degraded" ? (
        <div role="status">
          <Card tone="warning">
            <p className="font-body-sm font-semibold text-warning">{text.degradedTitle}</p>
            <p className="mt-1 font-body-sm text-text-secondary">
              {envelope.items.length
                ? text.degradedDescription
                : text.degradedEmptyDescription}
            </p>
            {envelope.warnings.length ? (
              <ul className="mt-2 space-y-1 font-data-mono text-xs text-text-secondary">
                {envelope.warnings.map((warning) => (
                  <li key={`${warning.source}:${warning.code}`}>
                    {warning.source} · {warning.code}
                  </li>
                ))}
              </ul>
            ) : null}
          </Card>
        </div>
      ) : null}
      {envelope.read_status === "unavailable" ? (
        <div role="alert">
          <Card tone="danger">
            <p className="font-body-sm font-semibold text-danger">{text.unavailableTitle}</p>
            <p className="mt-1 font-body-sm text-text-secondary">{text.unavailableDescription}</p>
            {envelope.warnings.length ? (
              <ul className="mt-2 space-y-1 font-data-mono text-xs text-text-secondary">
                {envelope.warnings.map((warning) => (
                  <li key={`${warning.source}:${warning.code}`}>
                    {warning.source} · {warning.code}
                  </li>
                ))}
              </ul>
            ) : null}
          </Card>
        </div>
      ) : envelope.read_status === "empty" ? (
        <div role="status">
          <EmptyState title={text.emptyTitle} description={text.emptyDescription} />
        </div>
      ) : envelope.items.length === 0 ? (
        <div role="status">
          <EmptyState title={text.noUsableTitle} description={text.noUsableDescription} />
        </div>
      ) : (
        <ul aria-label={text.timelineAria} className="space-y-3">
          {envelope.items.map((artifact) => (
            <li key={artifact.id}>
              <ArtifactCard artifact={artifact} locale={locale} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ArtifactCard({ artifact, locale }: { artifact: HermesArtifact; locale: Locale }) {
  const text = copy[locale];
  const headingId = `artifact-${safeDomId(artifact.id)}`;

  return (
    <article aria-labelledby={headingId}>
      <Card className="bg-[var(--color-stream-surface)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <ArtifactIcon artifact={artifact} />
              <h3 className="font-body-sm font-semibold text-text-primary" id={headingId}>
                {artifactTitle(artifact, locale)}
              </h3>
            </div>
            <p className="mt-1 font-body-sm text-text-secondary">
              {text.generated}{" "}
              <time dateTime={artifact.occurred_at}>
                {formatDateTime(artifact.occurred_at, locale)}
              </time>
            </p>
          </div>
          <StatusPill
            label={text.status}
            value={artifact.status || artifact.quality}
            tone={qualityTone(artifact.quality)}
          />
        </div>
        <div className="mt-4">
          <ArtifactBody artifact={artifact} locale={locale} />
        </div>
      </Card>
    </article>
  );
}

function ArtifactIcon({ artifact }: { artifact: HermesArtifact }) {
  if (artifact.kind === "portfolio_risk") {
    return <Activity aria-hidden="true" className="shrink-0 text-info" size={16} />;
  }
  if (artifact.kind === "prediction") {
    return <BrainCircuit aria-hidden="true" className="shrink-0 text-[var(--color-hermes)]" size={16} />;
  }
  if (artifact.kind === "market_foresight") {
    return <Telescope aria-hidden="true" className="shrink-0 text-warning" size={16} />;
  }
  if (artifact.kind === "weekly_review") {
    return <CalendarCheck aria-hidden="true" className="shrink-0 text-info" size={16} />;
  }
  if (artifact.kind === "opportunity_summary") {
    return <ListChecks aria-hidden="true" className="shrink-0 text-warning" size={16} />;
  }
  if (artifact.kind === "automation_status") {
    return <Workflow aria-hidden="true" className="shrink-0 text-[var(--color-hermes)]" size={16} />;
  }
  return assertNever(artifact);
}

function ArtifactBody({ artifact, locale }: { artifact: HermesArtifact; locale: Locale }) {
  const text = copy[locale];
  if (artifact.kind === "portfolio_risk") {
    return (
      <dl className="grid gap-3 sm:grid-cols-3">
        <Fact
          label={text.grossExposure}
          value={formatMoney(artifact.data.gross_value, artifact.data.currency, locale)}
        />
        <Fact label={text.topHolding} value={artifact.data.largest_symbol ?? "--"} />
        <Fact label={text.historicalRisk} value={artifact.data.historical_status ?? "--"} />
      </dl>
    );
  }
  if (artifact.kind === "prediction") {
    return (
      <div className="space-y-3">
        <dl className="grid gap-3 sm:grid-cols-4">
          <Fact label={text.status} value={artifact.data.state ?? artifact.status} />
          <Fact label={text.direction} value={artifact.data.direction ?? "--"} />
          <Fact label={text.confidence} value={formatPercent(artifact.data.confidence, locale)} />
          <Fact label={text.horizon} value={artifact.data.horizon_date ?? "--"} />
        </dl>
        {artifact.data.state === "scored" || artifact.status === "scored" ? (
          <dl className="grid gap-3 sm:grid-cols-2">
            <Fact
              label={text.outcomeReturn}
              value={formatPercent(artifact.data.outcome_return, locale)}
            />
            <Fact
              label={text.directionBrier}
              value={formatDecimal(artifact.data.direction_brier, 3)}
            />
          </dl>
        ) : null}
        {artifact.data.rationale ? (
          <p className="font-body-sm text-text-secondary">{artifact.data.rationale}</p>
        ) : null}
      </div>
    );
  }
  if (artifact.kind === "market_foresight") return (
    <div className="space-y-3">
      <p className="font-body-sm text-text-secondary">{artifact.data.summary ?? "--"}</p>
      <p className="font-body-sm font-semibold text-warning">{text.proposalOnly}</p>
      <dl>
        <Fact
          label={text.candidates}
          value={String(artifact.data.candidate_count ?? artifact.data.candidates?.length ?? 0)}
        />
      </dl>
      {artifact.data.candidates?.length ? (
        <ul aria-label={text.candidatesAria} className="space-y-2">
          {artifact.data.candidates.map((candidate, index) => (
            <li
              className="rounded-lg border border-border-subtle bg-bg-base p-3"
              key={`${candidate.symbol ?? "candidate"}-${candidate.horizon_date ?? index}`}
            >
              <p className="font-data-mono text-sm font-semibold text-text-primary">
                {candidate.symbol ?? "--"} · {candidate.direction ?? "--"}
              </p>
              <dl className="mt-2 grid gap-2 sm:grid-cols-3">
                <Fact label={text.direction} value={candidate.direction ?? "--"} />
                <Fact
                  label={text.confidence}
                  value={formatPercent(candidate.confidence, locale)}
                />
                <Fact label={text.horizon} value={candidate.horizon_date ?? "--"} />
              </dl>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
  if (artifact.kind === "weekly_review") {
    return (
      <div className="space-y-3">
        <p className="font-body-sm font-semibold text-warning">{text.proposalSummary}</p>
        <dl className="grid gap-3 sm:grid-cols-3">
          <Fact
            label={text.period}
            value={`${formatDateTime(artifact.data.period_start, locale)} – ${formatDateTime(artifact.data.period_end, locale)}`}
          />
          <Fact label={text.safetyAlerts} value={String(artifact.data.safety_alert_count)} />
          <Fact label={text.uniqueSignals} value={String(artifact.data.unique_signal_count)} />
          <Fact label={text.reviewDrafts} value={String(artifact.data.review_draft_count)} />
          <Fact label={text.reviewConfirmed} value={String(artifact.data.review_confirmed_count)} />
          <Fact label={text.predictionsCreated} value={String(artifact.data.prediction_created_count)} />
          <Fact label={text.predictionsScored} value={String(artifact.data.prediction_scored_count)} />
          <Fact label={text.predictionHits} value={String(artifact.data.prediction_hit_count)} />
          <Fact
            label={text.directionBrier}
            value={
              artifact.data.mean_direction_brier === null
                ? text.noScoredPredictions
                : formatDecimal(artifact.data.mean_direction_brier, 3)
            }
          />
          <Fact
            label={text.opportunitiesObserved}
            value={String(artifact.data.opportunity_observed_count)}
          />
          <Fact
            label={text.missedOpportunities}
            value={String(artifact.data.opportunity_missed_count)}
          />
          <Fact
            label={text.coverageUnknown}
            value={String(artifact.data.opportunity_coverage_unknown_count)}
          />
        </dl>
        {artifact.data.limitations.length ? (
          <div>
            <p className="font-label-caps text-text-secondary">{text.limitations}</p>
            <ul className="mt-1 space-y-1 font-body-sm text-text-secondary">
              {artifact.data.limitations.map((limitation) => (
                <li key={limitation}>{humanizeReasonCode(limitation, locale)}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    );
  }
  if (artifact.kind === "opportunity_summary") {
    const resolution = artifact.data.resolution_counts;
    const missReasons = artifact.data.miss_reason_counts;
    return (
      <div className="space-y-3">
        <p className="font-body-sm font-semibold text-warning">{text.proposalSummary}</p>
        <dl className="grid gap-3 sm:grid-cols-3">
          <Fact
            label={text.period}
            value={`${formatDateTime(artifact.data.window_start, locale)} – ${formatDateTime(artifact.data.window_end, locale)}`}
          />
          <Fact label={text.totalOpportunities} value={String(artifact.data.total_count)} />
          <Fact label={text.acted} value={String(resolution.acted)} />
          <Fact label={text.open} value={String(resolution.open)} />
          <Fact label={text.deferred} value={String(resolution.deferred)} />
          <Fact label={text.actionFailed} value={String(resolution.action_failed)} />
          <Fact label={text.declined} value={String(resolution.declined)} />
          <Fact label={text.missedOpportunities} value={String(resolution.missed)} />
          <Fact
            label={text.coverageUnknown}
            value={String(resolution.expired_coverage_unknown)}
          />
          <Fact label={text.notActionable} value={String(resolution.not_actionable)} />
          <Fact label={text.unknown} value={String(resolution.unknown)} />
          <Fact label={text.missNoDecision} value={String(missReasons.no_decision)} />
          <Fact
            label={text.missActWithoutAction}
            value={String(missReasons.act_without_action)}
          />
          <Fact label={text.missDeferExpired} value={String(missReasons.defer_expired)} />
        </dl>
      </div>
    );
  }
  if (artifact.kind === "automation_status") {
    return (
      <div className="space-y-3">
        <p
          className={
            artifact.data.overall_status === "fresh"
              ? "font-body-sm font-semibold text-accent-success"
              : "font-body-sm font-semibold text-warning"
          }
        >
          {artifact.data.overall_status === "fresh"
            ? text.automationFresh
            : text.automationDegraded}
        </p>
        <ul aria-label={text.automationJobsAria} className="space-y-2">
          {artifact.data.jobs.map((job) => (
            <li className="rounded-lg border border-border-subtle bg-bg-base p-3" key={job.job_id}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-data-mono text-sm font-semibold text-text-primary">
                  {automationJobLabel(job.job_id, locale)}
                </p>
                <StatusPill
                  label={text.status}
                  value={automationStatusLabel(job.status, locale)}
                  tone={automationStatusTone(job.status)}
                />
              </div>
              <dl className="mt-2 grid gap-2 sm:grid-cols-3">
                <Fact label={text.expectedSchedule} value={`${job.expected_schedule} · ${job.timezone}`} />
                <Fact
                  label={text.freshnessBudget}
                  value={formatDuration(job.freshness_budget_seconds, locale)}
                />
                <Fact
                  label={text.lastAttempt}
                  value={job.last_attempt_at ? formatDateTime(job.last_attempt_at, locale) : text.neverRun}
                />
                <Fact
                  label={text.lastSuccess}
                  value={job.last_success_at ? formatDateTime(job.last_success_at, locale) : text.neverRun}
                />
                <Fact
                  label={text.freshUntil}
                  value={job.fresh_until ? formatDateTime(job.fresh_until, locale) : text.neverRun}
                />
                <Fact label={text.lastRun} value={job.last_run_id ?? text.neverRun} />
                <Fact
                  label={text.notification}
                  value={notificationStatusLabel(job.notification_status, locale)}
                />
              </dl>
              {job.reason_code ? (
                <p className="mt-2 font-data-mono text-xs text-warning">
                  {humanizeReasonCode(job.reason_code, locale)}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      </div>
    );
  }
  return assertNever(artifact);
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-border-subtle bg-bg-base p-3">
      <dt className="font-label-caps text-text-secondary">{label}</dt>
      <dd className="mt-1 break-words font-data-mono text-sm text-text-primary">{value}</dd>
    </div>
  );
}

function artifactTitle(artifact: HermesArtifact, locale: Locale) {
  const text = copy[locale];
  if (artifact.kind === "portfolio_risk") return text.portfolioRisk;
  if (artifact.kind === "prediction") {
    return `${text.prediction} · ${artifact.data.symbol ?? artifact.data.prediction_id ?? "--"}`;
  }
  if (artifact.kind === "market_foresight") return text.marketForesight;
  if (artifact.kind === "weekly_review") {
    return `${text.weeklyReview} · ${artifact.data.week_id}`;
  }
  if (artifact.kind === "opportunity_summary") return text.opportunityReview;
  if (artifact.kind === "automation_status") return text.automationStatus;
  return assertNever(artifact);
}

function qualityTone(quality: HermesArtifactQuality): Tone {
  if (quality === "available") return "success";
  if (quality === "degraded") return "warning";
  if (quality === "unavailable") return "danger";
  return "neutral";
}

function sourceStatusTone(status: string): Tone {
  if (status === "available") return "success";
  if (status === "degraded") return "warning";
  if (status === "unavailable") return "danger";
  return "neutral";
}

function sourceLabel(kind: HermesArtifactKind, locale: Locale) {
  const text = copy[locale];
  if (kind === "portfolio_risk") return text.portfolioRiskSource;
  if (kind === "prediction") return text.predictionSource;
  if (kind === "market_foresight") return text.marketForesightSource;
  if (kind === "weekly_review") return text.weeklyReviewSource;
  if (kind === "opportunity_summary") return text.opportunitySummarySource;
  if (kind === "automation_status") return text.automationStatusSource;
  return assertNever(kind);
}

function automationJobLabel(
  job: "daily_close" | "freshness" | "weekly" | "notification_drain",
  locale: Locale,
) {
  const labels = locale === "zh"
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
  return labels[job];
}

function automationStatusLabel(
  status: "fresh" | "stale" | "failed" | "never_run",
  locale: Locale,
) {
  const text = copy[locale];
  if (status === "fresh") return text.fresh;
  if (status === "stale") return text.stale;
  if (status === "failed") return text.failed;
  return text.neverRun;
}

function automationStatusTone(
  status: "fresh" | "stale" | "failed" | "never_run",
): Tone {
  if (status === "fresh") return "success";
  if (status === "failed") return "danger";
  return "warning";
}

function notificationStatusLabel(
  status: "delivered" | "queued" | "fallback_persisted" | "not_required" | "delivery_unknown",
  locale: Locale,
) {
  const text = copy[locale];
  if (status === "delivered") return text.delivered;
  if (status === "queued") return text.queued;
  if (status === "fallback_persisted") return text.fallbackPersisted;
  if (status === "delivery_unknown") return text.deliveryUnknown;
  return text.notRequired;
}

function humanizeReasonCode(code: string, locale: Locale) {
  const labels = locale === "zh"
    ? {
        never_run: "从未运行",
        freshness_budget_exceeded: "超过时效窗口",
        last_attempt_degraded: "最近一次运行已降级",
        no_successful_run: "尚无成功运行",
        read_only_research_summary: "只读研究汇总",
      }
    : {
        never_run: "Never run",
        freshness_budget_exceeded: "Freshness window exceeded",
        last_attempt_degraded: "Latest attempt was degraded",
        no_successful_run: "No successful run yet",
        read_only_research_summary: "Read-only research summary",
      };
  if (code in labels) return labels[code as keyof typeof labels];
  return code.replaceAll("_", " ");
}

function formatDuration(seconds: number, locale: Locale) {
  const units = locale === "zh"
    ? { day: "天", hour: "小时", minute: "分钟", second: "秒" }
    : { day: "days", hour: "hours", minute: "minutes", second: "seconds" };
  if (seconds % 86_400 === 0) return `${seconds / 86_400} ${units.day}`;
  if (seconds % 3_600 === 0) return `${seconds / 3_600} ${units.hour}`;
  if (seconds % 60 === 0) return `${seconds / 60} ${units.minute}`;
  return `${seconds} ${units.second}`;
}

function formatDateTime(value: string, locale: Locale) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Shanghai",
  }).format(parsed);
}

function formatMoney(value: number | null | undefined, currency: string | null | undefined, locale: Locale) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  try {
    return new Intl.NumberFormat(locale === "zh" ? "zh-CN" : "en-US", {
      style: "currency",
      currency: currency || "USD",
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${currency || "USD"} ${value.toFixed(2)}`;
  }
}

function formatPercent(value: number | null | undefined, locale: Locale) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  return new Intl.NumberFormat(locale === "zh" ? "zh-CN" : "en-US", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

function formatDecimal(value: number | null | undefined, digits: number) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  return value.toFixed(digits);
}

function safeDomId(value: string) {
  return value.replace(/[^a-zA-Z0-9_-]/g, "-");
}

function assertNever(value: never): never {
  throw new Error(`Unsupported Hermes artifact variant: ${JSON.stringify(value)}`);
}
