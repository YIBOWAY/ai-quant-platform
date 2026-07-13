import Link from "next/link";
import { Card, StatusPill } from "@/components/ui/primitives";
import { FocusedArtifactCard } from "@/components/hermes/artifacts";
import type { HermesArtifact, HermesArtifactShelfEnvelope } from "@/lib/api";
import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import { hermesRouteHref } from "@/lib/hermes/routes";
import type { HermesResultSummary } from "@/lib/hermes/types";
import type { Locale } from "@/lib/locale";
import { artifactCopy } from "@/components/hermes/artifacts/copy";
import { qualityTone } from "@/components/hermes/artifacts/formatters";

export type RecentResultsProps = {
  results: HermesResultSummary[];
  artifacts: HermesArtifactShelfEnvelope;
  locale: Locale;
  /** Prefer focused conclusion cards when matching artifacts exist. */
  preferFocusedCards?: boolean;
};

function findArtifact(
  artifacts: HermesArtifactShelfEnvelope,
  id: string,
): HermesArtifact | null {
  return artifacts.items.find((item) => item.id === id) ?? null;
}

/**
 * Latest meaningful results — conclusions and key evidence, not raw source dumps.
 * Skips automation_status (owned by AutomationSummary).
 */
export function RecentResults({
  results,
  artifacts,
  locale,
  preferFocusedCards = true,
}: RecentResultsProps) {
  const workbench = hermesWorkbenchCopy(locale);
  const text = artifactCopy(locale);
  const nonAutomation = results.filter((item) => item.kind !== "automation_status");

  if (nonAutomation.length === 0) {
    return null;
  }

  return (
    <section aria-labelledby="hermes-recent-results-title" data-hermes-recent-results>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2
          className="font-label-caps text-text-secondary"
          id="hermes-recent-results-title"
        >
          {workbench.labels.recentResults}
        </h2>
        <Link
          className="app-touch-target inline-flex items-center font-body-sm text-info underline-offset-2 hover:underline"
          href={hermesRouteHref("results", locale)}
        >
          {locale === "zh" ? "查看全部结果" : "View all results"}
        </Link>
      </div>

      <ul aria-label={text.timelineAria} className="mt-2 space-y-3">
        {nonAutomation.map((result) => {
          const artifact = preferFocusedCards
            ? findArtifact(artifacts, result.id)
            : null;

          if (artifact && artifact.kind !== "automation_status") {
            return (
              <li key={result.id}>
                <FocusedArtifactCard artifact={artifact} locale={locale} />
              </li>
            );
          }

          return (
            <li key={result.id}>
              <article data-hermes-result-id={result.id}>
                <Card className="bg-[var(--color-stream-surface)]">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h3 className="font-body-sm font-semibold text-text-primary">
                        {result.title}
                      </h3>
                      <p className="mt-1 font-body-sm text-text-secondary">{result.summary}</p>
                      {result.limitations.length ? (
                        <ul className="mt-2 space-y-1 font-body-sm text-text-secondary">
                          {result.limitations.map((limitation) => (
                            <li key={limitation}>{limitation}</li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                    <StatusPill
                      label={text.status}
                      value={result.status}
                      tone={qualityTone(result.status)}
                    />
                  </div>
                </Card>
              </article>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
