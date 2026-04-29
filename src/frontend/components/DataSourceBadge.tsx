type DataSourceBadgeProps = {
  source: string;
};

function badgeClass(source: string) {
  const normalized = source.toLowerCase();
  if (normalized.includes("failed") || normalized.includes("missing token")) {
    return "border-danger/40 bg-danger/10 text-danger";
  }
  if (normalized.startsWith("tiingo")) {
    return "border-accent-success/40 bg-accent-success/10 text-accent-success";
  }
  if (normalized.startsWith("local")) {
    return "border-info/40 bg-info/10 text-info";
  }
  return "border-warning/40 bg-warning/10 text-warning";
}

export function DataSourceBadge({ source }: DataSourceBadgeProps) {
  return (
    <span
      className={`rounded border px-2 py-1 font-data-mono text-[10px] uppercase ${badgeClass(source)}`}
      title={source}
    >
      {source}
    </span>
  );
}
