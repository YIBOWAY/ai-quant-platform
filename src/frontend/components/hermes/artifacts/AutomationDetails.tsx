import { StatusPill } from "@/components/ui/primitives";
import type { HermesAutomationStatusArtifactData } from "@/lib/api";
import type { Locale } from "@/lib/locale";
import {
  automationJobLabel,
  automationStatusLabel,
  artifactCopy,
  notificationStatusLabel,
} from "./copy";
import { Fact } from "./Fact";
import {
  automationStatusTone,
  formatDateTime,
  formatDuration,
  humanizeReasonCode,
} from "./formatters";
import { TechnicalDetails } from "./TechnicalDetails";

export type AutomationJob = HermesAutomationStatusArtifactData["jobs"][number];

export type AutomationDetailsProps = {
  job: AutomationJob;
  locale: Locale;
  /** Exceptional jobs expand technical detail by default. */
  open?: boolean;
};

/**
 * Cron, freshness, last attempt/success, Run ID, and notification status
 * live only inside collapsed technical detail.
 */
export function AutomationDetails({ job, locale, open = false }: AutomationDetailsProps) {
  const text = artifactCopy(locale);
  const status = job.status as "fresh" | "stale" | "failed" | "never_run";

  return (
    <div data-hermes-automation-details={job.job_id}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-data-mono text-sm font-semibold text-text-primary">
          {automationJobLabel(job.job_id, locale)}
        </p>
        <StatusPill
          label={text.status}
          value={automationStatusLabel(status, locale)}
          tone={automationStatusTone(status)}
        />
      </div>
      {job.reason_code ? (
        <p className="mt-2 font-data-mono text-xs text-warning">
          {humanizeReasonCode(job.reason_code, locale)}
        </p>
      ) : null}
      <TechnicalDetails locale={locale} open={open}>
        <dl className="grid gap-2 sm:grid-cols-3">
          <Fact
            label={text.expectedSchedule}
            value={`${job.expected_schedule} · ${job.timezone}`}
          />
          <Fact
            label={text.freshnessBudget}
            value={formatDuration(job.freshness_budget_seconds, locale)}
          />
          <Fact
            label={text.lastAttempt}
            value={
              job.last_attempt_at
                ? formatDateTime(job.last_attempt_at, locale)
                : text.neverRun
            }
          />
          <Fact
            label={text.lastSuccess}
            value={
              job.last_success_at
                ? formatDateTime(job.last_success_at, locale)
                : text.neverRun
            }
          />
          <Fact
            label={text.freshUntil}
            value={
              job.fresh_until ? formatDateTime(job.fresh_until, locale) : text.neverRun
            }
          />
          <Fact label={text.lastRun} value={job.last_run_id ?? text.neverRun} />
          <Fact
            label={text.notification}
            value={notificationStatusLabel(job.notification_status, locale)}
          />
        </dl>
      </TechnicalDetails>
    </div>
  );
}
