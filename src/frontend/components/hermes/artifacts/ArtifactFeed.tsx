import { EmptyState } from "@/components/EmptyState";
import { Card, StatusPill } from "@/components/ui/primitives";
import type { HermesArtifactShelfEnvelope } from "@/lib/api";
import type { Locale } from "@/lib/locale";
import { artifactCopy, sourceLabel } from "./copy";
import { sourceStatusTone } from "./formatters";

export type ArtifactFeedProps = {
  envelope: HermesArtifactShelfEnvelope;
  locale: Locale;
  /** When true, omit empty/unavailable empty-state cards (used under collapsed technical). */
  sourcesOnly?: boolean;
};

/**
 * Feed/source-level status exactly once. Does not re-render per-item source badges.
 */
export function ArtifactFeed({ envelope, locale, sourcesOnly = false }: ArtifactFeedProps) {
  const text = artifactCopy(locale);

  return (
    <div className="space-y-3" data-hermes-artifact-feed>
      {envelope.sources.length ? (
        <ul aria-label={text.sourceAria} className="flex flex-wrap gap-2">
          {envelope.sources.map((source) => (
            <li key={source.kind}>
              <StatusPill
                label={sourceLabel(source.kind, locale)}
                value={source.status}
                tone={sourceStatusTone(source.status)}
              />
            </li>
          ))}
        </ul>
      ) : null}

      {sourcesOnly ? null : envelope.read_status === "degraded" ? (
        <div role="status">
          <Card tone="warning">
            <p className="font-body-sm font-semibold text-warning">{text.degradedTitle}</p>
            <p className="mt-1 font-body-sm text-text-secondary">
              {envelope.items.length ? text.degradedDescription : text.degradedEmptyDescription}
            </p>
            {envelope.warnings.length ? (
              <ul className="mt-2 space-y-1 font-data-mono text-xs text-text-secondary">
                {envelope.warnings.map((warning) => (
                  <li key={`${warning.source}:${warning.code}`}>
                    {warning.source} · {warning.code}
                  </li>
                ))}
              </ul>
            ) : null}
          </Card>
        </div>
      ) : null}

      {sourcesOnly ? null : envelope.read_status === "unavailable" ? (
        <div role="alert">
          <Card tone="danger">
            <p className="font-body-sm font-semibold text-danger">{text.unavailableTitle}</p>
            <p className="mt-1 font-body-sm text-text-secondary">{text.unavailableDescription}</p>
            {envelope.warnings.length ? (
              <ul className="mt-2 space-y-1 font-data-mono text-xs text-text-secondary">
                {envelope.warnings.map((warning) => (
                  <li key={`${warning.source}:${warning.code}`}>
                    {warning.source} · {warning.code}
                  </li>
                ))}
              </ul>
            ) : null}
          </Card>
        </div>
      ) : null}

      {sourcesOnly ? null : envelope.read_status === "empty" ? (
        <div role="status">
          <EmptyState title={text.emptyTitle} description={text.emptyDescription} />
        </div>
      ) : null}

      {sourcesOnly
        ? null
        : envelope.read_status !== "unavailable" &&
            envelope.read_status !== "empty" &&
            envelope.items.length === 0 ? (
            <div role="status">
              <EmptyState title={text.noUsableTitle} description={text.noUsableDescription} />
            </div>
          ) : null}
    </div>
  );
}
