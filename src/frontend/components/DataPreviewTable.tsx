import { EmptyState } from "@/components/EmptyState";
import type { PreviewRecord } from "@/lib/api";

type DataPreviewTableProps = {
  title: string;
  description: string;
  rows: PreviewRecord[];
  emptyTitle: string;
  emptyDescription: string;
  maxRows?: number;
  columns?: string[];
  /** Optional display names per raw column key, e.g. { avg_cost: "均价" }. */
  columnLabels?: Record<string, string>;
  /** Optional hover explanations per raw column key. */
  columnTips?: Record<string, string>;
  /** Localizes table chrome ("showing N/M"). Defaults to en. */
  locale?: "en" | "zh";
};

function formatValue(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return "--";
  }
  if (typeof value === "number") {
    if (value === 0) {
      return "0";
    }
    return Number.isFinite(value) ? value.toFixed(Math.abs(value) >= 100 ? 2 : 4) : "--";
  }
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value);
}

export function DataPreviewTable({
  title,
  description,
  rows,
  emptyTitle,
  emptyDescription,
  maxRows = 10,
  columns,
  columnLabels,
  columnTips,
  locale = "en",
}: DataPreviewTableProps) {
  if (!rows.length) {
    return <EmptyState title={emptyTitle} description={emptyDescription} />;
  }

  const visibleRows = rows.slice(0, maxRows);
  const resolvedColumns =
    columns ?? Array.from(new Set(visibleRows.flatMap((row) => Object.keys(row))));
  // Right-align numeric columns (sampled from the first row carrying a value).
  const numericColumns = new Set(
    resolvedColumns.filter((column) =>
      visibleRows.some((row) => typeof row[column] === "number"),
    ),
  );
  const counter =
    locale === "zh"
      ? `显示 ${visibleRows.length} / ${rows.length} 行`
      : `showing ${visibleRows.length}/${rows.length}`;

  return (
    <section className="rounded-lg border border-border-subtle bg-bg-surface p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h3 className="font-label-caps text-text-primary">{title}</h3>
          <p className="mt-1 font-body-sm text-text-secondary">{description}</p>
        </div>
        <span className="shrink-0 font-data-mono text-[10px] uppercase text-text-secondary">
          {counter}
        </span>
      </div>
      <div className="overflow-auto">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="border-b border-border-subtle">
              {resolvedColumns.map((column) => (
                <th
                  key={column}
                  className={`pb-2 pr-3 font-label-caps text-text-secondary ${
                    numericColumns.has(column) ? "text-right" : ""
                  } ${columnTips?.[column] ? "cursor-help underline decoration-dotted decoration-border-subtle underline-offset-4" : ""}`}
                  title={columnTips?.[column]}
                >
                  {columnLabels?.[column] ?? column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="font-data-mono text-xs text-text-primary">
            {visibleRows.map((row, index) => (
              <tr key={`${title}-${index}`} className="border-b border-border-subtle/40">
                {resolvedColumns.map((column) => (
                  <td
                    key={`${title}-${index}-${column}`}
                    className={`py-2 pr-3 align-top ${numericColumns.has(column) ? "text-right" : ""}`}
                  >
                    <span
                      className={`block max-w-56 truncate ${numericColumns.has(column) ? "tabular-nums" : ""}`}
                      title={formatValue(row[column])}
                    >
                      {formatValue(row[column])}
                    </span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
