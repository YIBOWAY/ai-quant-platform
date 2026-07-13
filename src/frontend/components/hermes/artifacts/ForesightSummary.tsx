import { Telescope } from "lucide-react";
import { Card, StatusPill } from "@/components/ui/primitives";
import type { HermesArtifact } from "@/lib/api";
import type { Locale } from "@/lib/locale";
import { artifactCopy } from "./copy";
import { Fact } from "./Fact";
import {
  formatDateTime,
  formatPercent,
  qualityTone,
  safeDomId,
} from "./formatters";
import { TechnicalDetails } from "./TechnicalDetails";

export type ForesightSummaryProps = {
  artifact: Extract<HermesArtifact, { kind: "market_foresight" }>;
  locale: Locale;
};

export function ForesightSummary({ artifact, locale }: ForesightSummaryProps) {
  const text = artifactCopy(locale);
  const headingId = `artifact-${safeDomId(artifact.id)}`;
  const conclusion =
    artifact.data.summary ||
    `${artifact.data.candidate_count ?? artifact.data.candidates?.length ?? 0} ${text.candidates}`;

  return (
    <article aria-labelledby={headingId} data-hermes-artifact-kind="market_foresight">
      <Card className="bg-[var(--color-stream-surface)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Telescope aria-hidden="true" className="shrink-0 text-warning" size={16} />
              <h3 className="font-body-sm font-semibold text-text-primary" id={headingId}>
                {text.marketForesight}
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

        <p className="mt-3 font-body-sm text-text-secondary">{conclusion}</p>
        <p className="mt-2 font-body-sm font-semibold text-warning">{text.proposalOnly}</p>
        <dl className="mt-3">
          <Fact
            label={text.candidates}
            value={String(
              artifact.data.candidate_count ?? artifact.data.candidates?.length ?? 0,
            )}
          />
        </dl>

        {artifact.data.candidates?.length ? (
          <ul aria-label={text.candidatesAria} className="mt-3 space-y-2">
            {artifact.data.candidates.map((candidate, index) => (
              <li
                className="rounded-lg border border-border-subtle bg-bg-base p-3"
                key={`${candidate.symbol ?? "candidate"}-${candidate.horizon_date ?? index}`}
              >
                <p className="font-data-mono text-sm font-semibold text-text-primary">
                  {candidate.symbol ?? "--"} · {candidate.direction ?? "--"}
                </p>
                <dl className="mt-2 grid gap-2 sm:grid-cols-3">
                  <Fact label={text.direction} value={candidate.direction ?? "--"} />
                  <Fact
                    label={text.confidence}
                    value={formatPercent(candidate.confidence, locale)}
                  />
                  <Fact label={text.horizon} value={candidate.horizon_date ?? "--"} />
                </dl>
              </li>
            ))}
          </ul>
        ) : null}

        <TechnicalDetails locale={locale}>
          <dl className="grid gap-2 sm:grid-cols-2">
            <Fact label="run_id" value={artifact.data.run_id ?? "--"} />
            <Fact label="id" value={artifact.id} />
            <Fact label="occurred_at" value={artifact.occurred_at} />
          </dl>
        </TechnicalDetails>
      </Card>
    </article>
  );
}
