import type { HermesArtifact, HermesAutomationStatusArtifactData } from "@/lib/api";
import type { Locale } from "@/lib/locale";
import type { HermesAutomationSummary } from "@/lib/hermes/types";
import { AutomationDetails } from "./AutomationDetails";
import { artifactCopy } from "./copy";
import { assertNever, formatDateTime, qualityTone, safeDomId } from "./formatters";
import { ForesightSummary } from "./ForesightSummary";
import { OpportunitySummary } from "./OpportunitySummary";
import { PortfolioRiskSummary } from "./PortfolioRiskSummary";
import { PredictionSummary } from "./PredictionSummary";
import { WeeklyReviewSummary } from "./WeeklyReviewSummary";
import { Card, StatusPill } from "@/components/ui/primitives";
import { Workflow } from "lucide-react";

const DEGRADED_NOTIFICATION = new Set(["fallback_persisted", "delivery_unknown"]);

function jobIsException(
  job: HermesAutomationStatusArtifactData["jobs"][number],
): boolean {
  if (job.status === "failed" || job.status === "stale" || job.status === "never_run") {
    return true;
  }
  return DEGRADED_NOTIFICATION.has(job.notification_status);
}

/**
 * Focused renderer dispatcher used by ArtifactShelf facade and RecentResults.
 */
export function FocusedArtifactCard({
  artifact,
  locale,
}: {
  artifact: HermesArtifact;
  locale: Locale;
}) {
  if (artifact.kind === "portfolio_risk") {
    return <PortfolioRiskSummary artifact={artifact} locale={locale} />;
  }
  if (artifact.kind === "prediction") {
    return <PredictionSummary artifact={artifact} locale={locale} />;
  }
  if (artifact.kind === "market_foresight") {
    return <ForesightSummary artifact={artifact} locale={locale} />;
  }
  if (artifact.kind === "weekly_review") {
    return <WeeklyReviewSummary artifact={artifact} locale={locale} />;
  }
  if (artifact.kind === "opportunity_summary") {
    return <OpportunitySummary artifact={artifact} locale={locale} />;
  }
  if (artifact.kind === "automation_status") {
    return <AutomationArtifactCard artifact={artifact} locale={locale} />;
  }
  return assertNever(artifact);
}

function AutomationArtifactCard({
  artifact,
  locale,
}: {
  artifact: Extract<HermesArtifact, { kind: "automation_status" }>;
  locale: Locale;
}) {
  const text = artifactCopy(locale);
  const headingId = `artifact-${safeDomId(artifact.id)}`;
  const known = artifact.data.jobs;
  const exceptions = known.filter(jobIsException);
  const healthy = known.length - exceptions.length;
  const total = 4;
  const line =
    artifact.data.overall_status === "fresh"
      ? text.automationHealthyLine(healthy, total)
      : text.automationAttentionLine(Math.max(0, total - exceptions.length), total);

  return (
    <article aria-labelledby={headingId} data-hermes-artifact-kind="automation_status">
      <Card className="bg-[var(--color-stream-surface)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Workflow
                aria-hidden="true"
                className="shrink-0 text-[var(--color-hermes)]"
                size={16}
              />
              <h3 className="font-body-sm font-semibold text-text-primary" id={headingId}>
                {text.automationStatus}
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

        <p
          className={
            artifact.data.overall_status === "fresh"
              ? "mt-3 font-body-sm font-semibold text-accent-success"
              : "mt-3 font-body-sm font-semibold text-warning"
          }
          data-hermes-automation-summary
        >
          {line}
        </p>
        <p className="mt-1 font-body-sm text-text-secondary">
          {artifact.data.overall_status === "fresh"
            ? text.automationFresh
            : text.automationDegraded}
        </p>

        {exceptions.length ? (
          <ul aria-label={text.exceptionsAria} className="mt-3 space-y-2">
            {exceptions.map((job) => (
              <li
                className="rounded-lg border border-border-subtle bg-bg-base p-3"
                data-hermes-automation-exception={job.job_id}
                key={job.job_id}
              >
                <AutomationDetails job={job} locale={locale} open />
              </li>
            ))}
          </ul>
        ) : null}
      </Card>
    </article>
  );
}

/** Derive a compact automation summary line from the model (preferred when available). */
export function automationLineFromModel(
  summary: HermesAutomationSummary,
  locale: Locale,
): string {
  const text = artifactCopy(locale);
  if (summary.status === "unavailable") return text.automationUnavailableLine;
  return text.automationHealthyLine(summary.healthy, summary.total);
}
