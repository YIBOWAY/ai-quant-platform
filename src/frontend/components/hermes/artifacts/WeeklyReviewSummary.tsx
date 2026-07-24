import { CalendarCheck } from "lucide-react";
import { Card, StatusPill } from "@/components/ui/primitives";
import type { HermesArtifact } from "@/lib/api";
import type { Locale } from "@/lib/locale";
import { artifactCopy } from "./copy";
import { Fact } from "./Fact";
import {
  formatDateTime,
  formatDecimal,
  humanizeReasonCode,
  qualityTone,
  safeDomId,
} from "./formatters";
import { TechnicalDetails } from "./TechnicalDetails";

export type WeeklyReviewSummaryProps = {
  artifact: Extract<HermesArtifact, { kind: "weekly_review" }>;
  locale: Locale;
};

export function WeeklyReviewSummary({ artifact, locale }: WeeklyReviewSummaryProps) {
  const text = artifactCopy(locale);
  const headingId = `artifact-${safeDomId(artifact.id)}`;
  const title = `${text.weeklyReview} · ${artifact.data.week_id}`;
  const conclusion = `${text.uniqueSignals} ${artifact.data.unique_signal_count} · ${text.missedOpportunities} ${artifact.data.opportunity_missed_count}`;

  return (
    <article aria-labelledby={headingId} data-hermes-artifact-kind="weekly_review">
      <Card className="bg-[var(--color-stream-surface)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <CalendarCheck aria-hidden="true" className="shrink-0 text-info" size={16} />
              <h3 className="font-body-sm font-semibold text-text-primary" id={headingId}>
                {title}
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

        <p className="mt-3 font-body-sm font-semibold text-warning">{text.proposalSummary}</p>
        <p className="mt-2 font-body-sm text-text-primary">{conclusion}</p>
        <dl className="mt-3 grid gap-3 sm:grid-cols-3">
          <Fact
            label={text.period}
            value={`${formatDateTime(artifact.data.period_start, locale)} – ${formatDateTime(artifact.data.period_end, locale)}`}
          />
          <Fact label={text.safetyAlerts} value={String(artifact.data.safety_alert_count)} />
          <Fact label={text.uniqueSignals} value={String(artifact.data.unique_signal_count)} />
          <Fact label={text.reviewDrafts} value={String(artifact.data.review_draft_count)} />
          <Fact
            label={text.reviewConfirmed}
            value={String(artifact.data.review_confirmed_count)}
          />
          <Fact
            label={text.predictionsCreated}
            value={String(artifact.data.prediction_created_count)}
          />
          <Fact
            label={text.predictionsScored}
            value={String(artifact.data.prediction_scored_count)}
          />
          <Fact
            label={text.predictionHits}
            value={String(artifact.data.prediction_hit_count)}
          />
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
          <div className="mt-3">
            <p className="font-label-caps text-text-secondary">{text.limitations}</p>
            <ul className="mt-1 space-y-1 font-body-sm text-text-secondary">
              {artifact.data.limitations.map((limitation) => (
                <li key={limitation}>{humanizeReasonCode(limitation, locale)}</li>
              ))}
            </ul>
          </div>
        ) : null}

        <TechnicalDetails locale={locale}>
          <dl className="grid gap-2 sm:grid-cols-2">
            <Fact label="week_id" value={artifact.data.week_id} />
            <Fact label="id" value={artifact.id} />
            <Fact label="occurred_at" value={artifact.occurred_at} />
          </dl>
        </TechnicalDetails>
      </Card>
    </article>
  );
}
