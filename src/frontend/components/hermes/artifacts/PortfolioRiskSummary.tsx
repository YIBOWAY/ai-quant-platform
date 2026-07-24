import { Activity } from "lucide-react";
import { Card, StatusPill } from "@/components/ui/primitives";
import type { HermesArtifact } from "@/lib/api";
import type { Locale } from "@/lib/locale";
import { artifactCopy } from "./copy";
import { Fact } from "./Fact";
import {
  formatDateTime,
  formatMoney,
  humanizeReasonCode,
  qualityTone,
  safeDomId,
} from "./formatters";
import { TechnicalDetails } from "./TechnicalDetails";

export type PortfolioRiskSummaryProps = {
  artifact: Extract<HermesArtifact, { kind: "portfolio_risk" }>;
  locale: Locale;
};

export function PortfolioRiskSummary({ artifact, locale }: PortfolioRiskSummaryProps) {
  const text = artifactCopy(locale);
  const headingId = `artifact-${safeDomId(artifact.id)}`;
  const conclusion = artifact.data.largest_symbol
    ? `${text.topHolding}: ${artifact.data.largest_symbol}`
    : text.portfolioRisk;

  return (
    <article aria-labelledby={headingId} data-hermes-artifact-kind="portfolio_risk">
      <Card className="bg-[var(--color-stream-surface)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Activity aria-hidden="true" className="shrink-0 text-info" size={16} />
              <h3 className="font-body-sm font-semibold text-text-primary" id={headingId}>
                {text.portfolioRisk}
              </h3>
            </div>
            <p className="mt-1 font-body-sm text-text-secondary">
              {text.generated}{" "}
              <time dateTime={artifact.occurred_at}>
                {formatDateTime(artifact.occurred_at, locale)}
              </time>
            </p>
          </div>
          <StatusPill
            label={text.status}
            value={artifact.status || artifact.quality}
            tone={qualityTone(artifact.quality)}
          />
        </div>

        <p className="mt-3 font-body-sm font-semibold text-text-primary">{conclusion}</p>
        <dl className="mt-3 grid gap-3 sm:grid-cols-3">
          <Fact
            label={text.grossExposure}
            value={formatMoney(artifact.data.gross_value, artifact.data.currency, locale)}
          />
          <Fact label={text.topHolding} value={artifact.data.largest_symbol ?? "--"} />
          <Fact label={text.historicalRisk} value={artifact.data.historical_status ?? "--"} />
        </dl>

        {artifact.data.limitations?.length ? (
          <div className="mt-3">
            <p className="font-label-caps text-text-secondary">{text.limitations}</p>
            <ul className="mt-1 space-y-1 font-body-sm text-text-secondary">
              {artifact.data.limitations.map((limitation) => (
                <li key={limitation}>{humanizeReasonCode(limitation, locale)}</li>
              ))}
            </ul>
          </div>
        ) : null}

        <TechnicalDetails locale={locale}>
          <dl className="grid gap-2 sm:grid-cols-2">
            <Fact label="account" value={artifact.data.account_id ?? "--"} />
            <Fact label="benchmark" value={artifact.data.benchmark ?? "--"} />
            <Fact label="id" value={artifact.id} />
            <Fact label="occurred_at" value={artifact.occurred_at} />
          </dl>
        </TechnicalDetails>
      </Card>
    </article>
  );
}
