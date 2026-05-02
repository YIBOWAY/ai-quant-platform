import { CandlestickChart } from "@/components/CandlestickChart";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { DataExplorerControls } from "@/components/forms/DataExplorerControls";
import { getMarketDataHistory, getSymbols } from "@/lib/api";

type DataExplorerProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function single(value: string | string[] | undefined, fallback: string) {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function paramsWithLang(params: Record<string, string | string[] | undefined>, lang: string) {
  const normalized = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (typeof value === "string") {
      normalized.set(key, value);
    }
  });
  normalized.set("lang", lang);
  return `/data-explorer?${normalized.toString()}`;
}

export default async function DataExplorer({ searchParams }: DataExplorerProps) {
  const params = (await searchParams) ?? {};
  const locale = single(params.lang, "en") === "zh" ? "zh" : "en";
  const text =
    locale === "zh"
      ? {
          currency: "美元",
          rawData: "原始行情",
          timestamp: "时间",
          open: "开盘",
          high: "最高",
          low: "最低",
          close: "收盘",
          volume: "成交量",
          quality: "数据质量",
          fetchedAt: "获取时间",
          chartTitle: "历史 K 线",
          chartHint: "真实 OHLCV K 线。长区间只显示少量时间刻度，避免横轴拥挤。",
          noRows: "没有行情数据",
          noRowsDescription: "后端没有返回这个标的和时间范围的数据。",
          qualityTitle: "质量报告未接入",
          qualityDescription: "覆盖率、缺失交易日和异常检测等待 /api/data/quality。",
          auditTitle: "详细审计日志不可用",
          auditDescription: "数据审计时间线计划在后续阶段接入。",
          languageLabel: "English",
          languageHref: paramsWithLang(params, "en"),
        }
      : {
          currency: "USD",
          rawData: "Raw Data Feed",
          timestamp: "TIMESTAMP (UTC)",
          open: "OPEN",
          high: "HIGH",
          low: "LOW",
          close: "CLOSE",
          volume: "VOLUME",
          quality: "Data Quality Metrics",
          fetchedAt: "Fetched At",
          chartTitle: "Historical K-Line",
          chartHint: "Real OHLCV candlesticks. Long ranges show sparse axis ticks to keep the chart readable.",
          noRows: "No OHLCV rows",
          noRowsDescription: "The backend returned no rows for the selected symbol and range.",
          qualityTitle: "Quality report not connected",
          qualityDescription: "Coverage, missing-day and anomaly checks are waiting for /api/data/quality.",
          auditTitle: "Detailed audit log unavailable",
          auditDescription: "Data audit timelines are scheduled in FIX_PLAN P2-5.",
          languageLabel: "中文",
          languageHref: paramsWithLang(params, "zh"),
        };
  const symbol = single(params.symbol, "SPY").toUpperCase();
  const start = single(params.start, "2024-01-02");
  const end = single(params.end, "2024-01-12");
  const freq = single(params.freq, "1d");
  const provider = single(params.provider, "futu");
  const [symbols, ohlcv] = await Promise.all([
    getSymbols(),
    getMarketDataHistory(symbol, start, end, freq, provider),
  ]);
  const latest = ohlcv.rows.at(-1);

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <div className="flex-none border-b border-border-subtle bg-bg-surface p-4">
        <ErrorBanner messages={[symbols.apiError, ohlcv.apiError]} />
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
              provider: provider === "sample" || provider === "tiingo" ? provider : "futu",
            }}
            locale={locale}
          />

          <div className="flex items-center gap-3">
            <DataSourceBadge source={ohlcv.source} />
            <span className="font-data-mono text-[10px] uppercase text-text-secondary">
              rows: {ohlcv.rows.length}
            </span>
            <span className="font-data-mono text-[10px] uppercase text-text-secondary">
              freq: {ohlcv.frequency}
            </span>
            <a className="font-body-sm text-info" href={text.languageHref}>
              {text.languageLabel}
            </a>
          </div>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div className="flex flex-1 flex-col border-r border-border-subtle">
          <div className="flex-1 bg-surface p-4">
            <div className="mb-4 flex items-start justify-between">
              <div>
                <div className="flex items-baseline gap-2 font-headline-lg text-text-primary">
                  {ohlcv.symbol} <span className="font-data-mono text-data-mono text-text-secondary">{text.currency}</span>
                </div>
                <div className="mt-1 flex gap-4 font-data-mono text-data-mono">
                  <span className="text-accent-success">O: {latest?.open.toFixed(2) ?? "--"}</span>
                  <span className="text-accent-success">H: {latest?.high.toFixed(2) ?? "--"}</span>
                  <span className="text-danger">L: {latest?.low.toFixed(2) ?? "--"}</span>
                  <span className="text-text-primary">C: {latest?.close.toFixed(2) ?? "--"}</span>
                </div>
              </div>
            </div>

            {ohlcv.rows.length ? (
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <div>
                    <h2 className="font-label-caps uppercase text-text-secondary">{text.chartTitle}</h2>
                    <p className="font-body-sm text-text-secondary">{text.chartHint}</p>
                  </div>
                  <DataSourceBadge source={ohlcv.source} />
                </div>
                <CandlestickChart rows={ohlcv.rows} />
              </div>
            ) : (
              <EmptyState
                title={text.noRows}
                description={text.noRowsDescription}
              />
            )}
          </div>

          <div className="h-1/3 border-t border-border-subtle bg-bg-surface">
            <div className="flex items-center justify-between border-b border-border-subtle bg-surface-container-low px-4 py-2">
              <span className="font-label-caps uppercase text-text-secondary">{text.rawData}</span>
              <DataSourceBadge source={ohlcv.source} />
            </div>
            <div className="h-[calc(100%-41px)] overflow-auto p-4">
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
                <tbody className="font-data-mono text-data-mono text-text-primary">
                  {ohlcv.rows.map((row) => (
                    <tr
                      className="border-b border-border-subtle/50 hover:bg-surface-muted"
                      key={row.timestamp}
                    >
                      <td className="py-2">{row.timestamp}</td>
                      <td className="py-2 text-right">{row.open.toFixed(2)}</td>
                      <td className="py-2 text-right">{row.high.toFixed(2)}</td>
                      <td className="py-2 text-right">{row.low.toFixed(2)}</td>
                      <td className="py-2 text-right text-accent-success">{row.close.toFixed(2)}</td>
                      <td className="py-2 text-right text-text-secondary">
                        {row.volume.toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="flex w-[300px] flex-col gap-4 overflow-y-auto bg-bg-surface p-4">
          <h3 className="font-label-caps uppercase text-text-secondary">{text.quality}</h3>
          <div className="rounded border border-border-subtle bg-surface-muted p-3">
            <div className="font-label-caps text-text-secondary">{text.fetchedAt}</div>
            <div className="mt-2 break-all font-data-mono text-[11px] text-text-primary">
              {ohlcv.metadata.fetched_at ?? "--"}
            </div>
          </div>
          <EmptyState
            title={text.qualityTitle}
            description={text.qualityDescription}
          />
          <EmptyState
            title={text.auditTitle}
            description={text.auditDescription}
          />
        </div>
      </div>
    </div>
  );
}
