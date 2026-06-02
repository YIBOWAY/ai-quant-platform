type DataSourceBadgeProps = {
  source: string;
};

export function isSampleSource(source: string | undefined | null): boolean {
  return Boolean(source && source.toLowerCase().includes("sample"));
}

function badgeClass(source: string) {
  const normalized = source.toLowerCase();
  if (normalized.includes("failed") || normalized.includes("missing token")) {
    return "border-danger/40 bg-danger/10 text-danger";
  }
  if (normalized.startsWith("futu")) {
    return "border-accent-success/40 bg-accent-success/10 text-accent-success";
  }
  if (normalized.startsWith("tiingo")) {
    return "border-accent-success/40 bg-accent-success/10 text-accent-success";
  }
  if (normalized.startsWith("local")) {
    return "border-info/40 bg-info/10 text-info";
  }
  return "border-warning/40 bg-warning/10 text-warning";
}

function displaySource(source: string) {
  return source.toLowerCase().includes("sample") ? `${source} / not real` : source;
}

export function DataSourceBadge({ source }: DataSourceBadgeProps) {
  return (
    <span
      className={`rounded border px-2 py-1 font-data-mono text-[10px] uppercase ${badgeClass(source)}`}
      title={source}
    >
      {displaySource(source)}
    </span>
  );
}

const syntheticCopy = {
  en: "DEMO DATA — these metrics are synthetic (sample provider) and do not reflect real markets.",
  zh: "演示数据 — 以下指标来自合成的 sample 数据源，不代表真实行情。",
} as const;

/**
 * Prominent banner shown above headline metrics when the underlying run used the
 * synthetic `sample` provider. Sample runs can show impossible numbers (e.g.
 * Sharpe 30+), so the warning must be loud, not a small corner badge.
 */
export function SyntheticMetricsWarning({
  source,
  locale = "en",
}: {
  source: string | undefined | null;
  locale?: "en" | "zh";
}) {
  if (!isSampleSource(source)) {
    return null;
  }
  return (
    <div className="rounded border border-warning/50 bg-warning/10 px-3 py-2 font-body-sm font-semibold text-warning">
      ⚠️ {syntheticCopy[locale]}
    </div>
  );
}

