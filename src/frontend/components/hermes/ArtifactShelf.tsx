import { Activity, BrainCircuit, Telescope } from "lucide-react";

import { EmptyState } from "@/components/EmptyState";
import { Card, SectionTitle, StatusPill } from "@/components/ui/primitives";
import type {
  HermesArtifact,
  HermesArtifactKind,
  HermesArtifactQuality,
  HermesArtifactShelfEnvelope,
} from "@/lib/api";

type Locale = "en" | "zh";
type Tone = "neutral" | "success" | "warning" | "danger" | "info";

const copy = {
  en: {
    title: "Artifacts",
    hint: "Latest read-only outputs from Hermes research employees.",
    status: "status",
    generated: "Generated",
    portfolioRisk: "Portfolio risk",
    prediction: "Prediction",
    marketForesight: "Market foresight",
    grossExposure: "Gross exposure",
    topHolding: "Largest holding",
    historicalRisk: "Historical risk",
    confidence: "Confidence",
    horizon: "Horizon",
    candidates: "Candidates",
    candidatesAria: "Foresight prediction candidates",
    proposalOnly: "Proposal only · human confirmation required",
    direction: "Direction",
    outcomeReturn: "Outcome return",
    directionBrier: "Direction Brier",
    timelineAria: "Research artifact timeline",
    sourceAria: "Artifact source status",
    portfolioRiskSource: "Portfolio risk source",
    predictionSource: "Prediction ledger",
    marketForesightSource: "Market foresight source",
    emptyTitle: "No research artifacts yet",
    emptyDescription: "Hermes jobs can populate this read-only shelf after their first run.",
    degradedTitle: "Artifact shelf is degraded",
    degradedDescription: "Some sources are unavailable; healthy artifacts remain visible.",
    degradedEmptyDescription: "Artifact sources are unavailable and no usable output could be loaded.",
    noUsableTitle: "No usable artifacts are available",
    noUsableDescription: "Run Hermes jobs again after the artifact sources recover.",
    unavailableTitle: "Artifacts unavailable",
    unavailableDescription: "Hermes artifact sources could not be read. Existing platform pages remain read-only.",
  },
  zh: {
    title: "产物货架",
    hint: "Hermes 研究员工最新生成的只读产物。",
    status: "状态",
    generated: "生成时间",
    portfolioRisk: "组合风险",
    prediction: "预测",
    marketForesight: "市场推演",
    grossExposure: "总敞口",
    topHolding: "最大持仓",
    historicalRisk: "历史风险",
    confidence: "置信度",
    horizon: "预测期限",
    candidates: "候选预测",
    candidatesAria: "市场推演候选预测",
    proposalOnly: "仅提案 · 待人工确认",
    direction: "方向",
    outcomeReturn: "结果收益",
    directionBrier: "方向 Brier 分数",
    timelineAria: "研究产物时间线",
    sourceAria: "产物来源状态",
    portfolioRiskSource: "组合风险来源",
    predictionSource: "预测账本",
    marketForesightSource: "市场推演来源",
    emptyTitle: "暂无研究产物",
    emptyDescription: "Hermes 任务首次运行后，会把只读产物放到这里。",
    degradedTitle: "产物货架已降级",
    degradedDescription: "部分来源不可用；仍保留展示可正常读取的产物。",
    degradedEmptyDescription: "产物来源不可用，当前未能加载任何可用产物。",
    noUsableTitle: "当前没有可用产物",
    noUsableDescription: "请在产物来源恢复后重新运行 Hermes 任务。",
    unavailableTitle: "产物不可用",
    unavailableDescription: "当前无法读取 Hermes 产物来源；平台其他页面仍保持只读。",
  },
} as const;

export type ArtifactShelfProps = {
  envelope: HermesArtifactShelfEnvelope;
  locale: Locale;
};

