import { BookOpen } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { PMRunForm } from "@/components/forms/PMRunForm";
import { getPredictionMarkets } from "@/lib/api";

export default async function OrderBookPage() {
  const predictionMarkets = await getPredictionMarkets();

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
          Polymarket support is research-only: no wallet signing, no live trading, no real orders.
        </p>
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
