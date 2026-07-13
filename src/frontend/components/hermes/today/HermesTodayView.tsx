import type { HermesArtifact, HermesArtifactShelfEnvelope } from "@/lib/api";
import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import type { HermesTodayModel } from "@/lib/hermes/types";
import type { Locale } from "@/lib/locale";
import { ArtifactFeed } from "@/components/hermes/artifacts";
import { TechnicalDetails } from "@/components/hermes/artifacts/TechnicalDetails";
import { AttentionSummary } from "./AttentionSummary";
import { AutomationSummary } from "./AutomationSummary";
import { RecentResults } from "./RecentResults";

export type HermesTodayViewProps = {
  model: HermesTodayModel;
  /** Read-only artifact envelope for focused conclusion renderers and exception detail. */
  artifacts: HermesArtifactShelfEnvelope;
  locale: Locale;
};

function pickLatestAutomation(
  items: HermesArtifact[],
): Extract<HermesArtifact, { kind: "automation_status" }> | null {
  const automationItems = items.filter(
    (item): item is Extract<HermesArtifact, { kind: "automation_status" }> =>
      item.kind === "automation_status",
  );
  if (automationItems.length === 0) return null;
  return automationItems.reduce((latest, item) =>
    item.occurred_at > latest.occurred_at ? item : latest,
  );
}

/**
 * Hermes Today hierarchy: attention → automation (exceptions only) → recent
 * conclusions → collapsed feed/source technical detail.
 * Consumes only HermesTodayModel, locale, and read-only artifacts.
 */
export function HermesTodayView({ model, artifacts, locale }: HermesTodayViewProps) {
  const copy = hermesWorkbenchCopy(locale);
  const automationArtifact = pickLatestAutomation(artifacts.items);

  return (
    <section
      aria-labelledby="hermes-today-title"
      className="space-y-4"
      data-hermes-today
      data-hermes-today-state={model.state}
    >
      <header className="space-y-2">
        <p className="font-label-caps uppercase text-text-secondary">
          {locale === "zh" ? "今日" : "Today"}
        </p>
        <h1 className="font-headline-lg text-text-primary" id="hermes-today-title">
          {copy.states[model.state]}
        </h1>
        <p className="font-body-sm text-text-secondary">
          {locale === "zh"
            ? "以行动、异常与结论为先的只读研究工作台。提交仍保持禁用。"
            : "Read-only research desk prioritizing action, exceptions, and conclusions. Submit remains disabled."}
        </p>
      </header>

      <AttentionSummary items={model.attention} locale={locale} />

      <AutomationSummary
        artifact={automationArtifact}
        locale={locale}
        summary={model.automation}
      />

      <RecentResults artifacts={artifacts} locale={locale} results={model.recentResults} />

      <TechnicalDetails locale={locale} summary={copy.labels.technicalDetails}>
        <ArtifactFeed envelope={artifacts} locale={locale} sourcesOnly />
        {model.technical.length ? (
          <dl className="mt-2 grid gap-2 sm:grid-cols-2">
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
