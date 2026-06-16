import Link from "next/link";
import { DataPreviewTable } from "@/components/DataPreviewTable";
import { ErrorBanner } from "@/components/ErrorBanner";
import { OptionsRadarSymbolLive } from "@/components/forms/OptionsRadarSymbolLive";
import { getOptionsDailyScanSymbol } from "@/lib/api";
import { localizePath } from "@/lib/locale";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    eyebrow: "Options Radar",
    titleSuffix: "Options Detail",
    intro: "Snapshot candidates plus read-only live option chain checks.",
    back: "Back to Radar",
    tableTitle: "Radar Candidates",
    tableDescription: (symbol: string, runDate?: string | null) =>
      `Latest saved Radar rows for ${symbol}${runDate ? ` on ${runDate}` : ""}.`,
    emptyTitle: "No Radar candidates",
    emptyDescription:
      "No saved Radar rows were found for this symbol. Run a scan from the Radar page first.",
  },
  zh: {
    eyebrow: "期权雷达",
    titleSuffix: "期权明细",
    intro: "已保存的雷达候选行,以及只读的实时期权链核对。",
    back: "返回雷达",
    tableTitle: "雷达候选",
    tableDescription: (symbol: string, runDate?: string | null) =>
      `${symbol} 最近一次保存的雷达行${runDate ? `(${runDate})` : ""}。`,
    emptyTitle: "暂无雷达候选",
    emptyDescription: "该标的没有已保存的雷达行,请先在雷达页运行一次扫描。",
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
    rating: candidate.rating,
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
      <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
        <DataPreviewTable
          columns={["ticker", "symbol", "strategy", "expiry", "strike", "mid", "iv", "delta", "open_interest", "score", "rating"]}
          description={text.tableDescription(symbol, radar.run_date)}
          emptyDescription={text.emptyDescription}
          emptyTitle={text.emptyTitle}
          maxRows={20}
          rows={rows}
          title={text.tableTitle}
        />
        <OptionsRadarSymbolLive expiry={expiry} optionType={optionType} symbol={symbol} />
      </div>
    </div>
  );
}
