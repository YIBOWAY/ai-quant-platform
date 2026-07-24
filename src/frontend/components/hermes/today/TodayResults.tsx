import Link from "next/link";
import { StatusPill } from "@/components/ui/primitives";
import {
  formatDateTime,
  qualityTone,
} from "@/components/hermes/artifacts/formatters";
import { artifactCopy } from "@/components/hermes/artifacts/copy";
import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import { hermesRouteHref } from "@/lib/hermes/routes";
import type {
  HermesHqaConclusionSummary,
  HermesUnifiedResultsPreview as UnifiedResultsPreviewModel,
} from "@/lib/hermes/types";
import { localizePath, type Locale } from "@/lib/locale";

export type TodayResultsProps = {
  preview: UnifiedResultsPreviewModel;
  /** Independent read-only artifact-feed conclusions (fallback when the
   *  unified catalog cannot be read — never presented as catalog rows). */
  hqaConclusions: HermesHqaConclusionSummary[];
  locale: Locale;
};

function resultDetailHref(
  item: UnifiedResultsPreviewModel["items"][number],
  locale: Locale,
): string {
  return localizePath(
    `/hermes/results/${item.kind}/${encodeURIComponent(item.resourceId)}`,
    locale,
  );
}

const KIND_TAG =
  "inline-flex items-center rounded border border-border-subtle px-1.5 py-px font-data-mono text-[10.5px] leading-4 text-text-secondary";

/**
 * UI-1 Direction A merged "recent results" lane: one bounded list from the
 * unified result catalog (limit 5) — display_title + kind tag + status pill
 * + occurred_at + detail link. The artifact-shelf duplicate preview is gone;
 * when the catalog is unreadable the section says so in one honest line and
 * only then falls back to the independent artifact feed.
 */
export function TodayResults({ preview, hqaConclusions, locale }: TodayResultsProps) {
  const workbench = hermesWorkbenchCopy(locale);
  const copy = workbench.today.results;
  const text = artifactCopy(locale);
  const unavailable = preview.readStatus === "unavailable";
  const degraded = preview.readStatus === "degraded";
  const showHqaFallback = unavailable && hqaConclusions.length > 0;

  return (
    <section
      aria-labelledby="hermes-today-results-title"
      data-hermes-today-results
      data-hermes-unified-results-preview
      data-state={preview.readStatus}
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="font-body-sm font-semibold text-text-primary" id="hermes-today-results-title">
          {copy.title}
        </h2>
        {preview.total !== null ? (
          <span className="font-data-mono text-xs text-text-secondary">
            {preview.total}
          </span>
        ) : null}
        {degraded ? (
          <span className="font-data-mono text-xs text-warning">{copy.delayed}</span>
        ) : null}
        <Link
          className="ml-auto font-body-sm text-text-secondary underline-offset-2 hover:text-info hover:underline"
          href={hermesRouteHref("results", locale)}
        >
          {copy.viewAll}
        </Link>
      </div>

      {unavailable ? (
        <p className="mt-1 border-b border-border-subtle py-2 font-body-sm text-text-secondary" role="status">
          {copy.unavailable}
          {preview.warningCode ? (
            <span className="ml-2 font-data-mono text-xs">{preview.warningCode}</span>
          ) : null}
        </p>
      ) : null}

      {preview.items.length ? (
        <ol className="mt-1 border-t border-border-subtle" data-hermes-today-results-list>
          {preview.items.map((item) => (
            <li key={`${item.kind}:${item.resourceId}`}>
              <Link
                className="flex flex-wrap items-center gap-3 border-b border-border-subtle py-2.5 transition-colors hover:bg-bg-surface-muted/40"
                href={resultDetailHref(item, locale)}
              >
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="truncate font-body-sm font-medium text-text-primary">
                      {item.displayTitle}
                    </span>
                    <span className={KIND_TAG}>{item.kind}</span>
                  </span>
                </span>
                <StatusPill
                  label={text.status}
                  value={item.status}
                  tone={qualityTone(item.status)}
                />
                <span className="shrink-0 font-data-mono text-[11px] text-text-secondary">
                  {formatDateTime(item.occurredAt, locale)}
                </span>
                <span aria-hidden className="shrink-0 text-text-secondary">
                  →
                </span>
              </Link>
            </li>
          ))}
        </ol>
      ) : !unavailable && !degraded && !showHqaFallback ? (
        <p className="mt-1 border-b border-border-subtle py-2 font-body-sm text-text-secondary">
          {copy.empty}
        </p>
      ) : null}

      {degraded ? (
        <p className="mt-1 border-b border-border-subtle py-2 font-body-sm text-warning" role="status">
          {workbench.labels.unifiedResultsDegraded}
          {preview.warningCode ? (
            <span className="ml-2 font-data-mono text-xs text-text-secondary">
              {preview.warningCode}
            </span>
          ) : null}
        </p>
      ) : null}

      {showHqaFallback ? (
        <div className="mt-2">
          <p className="font-body-sm text-text-secondary">{copy.independentFeedNote}</p>
          <ol className="mt-1 border-t border-border-subtle" data-hermes-hqa-conclusions>
            {hqaConclusions.slice(0, 5).map((result) => (
              <li
                className="flex flex-wrap items-center gap-3 border-b border-border-subtle py-2.5"
                data-hermes-result-id={result.id}
                key={result.id}
              >
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="truncate font-body-sm font-medium text-text-primary">
                      {result.title}
                    </span>
                    <span className={KIND_TAG}>{result.kind}</span>
                  </span>
                </span>
                <StatusPill
                  label={text.status}
                  value={result.status}
                  tone={qualityTone(result.status)}
                />
                <span className="shrink-0 font-data-mono text-[11px] text-text-secondary">
                  {formatDateTime(result.occurredAt, locale)}
                </span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
    </section>
  );
}
