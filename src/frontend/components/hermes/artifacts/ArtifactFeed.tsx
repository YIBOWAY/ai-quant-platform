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

export type ArtifactFeedReadState =
  | "available"
  | "empty"
  | "degraded"
  | "unavailable";

/** Normalize transport failures and forward-compatible corrupt states first. */
export function artifactFeedReadState(
  envelope: HermesArtifactShelfEnvelope,
): ArtifactFeedReadState {
  const runtimeStatus = String(envelope.read_status);
  if (
    envelope.apiError ||
    runtimeStatus === "unavailable" ||
    runtimeStatus === "corrupt"
  ) {
    return "unavailable";
  }
  if (runtimeStatus === "degraded") return "degraded";
  if (runtimeStatus === "empty") return "empty";
  if (runtimeStatus === "available") return "available";
  return "unavailable";
}

function artifactFeedReasons(envelope: HermesArtifactShelfEnvelope): string[] {
  const runtimeStatus = String(envelope.read_status);
  const knownReadStatuses = new Set([
    "available",
    "empty",
    "degraded",
    "unavailable",
    "corrupt",
  ]);
  return Array.from(
    new Set([
      ...(envelope.apiError ? [envelope.apiError] : []),
      ...(!knownReadStatuses.has(runtimeStatus)
        ? ["artifact_feed · read_status_invalid"]
        : []),
      ...envelope.warnings.map(
        (warning) => `${warning.source} · ${warning.code}`,
      ),
      ...envelope.sources.flatMap((source) =>
        source.reason_code
          ? [`${source.kind} · ${source.reason_code}`]
          : source.status === "degraded" || source.status === "unavailable"
            ? [`${source.kind} · ${source.status}`]
            : [],
      ),
    ]),
  );
}

/**
 * Feed/source-level status exactly once. Does not re-render per-item source badges.
 */
export function ArtifactFeed({ envelope, locale, sourcesOnly = false }: ArtifactFeedProps) {
  const text = artifactCopy(locale);
  const readState = artifactFeedReadState(envelope);
  const reasons = artifactFeedReasons(envelope);

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

      {sourcesOnly ? null : readState === "degraded" ? (
        <div role="status">
          <Card tone="warning">
            <p className="font-body-sm font-semibold text-warning">{text.degradedTitle}</p>
            <p className="mt-1 font-body-sm text-text-secondary">
              {envelope.items.length ? text.degradedDescription : text.degradedEmptyDescription}
            </p>
            {reasons.length ? (
              <ul className="mt-2 space-y-1 font-data-mono text-xs text-text-secondary">
                {reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            ) : null}
          </Card>
        </div>
      ) : null}

      {sourcesOnly ? null : readState === "unavailable" ? (
        <div role="alert">
          <Card tone="danger">
            <p className="font-body-sm font-semibold text-danger">{text.unavailableTitle}</p>
            <p className="mt-1 font-body-sm text-text-secondary">{text.unavailableDescription}</p>
            {reasons.length ? (
              <ul className="mt-2 space-y-1 font-data-mono text-xs text-text-secondary">
                {reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            ) : null}
          </Card>
        </div>
      ) : null}

      {sourcesOnly ? null : readState === "empty" ? (
        <div role="status">
          <EmptyState title={text.emptyTitle} description={text.emptyDescription} />
        </div>
      ) : null}

      {sourcesOnly
        ? null
        : readState !== "unavailable" &&
            readState !== "empty" &&
            envelope.items.length === 0 ? (
            <div role="status">
              <EmptyState title={text.noUsableTitle} description={text.noUsableDescription} />
            </div>
          ) : null}
    </div>
  );
}
