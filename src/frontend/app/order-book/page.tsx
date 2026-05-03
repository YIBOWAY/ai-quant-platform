import { BookOpen } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { PMHistoryBacktestForm } from "@/components/forms/PMHistoryBacktestForm";
import { PredictionMarketDataControls } from "@/components/forms/PredictionMarketDataControls";
import { PMRunForm } from "@/components/forms/PMRunForm";
import { getPredictionMarkets } from "@/lib/api";

type OrderBookPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function single(value: string | string[] | undefined, fallback: string) {
  return typeof value === "string" && value.trim() ? value : fallback;
}

export default async function OrderBookPage({ searchParams }: OrderBookPageProps) {
  const params = (await searchParams) ?? {};
  const provider = single(params.provider, "sample");
  const cacheMode = single(params.cache_mode, "prefer_cache");
  const limit = Number.parseInt(single(params.limit, "6"), 10);
  const predictionMarkets = await getPredictionMarkets(provider, cacheMode, limit);

  return (
    <div className="flex h-full flex-1 flex-col gap-4 overflow-y-auto p-container-padding text-zinc-400">
      <ErrorBanner messages={[predictionMarkets.apiError]} />
      <header className="rounded border border-danger/30 bg-danger/10 p-4">
        <div className="flex items-center gap-2 text-danger">
          <BookOpen size={18} />
          <h1 className="font-headline-lg text-text-primary">Prediction Market Order Books</h1>
        </div>
        <p className="mt-2 max-w-2xl font-body-sm text-text-secondary">
          Loaded {predictionMarkets.order_books.length} read-only order books from the local API.
          Polymarket support is research-only: no signing, no live trading, no real orders.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <PredictionMarketDataControls
            initial={{
              provider:
                provider === "polymarket" ? "polymarket" : "sample",
              cache_mode:
                cacheMode === "refresh" || cacheMode === "network_only"
                  ? cacheMode
                  : "prefer_cache",
              limit: String(Number.isFinite(limit) ? limit : 6),
            }}
          />
          <span className="font-data-mono text-[10px] uppercase text-text-secondary">
            provider: {predictionMarkets.provider}
          </span>
          <span className="font-data-mono text-[10px] uppercase text-text-secondary">
            cache: {predictionMarkets.cache_status ?? "live"}
          </span>
        </div>
      </header>
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {predictionMarkets.markets.map((market) => (
          <div key={market.market_id} className="rounded border border-border-subtle bg-bg-surface p-4">
            <div className="font-data-mono text-[10px] uppercase text-text-secondary">
              {market.market_id}
            </div>
            <h2 className="mt-2 font-body-md font-medium text-text-primary">{market.question}</h2>
            <p className="mt-2 font-body-sm text-text-secondary">
              Outcomes: {market.outcomes.map((outcome) => outcome.name).join(", ")}
            </p>
            <div className="mt-3 space-y-2">
              {predictionMarkets.order_books
                .filter((book) => book.market_id === market.market_id)
                .slice(0, 4)
                .map((book) => (
                  <div key={book.token_id} className="grid grid-cols-3 gap-2 rounded border border-border-subtle bg-surface-muted p-2 font-data-mono text-xs">
                    <span className="truncate text-text-secondary">{book.token_id}</span>
                    <span className="text-accent-success">bid {bestPrice(book.bids, "bid")}</span>
                    <span className="text-warning">ask {bestPrice(book.asks, "ask")}</span>
                  </div>
                ))}
            </div>
          </div>
        ))}
      </section>
      <PMRunForm />
      <PMHistoryBacktestForm />
      <EmptyState
        title="Live integration disabled"
        description="This page only runs read-only scans, dry proposals, and quasi-backtests."
      />
    </div>
  );
}

function bestPrice(rows: Array<{ price?: number }>, side: "bid" | "ask") {
  const prices = rows.map((row) => row.price).filter((price): price is number => typeof price === "number");
  if (!prices.length) {
    return "--";
  }
  return (side === "bid" ? Math.max(...prices) : Math.min(...prices)).toFixed(3);
}
