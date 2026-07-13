import { BrainCircuit } from "lucide-react";
import { Card, StatusPill } from "@/components/ui/primitives";
import type { HermesArtifact } from "@/lib/api";
import type { Locale } from "@/lib/locale";
import { artifactCopy } from "./copy";
import { Fact } from "./Fact";
import {
  formatDateTime,
  formatDecimal,
  formatPercent,
  qualityTone,
  safeDomId,
} from "./formatters";
import { TechnicalDetails } from "./TechnicalDetails";

export type PredictionSummaryProps = {
  artifact: Extract<HermesArtifact, { kind: "prediction" }>;
  locale: Locale;
};

export function PredictionSummary({ artifact, locale }: PredictionSummaryProps) {
  const text = artifactCopy(locale);
  const headingId = `artifact-${safeDomId(artifact.id)}`;
  const title = `${text.prediction} · ${artifact.data.symbol ?? artifact.data.prediction_id ?? "--"}`;
  const conclusion = `${artifact.data.direction ?? "--"} · ${artifact.data.state ?? artifact.status}`;

  return (
    <article aria-labelledby={headingId} data-hermes-artifact-kind="prediction">
      <Card className="bg-[var(--color-stream-surface)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <BrainCircuit
                aria-hidden="true"
                className="shrink-0 text-[var(--color-hermes)]"
                size={16}
              />
              <h3 className="font-body-sm font-semibold text-text-primary" id={headingId}>
                {title}
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
        <dl className="mt-3 grid gap-3 sm:grid-cols-4">
          <Fact label={text.status} value={artifact.data.state ?? artifact.status} />
          <Fact label={text.direction} value={artifact.data.direction ?? "--"} />
          <Fact
            label={text.confidence}
            value={formatPercent(artifact.data.confidence, locale)}
          />
          <Fact label={text.horizon} value={artifact.data.horizon_date ?? "--"} />
        </dl>

        {artifact.data.state === "scored" || artifact.status === "scored" ? (
          <dl className="mt-3 grid gap-3 sm:grid-cols-2">
            <Fact
              label={text.outcomeReturn}
              value={formatPercent(artifact.data.outcome_return, locale)}
            />
            <Fact
              label={text.directionBrier}
              value={formatDecimal(artifact.data.direction_brier, 3)}
            />
          </dl>
        ) : null}

        {artifact.data.rationale ? (
          <p className="mt-3 font-body-sm text-text-secondary">{artifact.data.rationale}</p>
        ) : null}

        <TechnicalDetails locale={locale}>
          <dl className="grid gap-2 sm:grid-cols-2">
            <Fact label="prediction_id" value={artifact.data.prediction_id ?? "--"} />
            <Fact label="id" value={artifact.id} />
            <Fact label="occurred_at" value={artifact.occurred_at} />
          </dl>
        </TechnicalDetails>
      </Card>
    </article>
  );
}
