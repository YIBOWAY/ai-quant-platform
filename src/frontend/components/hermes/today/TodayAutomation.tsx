import { StatusPill } from "@/components/ui/primitives";
import type { HermesArtifact } from "@/lib/api";
import type { HermesAutomationSummary as AutomationModel } from "@/lib/hermes/types";
import { HERMES_KNOWN_JOB_IDS } from "@/lib/hermes/viewModel";
import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import type { Locale } from "@/lib/locale";
import {
  AutomationDetails,
  artifactCopy,
  automationLineFromModel,
} from "@/components/hermes/artifacts";
import {
  automationJobLabel,
  automationStatusLabel,
} from "@/components/hermes/artifacts/copy";
import {
  automationStatusTone,
  formatDateTime,
} from "@/components/hermes/artifacts/formatters";

export type TodayAutomationProps = {
  summary: AutomationModel;
  /** Latest automation_status artifact for job rows. */
  artifact: Extract<HermesArtifact, { kind: "automation_status" }> | null;
  locale: Locale;
};

function latestSuccessAt(
  artifact: TodayAutomationProps["artifact"],
): string | null {
  if (!artifact) return null;
  let latest: string | null = null;
  for (const job of artifact.data.jobs) {
    if (!job.last_success_at) continue;
    if (!latest || Date.parse(job.last_success_at) > Date.parse(latest)) {
      latest = job.last_success_at;
    }
  }
  return latest;
}

/**
 * UI-1 Direction A automation lane: healthy collapses to one row
 * ("N/4 healthy · last success …"); exceptions expand the fixed four-job
 * list with status / reason_code / last_success_at (no next_run — the
 * contract has no such field). Exception rows keep the V-series detail
 * disclosure open.
 */
export function TodayAutomation({ summary, artifact, locale }: TodayAutomationProps) {
  const text = artifactCopy(locale);
  const copy = hermesWorkbenchCopy(locale).today.automation;
  const line = automationLineFromModel(summary, locale);
  const exceptionIds = new Set(summary.exceptions.map((entry) => entry.jobId));
  const jobs = (artifact?.data.jobs ?? [])
    .filter((job) => HERMES_KNOWN_JOB_IDS.includes(job.job_id))
    .sort(
      (a, b) =>
        HERMES_KNOWN_JOB_IDS.indexOf(a.job_id) -
        HERMES_KNOWN_JOB_IDS.indexOf(b.job_id),
    );
  const latestSuccess = latestSuccessAt(artifact);
  const summaryTone =
    summary.status === "unavailable"
      ? "text-danger"
      : summary.exceptions.length > 0
        ? "text-warning"
        : "text-accent-success";

  return (
    <section
      aria-labelledby="hermes-automation-title"
      data-hermes-automation
      id="hermes-today-automation"
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="font-body-sm font-semibold text-text-primary" id="hermes-automation-title">
          {copy.title}
        </h2>
        <span
          className={`font-body-sm font-semibold ${summaryTone}`}
          data-hermes-automation-summary
        >
          {line}
        </span>
      </div>

      {summary.status === "unavailable" ? (
        <p className="mt-1 border-b border-border-subtle py-2 font-body-sm text-text-secondary">
          {text.automationUnavailableLine}
        </p>
      ) : summary.exceptions.length === 0 ? (
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border-subtle py-2">
          <span className="font-data-mono text-xs text-text-secondary">
            {HERMES_KNOWN_JOB_IDS.join(" · ")}
          </span>
          <StatusPill
            label={text.status}
            value={`${summary.healthy}/${summary.total} fresh`}
            tone="success"
          />
          <span className="font-data-mono text-[11px] text-text-secondary">
            {copy.lastSuccessPrefix}{" "}
            {latestSuccess ? formatDateTime(latestSuccess, locale) : copy.lastSuccessNever}
          </span>
        </div>
      ) : (
        <ul className="mt-1 border-t border-border-subtle" data-hermes-automation-exceptions>
          {jobs.map((job) => {
            const status = job.status as "fresh" | "stale" | "failed" | "never_run";
            if (exceptionIds.has(job.job_id)) {
              return (
                <li
                  className="border-b border-border-subtle py-2"
                  data-hermes-automation-exception={job.job_id}
                  key={job.job_id}
                >
                  <AutomationDetails job={job} locale={locale} open />
                </li>
              );
            }
            return (
              <li
                className="flex flex-wrap items-center gap-3 border-b border-border-subtle py-2"
                key={job.job_id}
              >
                <span className="min-w-0 flex-1 font-data-mono text-xs text-text-primary">
                  {automationJobLabel(job.job_id, locale)}
                </span>
                <StatusPill
                  label={text.status}
                  value={automationStatusLabel(status, locale)}
                  tone={automationStatusTone(status)}
                />
                <span className="shrink-0 font-data-mono text-[11px] text-text-secondary">
                  {job.last_success_at
                    ? formatDateTime(job.last_success_at, locale)
                    : copy.lastSuccessNever}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