export function ArtifactShelf({ envelope, locale }: ArtifactShelfProps) {
  const text = copy[locale];

  return (
    <section aria-labelledby="hermes-artifact-shelf-title" className="space-y-3">
      <div id="hermes-artifact-shelf-title">
        <SectionTitle title={text.title} hint={text.hint} />
      </div>
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
      {envelope.read_status === "degraded" ? (
        <div role="status">
          <Card tone="warning">
            <p className="font-body-sm font-semibold text-warning">{text.degradedTitle}</p>
            <p className="mt-1 font-body-sm text-text-secondary">
              {envelope.items.length
                ? text.degradedDescription
                : text.degradedEmptyDescription}
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
      {envelope.read_status === "unavailable" ? (
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
      ) : envelope.read_status === "empty" ? (
        <div role="status">
          <EmptyState title={text.emptyTitle} description={text.emptyDescription} />
        </div>
      ) : envelope.items.length === 0 ? (
        <div role="status">
          <EmptyState title={text.noUsableTitle} description={text.noUsableDescription} />
        </div>
      ) : (
        <ul aria-label={text.timelineAria} className="space-y-3">
          {envelope.items.map((artifact) => (
            <li key={artifact.id}>
              <ArtifactCard artifact={artifact} locale={locale} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ArtifactCard({ artifact, locale }: { artifact: HermesArtifact; locale: Locale }) {
  const text = copy[locale];
  const headingId = `artifact-${safeDomId(artifact.id)}`;

  return (
    <article aria-labelledby={headingId}>
      <Card className="bg-[var(--color-stream-surface)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <ArtifactIcon artifact={artifact} />
              <h3 className="font-body-sm font-semibold text-text-primary" id={headingId}>
                {artifactTitle(artifact, locale)}
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
        <div className="mt-4">
          <ArtifactBody artifact={artifact} locale={locale} />
        </div>
      </Card>
    </article>
  );
}

function ArtifactIcon({ artifact }: { artifact: HermesArtifact }) {
  if (artifact.kind === "portfolio_risk") {
    return <Activity aria-hidden="true" className="shrink-0 text-info" size={16} />;
  }
  if (artifact.kind === "prediction") {
    return <BrainCircuit aria-hidden="true" className="shrink-0 text-[var(--color-hermes)]" size={16} />;
  }
  return <Telescope aria-hidden="true" className="shrink-0 text-warning" size={16} />;
}

function ArtifactBody({ artifact, locale }: { artifact: HermesArtifact; locale: Locale }) {
  const text = copy[locale];
  if (artifact.kind === "portfolio_risk") {
    return (
      <dl className="grid gap-3 sm:grid-cols-3">
        <Fact
          label={text.grossExposure}
          value={formatMoney(artifact.data.gross_value, artifact.data.currency, locale)}
        />
        <Fact label={text.topHolding} value={artifact.data.largest_symbol ?? "--"} />
        <Fact label={text.historicalRisk} value={artifact.data.historical_status ?? "--"} />
      </dl>
    );
  }
  if (artifact.kind === "prediction") {
    return (
      <div className="space-y-3">
        <dl className="grid gap-3 sm:grid-cols-4">
          <Fact label={text.status} value={artifact.data.state ?? artifact.status} />
          <Fact label={text.direction} value={artifact.data.direction ?? "--"} />
          <Fact label={text.confidence} value={formatPercent(artifact.data.confidence, locale)} />
          <Fact label={text.horizon} value={artifact.data.horizon_date ?? "--"} />
        </dl>
        {artifact.data.state === "scored" || artifact.status === "scored" ? (
          <dl className="grid gap-3 sm:grid-cols-2">
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
          <p className="font-body-sm text-text-secondary">{artifact.data.rationale}</p>
        ) : null}
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <p className="font-body-sm text-text-secondary">{artifact.data.summary ?? "--"}</p>
      <p className="font-body-sm font-semibold text-warning">{text.proposalOnly}</p>
      <dl>
        <Fact
          label={text.candidates}
          value={String(artifact.data.candidate_count ?? artifact.data.candidates?.length ?? 0)}
        />
      </dl>
      {artifact.data.candidates?.length ? (
        <ul aria-label={text.candidatesAria} className="space-y-2">
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
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-border-subtle bg-bg-base p-3">
      <dt className="font-label-caps text-text-secondary">{label}</dt>
      <dd className="mt-1 break-words font-data-mono text-sm text-text-primary">{value}</dd>
    </div>
  );
}

function artifactTitle(artifact: HermesArtifact, locale: Locale) {
  const text = copy[locale];
  if (artifact.kind === "portfolio_risk") return text.portfolioRisk;
  if (artifact.kind === "prediction") {
    return `${text.prediction} · ${artifact.data.symbol ?? artifact.data.prediction_id ?? "--"}`;
  }
  return text.marketForesight;
}

function qualityTone(quality: HermesArtifactQuality): Tone {
  if (quality === "available") return "success";
  if (quality === "degraded") return "warning";
  if (quality === "unavailable") return "danger";
  return "neutral";
}

function sourceStatusTone(status: string): Tone {
  if (status === "available") return "success";
  if (status === "degraded") return "warning";
  if (status === "unavailable") return "danger";
  return "neutral";
}

function sourceLabel(kind: HermesArtifactKind, locale: Locale) {
  const text = copy[locale];
  if (kind === "portfolio_risk") return text.portfolioRiskSource;
  if (kind === "prediction") return text.predictionSource;
  return text.marketForesightSource;
}

function formatDateTime(value: string, locale: Locale) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Shanghai",
  }).format(parsed);
}

function formatMoney(value: number | null | undefined, currency: string | null | undefined, locale: Locale) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  try {
    return new Intl.NumberFormat(locale === "zh" ? "zh-CN" : "en-US", {
      style: "currency",
      currency: currency || "USD",
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${currency || "USD"} ${value.toFixed(2)}`;
  }
}

function formatPercent(value: number | null | undefined, locale: Locale) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  return new Intl.NumberFormat(locale === "zh" ? "zh-CN" : "en-US", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

function formatDecimal(value: number | null | undefined, digits: number) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  return value.toFixed(digits);
}

function safeDomId(value: string) {
  return value.replace(/[^a-zA-Z0-9_-]/g, "-");
}
