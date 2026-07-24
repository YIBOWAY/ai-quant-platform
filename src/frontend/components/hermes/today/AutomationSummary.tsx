import { Workflow } from "lucide-react";
import { Card } from "@/components/ui/primitives";
import type { HermesArtifact, HermesAutomationStatusArtifactData } from "@/lib/api";
import type { HermesAutomationSummary as AutomationModel } from "@/lib/hermes/types";
import type { Locale } from "@/lib/locale";
import {
  AutomationDetails,
  artifactCopy,
  automationLineFromModel,
} from "@/components/hermes/artifacts";

export type AutomationSummaryProps = {
  summary: AutomationModel;
  /** Latest automation_status artifact for exception job detail rows. */
  artifact: Extract<HermesArtifact, { kind: "automation_status" }> | null;
  locale: Locale;
};

function jobById(
  artifact: Extract<HermesArtifact, { kind: "automation_status" }> | null,
  jobId: string,
): HermesAutomationStatusArtifactData["jobs"][number] | null {
  if (!artifact) return null;
  return artifact.data.jobs.find((job) => job.job_id === jobId) ?? null;
}

/**
 * Compresses healthy jobs to one "N/4 normal" line; only exceptions expand.
 */
export function AutomationSummary({ summary, artifact, locale }: AutomationSummaryProps) {
  const text = artifactCopy(locale);
  const line = automationLineFromModel(summary, locale);
  const isHealthy = summary.status === "healthy" && summary.exceptions.length === 0;

  return (
    <section aria-labelledby="hermes-automation-title" data-hermes-automation>
      <Card className="bg-[var(--color-stream-surface)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <Workflow
              aria-hidden="true"
              className="shrink-0 text-[var(--color-hermes)]"
              size={16}
            />
            <h2
              className={
                isHealthy
                  ? "font-body-sm font-semibold text-accent-success"
                  : summary.status === "unavailable"
                    ? "font-body-sm font-semibold text-danger"
                    : "font-body-sm font-semibold text-warning"
              }
              data-hermes-automation-summary
              id="hermes-automation-title"
            >
              {line}
            </h2>
          </div>
        </div>

        {isHealthy ? (
          <p className="mt-2 font-body-sm text-text-secondary">{text.automationFresh}</p>
        ) : summary.status === "unavailable" ? (
          <p className="mt-2 font-body-sm text-text-secondary">
            {text.automationUnavailableLine}
          </p>
        ) : (
          <p className="mt-2 font-body-sm text-text-secondary">{text.automationDegraded}</p>
        )}

        {summary.exceptions.length ? (
          <ul
            aria-label={text.exceptionsAria}
            className="mt-3 space-y-2"
            data-hermes-automation-exceptions
          >
            {summary.exceptions.map((exception) => {
              const job = jobById(artifact, exception.jobId);
              return (
                <li
                  className="rounded-lg border border-border-subtle bg-bg-base p-3"
                  data-hermes-automation-exception={exception.jobId}
                  key={exception.jobId}
                >
                  {job ? (
                    <AutomationDetails job={job} locale={locale} open />
                  ) : (
                    <div>
                      <p className="font-data-mono text-sm font-semibold text-text-primary">
                        {exception.jobId}
                      </p>
                      <p className="mt-1 font-body-sm text-warning">
                        {exception.status} · {exception.reason}
                      </p>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        ) : null}
      </Card>
    </section>
  );
}
