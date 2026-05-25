import Link from "next/link";
import { DataPreviewTable } from "@/components/DataPreviewTable";
import { ErrorBanner } from "@/components/ErrorBanner";
import { OptionsRadarSymbolLive } from "@/components/forms/OptionsRadarSymbolLive";
import { getOptionsRadarSymbol } from "@/lib/api";

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
  const resolvedParams = (await params) ?? {};
  const resolvedSearch = (await searchParams) ?? {};
  const symbol = single(resolvedParams.symbol, "SPY").toUpperCase();
  const date = single(resolvedSearch.date);
  const expiry = single(resolvedSearch.expiry);
  const optionType = single(resolvedSearch.option_type, "ALL").toUpperCase();
  const radar = await getOptionsRadarSymbol(symbol, date || undefined);
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
          <p className="font-label-caps uppercase text-text-secondary">Options Radar</p>
          <h1 className="mt-1 font-headline-xl text-text-primary">{symbol} Options Detail</h1>
          <p className="mt-1 font-body-sm text-text-secondary">
            Snapshot candidates plus read-only live option chain checks.
          </p>
        </div>
        <Link className="rounded border border-border-subtle px-3 py-2 font-body-sm text-text-primary" href="/options-radar">
          Back to Radar
        </Link>
      </header>
      <ErrorBanner messages={[radar.apiError]} />
      <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
        <DataPreviewTable
          columns={["ticker", "symbol", "strategy", "expiry", "strike", "mid", "iv", "delta", "open_interest", "score", "rating"]}
          description={`Latest saved Radar rows for ${symbol}${radar.run_date ? ` on ${radar.run_date}` : ""}.`}
          emptyDescription="No saved Radar rows were found for this symbol. Run a scan from the Radar page first."
          emptyTitle="No Radar candidates"
          maxRows={20}
          rows={rows}
          title="Radar Candidates"
        />
        <OptionsRadarSymbolLive expiry={expiry} optionType={optionType} symbol={symbol} />
      </div>
    </div>
  );
}
