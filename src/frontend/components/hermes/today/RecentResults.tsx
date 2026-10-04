import { Card, StatusPill } from "@/components/ui/primitives";
import { FocusedArtifactCard } from "@/components/hermes/artifacts";
import type { HermesArtifact, HermesArtifactShelfEnvelope } from "@/lib/api";
import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import type { HermesHqaConclusionSummary } from "@/lib/hermes/types";
import type { Locale } from "@/lib/locale";
import { artifactCopy } from "@/components/hermes/artifacts/copy";
import { qualityTone } from "@/components/hermes/artifacts/formatters";
import {
  resultDisplayTitle,
  resultStatusLabel,
  resultSummaryText,
} from "@/lib/hermes/resultsPresentation";
import { isHermesResultKind } from "@/lib/hermes/resultsTypes";

export type RecentResultsProps = {
  results: HermesHqaConclusionSummary[];
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
 * Latest HQA conclusion artifacts, not the complete platform result catalog.
 * Skips automation_status (owned by AutomationSummary) and stays visibly
 * separate from UnifiedResultsPreview.
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
    <section
      aria-labelledby="hermes-hqa-conclusions-title"
      data-hermes-hqa-conclusions
    >
      <h2
        className="font-label-caps text-text-secondary"
        id="hermes-hqa-conclusions-title"
      >
        {workbench.labels.hqaConclusions}
      </h2>

      <ul aria-label={text.timelineAria} className="mt-2 space-y-3">
        {nonAutomation.map((result) => {
          const kind = isHermesResultKind(result.kind) ? result.kind : "market_foresight";
          const presentationItem = {
            kind,
            resource_id: result.id,
            display_title: result.title,
            summary: result.summary,
            status: result.status,
            freshness: "unknown" as const,
            occurred_at: result.occurredAt,
          };
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
                        {resultDisplayTitle(presentationItem, locale)}
                      </h3>
                      <p className="mt-1 font-body-sm text-text-secondary">
                        {resultSummaryText(presentationItem, locale)}
                      </p>
                      {locale === "en" && result.limitations.length ? (
                        <ul className="mt-2 space-y-1 font-body-sm text-text-secondary">
                          {result.limitations.map((limitation) => (
                            <li key={limitation}>{limitation}</li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                    <StatusPill
                      label={text.status}
                      value={resultStatusLabel(result.status, locale)}
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
