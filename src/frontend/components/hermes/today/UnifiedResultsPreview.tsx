import Link from "next/link";

import { Card, StatusPill } from "@/components/ui/primitives";
import { qualityTone } from "@/components/hermes/artifacts/formatters";
import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import { hermesRouteHref } from "@/lib/hermes/routes";
import type { HermesUnifiedResultsPreview as UnifiedResultsPreviewModel } from "@/lib/hermes/types";
import { localizePath, type Locale } from "@/lib/locale";

export type UnifiedResultsPreviewProps = {
  preview: UnifiedResultsPreviewModel;
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

/**
 * Bounded GET-only preview of the cross-source result catalog. This is kept
 * separate from HQA conclusion artifacts so neither read source impersonates
 * the other.
 */
export function UnifiedResultsPreview({
  preview,
  locale,
}: UnifiedResultsPreviewProps) {
  const text = hermesWorkbenchCopy(locale);
  const unavailable = preview.readStatus === "unavailable";
  const degraded = preview.readStatus === "degraded";
  const resultList = preview.items.length ? (
    <ul className="mt-2 grid gap-2 lg:grid-cols-2">
      {preview.items.map((item) => (
        <li key={`${item.kind}:${item.resourceId}`}>
          <Card className="h-full bg-[var(--color-stream-surface)]">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <Link
                  className="font-body-sm font-semibold text-text-primary underline-offset-2 hover:text-info hover:underline"
                  href={resultDetailHref(item, locale)}
                >
                  {item.displayTitle}
                </Link>
                {item.summary ? (
                  <p className="mt-1 font-body-sm text-text-secondary">
                    {item.summary}
                  </p>
                ) : null}
                <p className="mt-2 break-all font-data-mono text-xs text-text-secondary">
                  {item.kind} · {item.resourceId}
                </p>
              </div>
              <StatusPill
                label={locale === "zh" ? "状态" : "Status"}
                value={item.status}
                tone={qualityTone(item.status)}
              />
            </div>
          </Card>
        </li>
      ))}
    </ul>
  ) : null;

  return (
    <section
      aria-labelledby="hermes-unified-results-preview-title"
      data-hermes-unified-results-preview
      data-state={preview.readStatus}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-baseline gap-2">
          <h2
            className="font-label-caps text-text-secondary"
            id="hermes-unified-results-preview-title"
          >
            {text.labels.unifiedResults}
          </h2>
          {preview.total !== null ? (
            <span className="font-data-mono text-xs text-text-secondary">
              {locale === "zh" ? `共 ${preview.total} 项` : `${preview.total} total`}
            </span>
          ) : null}
        </div>
        <Link
          className="app-touch-target inline-flex items-center font-body-sm text-info underline-offset-2 hover:underline"
          href={hermesRouteHref("results", locale)}
        >
          {text.labels.viewUnifiedResults}
        </Link>
      </div>

      {unavailable ? (
        <Card className="mt-2 border-warning/40 bg-warning/5" role="status">
          <p className="font-body-sm font-semibold text-warning">
            {text.labels.unifiedResultsUnavailable}
          </p>
          <p className="mt-1 font-body-sm text-text-secondary">
            {text.labels.unifiedResultsIndependentTruth}
          </p>
          {preview.warningCode ? (
            <p className="mt-2 font-data-mono text-xs text-text-secondary">
              {preview.warningCode}
            </p>
          ) : null}
        </Card>
      ) : (
        <>
          {degraded ? (
            <Card className="mt-2 border-warning/40 bg-warning/5" role="status">
              <p className="font-body-sm text-warning">
                {text.labels.unifiedResultsDegraded}
              </p>
              {preview.warningCode ? (
                <p className="mt-2 font-data-mono text-xs text-text-secondary">
                  {preview.warningCode}
                </p>
              ) : null}
            </Card>
          ) : null}
          {resultList ??
            (!degraded ? (
              <Card className="mt-2 bg-[var(--color-stream-surface)]">
                <p className="font-body-sm text-text-secondary">
                  {text.labels.unifiedResultsEmpty}
                </p>
              </Card>
            ) : null)}
        </>
      )}
    </section>
  );
}
