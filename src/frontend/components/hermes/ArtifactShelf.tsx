import { SectionTitle } from "@/components/ui/primitives";
import type { HermesArtifactShelfEnvelope } from "@/lib/api";
import type { Locale } from "@/lib/locale";
import {
  ArtifactFeed,
  FocusedArtifactCard,
  artifactCopy,
} from "@/components/hermes/artifacts";

export type ArtifactShelfProps = {
  envelope: HermesArtifactShelfEnvelope;
  locale: Locale;
};

/**
 * Compatibility facade over focused artifact renderers.
 * Prefer HermesTodayView for the production hierarchy; this shelf remains for
 * direct envelope rendering and unit coverage until later callers migrate.
 */
export function ArtifactShelf({ envelope, locale }: ArtifactShelfProps) {
  const text = artifactCopy(locale);
  const showItems =
    envelope.read_status !== "unavailable" &&
    envelope.read_status !== "empty" &&
    envelope.items.length > 0;

  return (
    <section aria-labelledby="hermes-artifact-shelf-title" className="space-y-3">
      <div id="hermes-artifact-shelf-title">
        <SectionTitle title={text.title} hint={text.hint} />
      </div>
      <ArtifactFeed envelope={envelope} locale={locale} />
      {showItems ? (
        <ul aria-label={text.timelineAria} className="space-y-3">
          {envelope.items.map((artifact) => (
            <li key={artifact.id}>
              <FocusedArtifactCard artifact={artifact} locale={locale} />
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
