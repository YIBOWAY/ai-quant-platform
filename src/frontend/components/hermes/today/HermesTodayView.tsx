import type { HermesArtifactShelfEnvelope } from "@/lib/api";
import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import type { HermesTodayOverviewModel } from "@/lib/hermes/types";
import type { Locale } from "@/lib/locale";
import { ArtifactFeed } from "@/components/hermes/artifacts";
import { TechnicalDetails } from "@/components/hermes/artifacts/TechnicalDetails";
import { TodayAttention } from "./TodayAttention";
import { TodayGreeting } from "./TodayGreeting";
import { TodayRunning } from "./TodayRunning";
import { TodayStatusLine } from "./TodayStatusLine";

export type HermesTodayViewProps = {
  model: HermesTodayOverviewModel;
  /** Read-only artifact envelope for collapsed source detail. */
  artifacts: HermesArtifactShelfEnvelope;
  locale: Locale;
};

/**
 * UI-1 Direction A Today overview: greeting → status line → unified action
 * lane → running commands → collapsed technical detail. Results and the
 * automation lane live in the second Suspense boundary
 * (HermesTodaySecondarySection) so each half loads independently.
 */
export function HermesTodayView({ model, artifacts, locale }: HermesTodayViewProps) {
  const copy = hermesWorkbenchCopy(locale);

  return (
    <section
      aria-labelledby="hermes-today-title"
      className="flex flex-col gap-4 sm:gap-5"
      data-hermes-today
      data-hermes-today-state={model.state}
      data-state={model.state}
      data-testid="hermes-today-state"
    >
      <TodayGreeting locale={locale} model={model} />

      <TodayStatusLine locale={locale} model={model} />

      <TodayAttention items={model.attention} locale={locale} />

      <TodayRunning locale={locale} />

      <TechnicalDetails
        id="hermes-technical-details"
        locale={locale}
        summary={copy.labels.technicalDetails}
      >
        <ArtifactFeed envelope={artifacts} locale={locale} sourcesOnly />
        <div className="rounded-lg border border-border-subtle bg-bg-base p-3">
          <p className="font-label-caps text-text-secondary">hermes_gateway</p>
          <p className="mt-1 font-data-mono text-xs text-text-primary">
            {model.gateway.readStatus}
            {model.gateway.connected ? " · connected" : " · disconnected"}
          </p>
          {model.gateway.blockers.length || model.gateway.warningCodes.length ? (
            <ul className="mt-2 space-y-1 font-data-mono text-xs text-text-secondary">
              {model.gateway.blockers.map((code) => (
                <li key={`blocker:${code}`}>blocker: {code}</li>
              ))}
              {model.gateway.warningCodes.map((code) => (
                <li key={`warning:${code}`}>warning: {code}</li>
              ))}
            </ul>
          ) : null}
        </div>
        {model.technical.length ? (
          <dl className="grid gap-2 sm:grid-cols-2">
            {model.technical.map((source) => (
              <div
                className="rounded-lg border border-border-subtle bg-bg-base p-3"
                key={source.id}
              >
                <dt className="font-label-caps text-text-secondary">{source.label}</dt>
                <dd className="mt-1 font-data-mono text-xs text-text-primary">
                  {source.status}
                  {source.lastSyncedAt ? ` · ${source.lastSyncedAt}` : ""}
                </dd>
                {source.details.length ? (
                  <ul className="mt-2 space-y-1 font-data-mono text-xs text-text-secondary">
                    {source.details.map((detail) => (
                      <li key={`${source.id}:${detail.label}`}>
                        {detail.label}: {detail.value}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ))}
          </dl>
        ) : null}
      </TechnicalDetails>
    </section>
  );
}
