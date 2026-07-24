import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import type { HermesTodayOverviewModel } from "@/lib/hermes/types";
import type { Locale } from "@/lib/locale";
import { TodayLedgerStatus } from "./TodayLedgerStatus";

export type TodayStatusLineProps = {
  model: HermesTodayOverviewModel;
  locale: Locale;
};

type DotTone = "ok" | "warn" | "err" | "idle";

function dotClass(tone: DotTone): string {
  if (tone === "ok") return "bg-accent-success";
  if (tone === "warn") return "bg-warning";
  if (tone === "err") return "bg-danger";
  return "bg-text-secondary";
}

function StatusItem({
  tone,
  name,
  children,
}: {
  tone: DotTone;
  name: string;
  children: React.ReactNode;
}) {
  return (
    <span className="inline-flex items-center gap-1.5" data-hermes-status-item={name}>
      <span aria-hidden className={`inline-block h-[7px] w-[7px] shrink-0 rounded-full ${dotClass(tone)}`} />
      {children}
    </span>
  );
}

/**
 * UI-1 Direction A one-line aggregate status bar: Hermes gateway + artifact
 * sources + automation + (chat on) command ledger, with the "system status"
 * link into the collapsed technical details.
 */
export function TodayStatusLine({ model, locale }: TodayStatusLineProps) {
  const copy = hermesWorkbenchCopy(locale).today.status;

  const gatewayTone: DotTone = model.gateway.online
    ? "ok"
    : model.gateway.readStatus === "degraded"
      ? "warn"
      : "err";
  const gatewayLabel = model.gateway.online
    ? copy.hermesOnline
    : model.gateway.readStatus === "degraded"
      ? copy.hermesDegraded
      : copy.hermesOffline;

  const sourcesTone: DotTone =
    model.sources.status === "available"
      ? "ok"
      : model.sources.status === "degraded"
        ? "warn"
        : model.sources.status === "unavailable"
          ? "err"
          : "idle";
  const sourcesLabel =
    model.sources.status === "available"
      ? copy.sourcesAll
      : model.sources.status === "degraded"
        ? copy.sourcesPartial
        : model.sources.status === "unavailable"
          ? copy.sourcesUnavailable
          : copy.sourcesEmpty;

  const automationTone: DotTone =
    model.automation.status === "unavailable"
      ? "err"
      : model.automation.exceptions.length > 0 || model.automation.status === "attention"
        ? "warn"
        : "ok";

  return (
    <div
      className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-border-subtle pb-2 font-body-sm text-text-secondary"
      data-hermes-status-line
      data-state={model.state}
    >
      <StatusItem name="gateway" tone={gatewayTone}>
        <span data-hermes-gateway-status={model.gateway.readStatus}>{gatewayLabel}</span>
      </StatusItem>
      <StatusItem name="sources" tone={sourcesTone}>
        {copy.sourcesLabel}{" "}
        <span className="text-text-primary">{sourcesLabel}</span>
      </StatusItem>
      <StatusItem name="automation" tone={automationTone}>
        {copy.automationLabel}{" "}
        {model.automation.status === "unavailable" ? (
          <span className="text-text-primary">{copy.automationUnavailable}</span>
        ) : (
          <span className="font-data-mono text-text-primary">
            {model.automation.healthy}/{model.automation.total}
          </span>
        )}
      </StatusItem>
      <TodayLedgerStatus locale={locale} />
      <a
        aria-label={copy.systemStatusAria}
        className="app-touch-target inline-flex items-center text-text-secondary underline-offset-2 transition-colors hover:text-info hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info sm:ml-auto"
        data-hermes-status-more
        href="#hermes-technical-details"
      >
        {copy.systemStatusLink}
      </a>
    </div>
  );
}
