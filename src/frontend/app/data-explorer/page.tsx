import { Database } from "lucide-react";
import { CandlestickChart } from "@/components/CandlestickChart";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { DataExplorerControls } from "@/components/forms/DataExplorerControls";
import { getMarketDataHistory, getSymbols, type OhlcvRow } from "@/lib/api";
import { getServerLocale } from "@/lib/serverLocale";

type DataExplorerProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function single(value: string | string[] | undefined, fallback: string) {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function isoDate(date: Date) {
  return date.toISOString().slice(0, 10);
}

function defaultRange(days = 60) {
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - days);
  return { start: isoDate(start), end: isoDate(end) };
}

const copy = {
  en: {
    eyebrow: "Research",
    title: "Data Explorer",
    subtitle: "Inspect real OHLCV history for any symbol and verify data quality before research runs.",
    currency: "USD",
    rawData: "Raw Data Feed",
    rawDataHint: "Newest first.",
    timestamp: "Timestamp (UTC)",
    open: "Open",
    high: "High",
    low: "Low",
    close: "Close",
    volume: "Volume",
    quality: "Data Quality",
    fetchedAt: "Fetched at",
    rowsReturned: "Rows returned",
    range: "Range",
    missingWeekdays: "Missing weekdays (incl. holidays)",
    invalidFields: "Invalid numeric fields",
    chartTitle: "Historical K-Line",
    lastClose: "Last close",
    asOf: "as of",
    noRows: "No OHLCV rows",
    noRowsDescription:
      "The backend returned no rows for this symbol and range. Check the ticker, widen the dates, or switch the data source (futu requires OpenD online).",
    showingRows: (n: number, total: number) => `showing ${n}/${total}`,
  },
  zh: {
    eyebrow: "研究",
    title: "行情浏览",
    subtitle: "查看任意标的的真实 OHLCV 历史，在研究运行前核对数据源质量。",
    currency: "美元",
    rawData: "原始行情",
    rawDataHint: "按时间倒序。",
    timestamp: "时间 (UTC)",
    open: "开盘",
    high: "最高",
    low: "最低",
    close: "收盘",
    volume: "成交量",
    quality: "数据质量",
    fetchedAt: "获取时间",
    rowsReturned: "返回行数",
    range: "数据区间",
    missingWeekdays: "缺失工作日（含节假日）",
    invalidFields: "异常数值字段",
    chartTitle: "历史 K 线",
    lastClose: "最新收盘",
    asOf: "截至",
    noRows: "没有行情数据",
    noRowsDescription:
      "后端没有返回这个标的和时间范围的数据。请检查代码拼写、放宽日期范围，或切换数据源（futu 需要 OpenD 在线）。",
    showingRows: (n: number, total: number) => `显示 ${n}/${total} 行`,
  },
} as const;

const MAX_TABLE_ROWS = 120;

