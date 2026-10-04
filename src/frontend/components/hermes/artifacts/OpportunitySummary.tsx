import { ListChecks } from "lucide-react";
import { Card, StatusPill } from "@/components/ui/primitives";
import type { HermesArtifact } from "@/lib/api";
import type { Locale } from "@/lib/locale";
import { artifactCopy } from "./copy";
import { Fact } from "./Fact";
import { artifactStatusLabel, formatDateTime, qualityTone, safeDomId } from "./formatters";
import { TechnicalDetails } from "./TechnicalDetails";

export type OpportunitySummaryProps = {
  artifact: Extract<HermesArtifact, { kind: "opportunity_summary" }>;
  locale: Locale;
};

export function OpportunitySummary({ artifact, locale }: OpportunitySummaryProps) {
  const text = artifactCopy(locale);
  const headingId = `artifact-${safeDomId(artifact.id)}`;
  const resolution = artifact.data.resolution_counts;
  const missReasons = artifact.data.miss_reason_counts;
  const conclusion = `${text.totalOpportunities}: ${artifact.data.total_count}`;
  const actionable = [
    resolution.acted,
    resolution.open,
    resolution.deferred,
    resolution.action_failed,
    resolution.declined,
    resolution.missed,
    resolution.expired_coverage_unknown,
    resolution.unknown,
  ].reduce((sum, value) => sum + value, 0);
  // A window where nothing was actionable is noise: keep one honest muted
  // line on the duty front page instead of a full headline card.
  if (artifact.quality === "degraded" && actionable === 0) {
    return (
      <article
        aria-labelledby={headingId}
        data-hermes-artifact-kind="opportunity_summary"
        data-collapsed="no_actionable_signal"
        className="rounded-lg border border-border-subtle bg-bg-surface px-4 py-2"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-body-sm text-text-secondary">
            {text.opportunityNoise(artifact.data.total_count)}
          </p>
          <StatusPill
            label={text.status}
            value={artifactStatusLabel(artifact.status || artifact.quality, locale)}
            tone={qualityTone(artifact.quality)}
          />
        </div>
      </article>
    );
  }

  return (
    <article aria-labelledby={headingId} data-hermes-artifact-kind="opportunity_summary">
      <Card className="bg-[var(--color-stream-surface)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <ListChecks aria-hidden="true" className="shrink-0 text-warning" size={16} />
              <h3 className="font-body-sm font-semibold text-text-primary" id={headingId}>
                {text.opportunityReview}
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
            value={artifactStatusLabel(artifact.status || artifact.quality, locale)}
            tone={qualityTone(artifact.quality)}
          />
        </div>

        <p className="mt-3 font-body-sm font-semibold text-warning">{text.proposalSummary}</p>
        <p className="mt-2 font-body-sm text-text-primary">{conclusion}</p>
        <dl className="mt-3 grid gap-3 sm:grid-cols-3">
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

        <TechnicalDetails locale={locale}>
          <dl className="grid gap-2 sm:grid-cols-2">
            <Fact label="id" value={artifact.id} />
            <Fact label="occurred_at" value={artifact.occurred_at} />
          </dl>
        </TechnicalDetails>
      </Card>
    </article>
  );
}
