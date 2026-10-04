import Link from "next/link";
import { DataPreviewTable } from "@/components/DataPreviewTable";
import { ErrorBanner } from "@/components/ErrorBanner";
import { OptionsRadarSymbolLive } from "@/components/forms/OptionsRadarSymbolLive";
import { getOptionsDailyScanSymbol } from "@/lib/api";
import { optionsReasonLabel } from "@/lib/optionsErrorPresentation";
import { localizePath } from "@/lib/locale";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    eyebrow: "Options Recommendations",
    titleSuffix: "Recommendation Detail",
    intro: "Saved recommendations plus read-only live option chain checks.",
    back: "Back to Recommendations",
    tableTitle: "Saved Recommendations",
    tableDescription: (symbol: string, runDate?: string | null) =>
      `Latest saved recommendation rows for ${symbol}${runDate ? ` on ${runDate}` : ""}.`,
    emptyTitle: "No saved recommendations",
    emptyDescription:
      "No saved recommendation rows were found for this symbol. Wait for the next scheduled scan.",
    unavailableTitle: "Saved recommendations unavailable",
    unavailableDescription: "The saved snapshot cannot be used as recommendations.",
    provider: "Provider",
    reasons: "Reasons",
    coverage: "Coverage",
  },
  zh: {
    eyebrow: "期权推荐",
    titleSuffix: "推荐详情",
    intro: "已保存的推荐行，以及只读的实时期权链核对。",
    back: "返回期权推荐",
    tableTitle: "已保存推荐",
    tableDescription: (symbol: string, runDate?: string | null) =>
      `${symbol} 最近一次保存的推荐行${runDate ? `（${runDate}）` : ""}。`,
    emptyTitle: "暂无已保存推荐",
    emptyDescription: "该标的没有已保存的推荐行，请等待下一次定时扫描。",
    unavailableTitle: "已保存推荐不可用",
    unavailableDescription: "该快照不能作为推荐使用。",
    provider: "数据源",
    reasons: "原因",
    coverage: "扫描覆盖",
  },
} as const;

type OptionsRadarSymbolPageProps = {
  params?: Promise<{ symbol?: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function single(value: string | string[] | undefined, fallback = "") {
  return typeof value === "string" && value.trim() ? value : fallback;
}

export default async function OptionsRadarSymbolPage({
  params,
  searchParams,
}: OptionsRadarSymbolPageProps) {
  const locale = await getServerLocale();
  const text = copy[locale];
  const resolvedParams = (await params) ?? {};
  const resolvedSearch = (await searchParams) ?? {};
  const symbol = single(resolvedParams.symbol, "SPY").toUpperCase();
  const date = single(resolvedSearch.date);
  const expiry = single(resolvedSearch.expiry);
  const optionType = single(resolvedSearch.option_type, "ALL").toUpperCase();
  const radar = await getOptionsDailyScanSymbol(symbol, date || undefined);
  const unavailable = radar.status === "unavailable";
  const reasons = Object.entries(radar.shortfall_reasons ?? {})
    .map(([reason, count]) => `${optionsReasonLabel(reason, locale)}${count > 1 ? ` (${count})` : ""}`)
    .join(" · ");
  const rows = radar.candidates.map((candidate) => ({
    ticker: candidate.ticker,
    symbol: candidate.symbol,
    strategy: candidate.strategy,
    expiry: candidate.expiry,
    strike: candidate.strike,
    mid: candidate.mid,
    iv: candidate.implied_volatility,
    delta: candidate.delta,
    open_interest: candidate.open_interest,
    score: candidate.global_score,
  }));

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-bg-base p-5">
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4 border-b border-border-subtle pb-4">
        <div>
          <p className="font-label-caps uppercase text-text-secondary">{text.eyebrow}</p>
          <h1 className="mt-1 font-headline-xl text-text-primary">
            {symbol} {text.titleSuffix}
          </h1>
          <p className="mt-1 font-body-sm text-text-secondary">{text.intro}</p>
        </div>
        <Link
          className="rounded-lg border border-border-subtle px-3 py-2 font-body-sm text-text-primary transition-colors hover:bg-bg-surface-muted"
          href={localizePath("/options-radar", locale)}
        >
          {text.back}
        </Link>
      </header>
      <ErrorBanner messages={[radar.apiError]} />
      {unavailable ? (
        <section
          className="mb-4 rounded-lg border border-danger/40 bg-danger/10 p-4 font-body-sm text-danger"
          data-options-recommendation-unavailable
        >
          <h2 className="font-label-caps">{text.unavailableTitle}</h2>
          <p className="mt-1">{text.unavailableDescription}</p>
          <p className="mt-2 font-data-mono text-xs">
            {text.provider}: {radar.provider ?? "--"} · {text.coverage}: {radar.scanned_tickers}/
            {radar.universe_size} · {text.reasons}: {reasons || "--"}
          </p>
        </section>
      ) : null}
      <div className="grid min-w-0 gap-4 [&>*]:min-w-0 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <DataPreviewTable
          columns={["ticker", "symbol", "strategy", "expiry", "strike", "mid", "iv", "delta", "open_interest", "score"]}
          description={text.tableDescription(symbol, radar.run_date)}
          emptyDescription={
            unavailable ? text.unavailableDescription : text.emptyDescription
          }
          emptyTitle={unavailable ? text.unavailableTitle : text.emptyTitle}
          maxRows={20}
          rows={rows}
          title={text.tableTitle}
        />
        <OptionsRadarSymbolLive expiry={expiry} optionType={optionType} symbol={symbol} />
      </div>
    </div>
  );
}