export default async function DataExplorer({ searchParams }: DataExplorerProps) {
  const params = (await searchParams) ?? {};
  const locale = await getServerLocale(params);
  const text = copy[locale];
  const symbol = single(params.symbol, "SPY").toUpperCase();
  const fallbackRange = defaultRange(60);
  const start = single(params.start, fallbackRange.start);
  const end = single(params.end, fallbackRange.end);
  const freq = single(params.freq, "1d");
  const requestedProvider = single(params.provider, "").toLowerCase();
  const provider =
    requestedProvider === "sample" || requestedProvider === "futu" || requestedProvider === "tiingo"
      ? requestedProvider
      : undefined;
  const [symbols, ohlcv] = await Promise.all([
    getSymbols(),
    getMarketDataHistory(symbol, start, end, freq, provider),
  ]);
  const latest = ohlcv.rows.at(-1);
  const previous = ohlcv.rows.at(-2);
  const change = latest && previous ? latest.close - previous.close : null;
  const changePct = change !== null && previous ? (change / previous.close) * 100 : null;
  const changePositive = (change ?? 0) >= 0;
  const qualitySummary = summarizeHistoryQuality(ohlcv.rows, ohlcv.frequency);
  const activeProvider = ohlcv.metadata.requested_provider;
  const initialProvider =
    activeProvider === "sample" || activeProvider === "tiingo" ? activeProvider : "futu";
  const hasRows = ohlcv.rows.length > 0;
  const tableRows = [...ohlcv.rows].reverse().slice(0, MAX_TABLE_ROWS);

  return (
    <div
      className="flex h-full w-full flex-col overflow-x-hidden overflow-y-auto"
      data-testid="data-explorer-scroll-region"
    >
      <div className="flex-none border-b border-border-subtle bg-bg-surface p-4">
        <ErrorBanner locale={locale} messages={[symbols.apiError, ohlcv.apiError]} />
        <div className="mb-3 flex items-center gap-2">
          <Database size={16} className="text-accent-success" />
          <div>
            <span className="font-label-caps uppercase text-text-secondary">{text.eyebrow}</span>
            <h1 className="font-headline-lg text-text-primary">{text.title}</h1>
          </div>
          <p className="ml-4 hidden font-body-sm text-text-secondary xl:block">{text.subtitle}</p>
        </div>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <DataExplorerControls
            symbols={symbols.symbols}
            initial={{
              symbol: ohlcv.symbol || symbol,
              start,
              end,
              freq:
                freq === "1h" || freq === "30m" || freq === "15m" || freq === "5m" || freq === "1m"
                  ? freq
                  : "1d",
              provider: initialProvider,
            }}
            locale={locale}
          />
          <div className="flex items-center gap-3">
            <DataSourceBadge source={ohlcv.source} />
            <span className="font-data-mono text-[10px] uppercase text-text-secondary">
              {text.rowsReturned}: {qualitySummary.rowCount} · freq: {ohlcv.frequency}
            </span>
          </div>
        </div>
      </div>

      {hasRows ? (
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="flex flex-1 flex-col bg-bg-base p-4">
            <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
              <div className="flex items-baseline gap-3">
                <span className="font-headline-xl text-text-primary">{ohlcv.symbol}</span>
                <span className="font-data-mono text-text-secondary">{text.currency}</span>
                {latest ? (
                  <>
                    <span className="font-data-mono text-xl font-bold tabular-nums text-text-primary">
                      {latest.close.toFixed(2)}
                    </span>
                    {change !== null && changePct !== null ? (
                      <span
                        className={`font-data-mono tabular-nums ${changePositive ? "text-accent-success" : "text-danger"}`}
                      >
                        {changePositive ? "+" : ""}
                        {change.toFixed(2)} ({changePositive ? "+" : ""}
                        {changePct.toFixed(2)}%)
                      </span>
                    ) : null}
                    <span className="font-data-mono text-[11px] text-text-secondary">
                      {text.asOf} {latest.timestamp.slice(0, 10)}
                    </span>
                  </>
                ) : null}
              </div>
              {latest ? (
                <div className="flex gap-4 font-data-mono text-xs tabular-nums text-text-secondary">
                  <span>O {latest.open.toFixed(2)}</span>
                  <span>H {latest.high.toFixed(2)}</span>
                  <span>L {latest.low.toFixed(2)}</span>
                  <span>V {latest.volume.toLocaleString()}</span>
                </div>
              ) : null}
            </div>
            <div className="min-h-[290px] flex-1">
              <CandlestickChart locale={locale} rows={ohlcv.rows} />
            </div>
          </div>

          <div className="flex h-[280px] shrink-0 flex-col border-t border-border-subtle bg-bg-surface">
            <div className="flex shrink-0 items-center justify-between border-b border-border-subtle bg-bg-surface-muted/40 px-4 py-2">
              <span className="font-label-caps uppercase text-text-secondary">
                {text.rawData} <span className="normal-case opacity-70">· {text.rawDataHint}</span>
              </span>
              <div className="flex items-center gap-4">
                <span className="font-data-mono text-[10px] text-text-secondary">
                  {text.showingRows(tableRows.length, ohlcv.rows.length)}
                </span>
                <QualityStrip locale={locale} summary={qualitySummary} fetchedAt={ohlcv.metadata.fetched_at} />
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-auto p-4">
              <table className="w-full border-collapse text-left">
                <thead>
                  <tr className="border-b border-border-subtle">
                    <th className="pb-2 font-label-caps text-text-secondary">{text.timestamp}</th>
                    <th className="pb-2 text-right font-label-caps text-text-secondary">{text.open}</th>
                    <th className="pb-2 text-right font-label-caps text-text-secondary">{text.high}</th>
                    <th className="pb-2 text-right font-label-caps text-text-secondary">{text.low}</th>
                    <th className="pb-2 text-right font-label-caps text-text-secondary">{text.close}</th>
                    <th className="pb-2 text-right font-label-caps text-text-secondary">{text.volume}</th>
                  </tr>
                </thead>
                <tbody className="font-data-mono text-xs tabular-nums text-text-primary">
                  {tableRows.map((row) => {
                    const up = row.close >= row.open;
                    return (
                      <tr
                        className="border-b border-border-subtle/50 transition-colors hover:bg-bg-surface-muted"
                        key={row.timestamp}
                      >
                        <td className="py-1.5">{formatRowTimestamp(row.timestamp, ohlcv.frequency)}</td>
                        <td className="py-1.5 text-right">{row.open.toFixed(2)}</td>
                        <td className="py-1.5 text-right">{row.high.toFixed(2)}</td>
                        <td className="py-1.5 text-right">{row.low.toFixed(2)}</td>
                        <td className={`py-1.5 text-right ${up ? "text-accent-success" : "text-danger"}`}>
                          {row.close.toFixed(2)}
                        </td>
                        <td className="py-1.5 text-right text-text-secondary">
                          {row.volume.toLocaleString()}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 place-items-center bg-bg-base p-8">
          <EmptyState title={text.noRows} description={text.noRowsDescription} />
        </div>
      )}
    </div>
  );
}

function QualityStrip({
  locale,
  summary,
  fetchedAt,
}: {
  locale: "en" | "zh";
  summary: ReturnType<typeof summarizeHistoryQuality>;
  fetchedAt?: string | null;
}) {
  const text = copy[locale];
  const items: Array<[string, string]> = [
    [text.range, summary.rowCount ? `${summary.firstTimestamp.slice(0, 10)} → ${summary.lastTimestamp.slice(0, 10)}` : "--"],
    [text.missingWeekdays, String(summary.estimatedMissingWeekdays)],
    [text.invalidFields, String(summary.invalidNumericFields)],
    [text.fetchedAt, fetchedAt ? fetchedAt.slice(0, 19).replace("T", " ") : "--"],
  ];
  return (
    <div className="hidden items-center gap-4 lg:flex">
      {items.map(([label, value]) => (
        <span className="font-data-mono text-[10px] text-text-secondary" key={label} title={label}>
          <span className="opacity-70">{label}:</span> {value}
        </span>
      ))}
    </div>
  );
}

function formatRowTimestamp(timestamp: string, frequency: string) {
  if (frequency === "1d") {
    return timestamp.slice(0, 10);
  }
  return timestamp.slice(0, 16).replace("T", " ");
}

function summarizeHistoryQuality(rows: OhlcvRow[], frequency: string) {
  const firstTimestamp = rows[0]?.timestamp ?? "--";
  const lastTimestamp = rows.at(-1)?.timestamp ?? "--";
  const estimatedMissingWeekdays =
    frequency === "1d" && rows.length
      ? Math.max(0, countWeekdays(firstTimestamp, lastTimestamp) - rows.length)
      : 0;
  const invalidNumericFields = rows.reduce((count, row) => {
    return (
      count +
      [row.open, row.high, row.low, row.close, row.volume].filter(
        (value) => !Number.isFinite(value),
      ).length
    );
  }, 0);
  return {
    rowCount: rows.length,
    firstTimestamp,
    lastTimestamp,
    estimatedMissingWeekdays,
    invalidNumericFields,
  };
}

function countWeekdays(start: string, end: string) {
  const current = new Date(start);
  const final = new Date(end);
  if (Number.isNaN(current.valueOf()) || Number.isNaN(final.valueOf())) {
    return 0;
  }
  let count = 0;
  while (current <= final) {
    const day = current.getUTCDay();
    if (day !== 0 && day !== 6) {
      count += 1;
    }
    current.setUTCDate(current.getUTCDate() + 1);
  }
  return count;
}
