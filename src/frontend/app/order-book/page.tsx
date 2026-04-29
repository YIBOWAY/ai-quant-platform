import { BookOpen } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { getPredictionMarkets } from "@/lib/api";

export default async function OrderBookPage() {
  const predictionMarkets = await getPredictionMarkets();

  return (
    <div className="flex h-full flex-1 flex-col gap-4 overflow-y-auto p-container-padding text-zinc-400">
      <header className="rounded border border-danger/30 bg-danger/10 p-4">
        <div className="flex items-center gap-2 text-danger">
          <BookOpen size={18} />
          <h1 className="font-headline-lg text-text-primary">Prediction Market Order Books</h1>
        </div>
        <p className="mt-2 max-w-2xl font-body-sm text-text-secondary">
          Loaded {predictionMarkets.order_books.length} sample order books from the local API.
          Live Polymarket trading and signing remain disabled.
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
          </div>
        ))}
      </section>
      <EmptyState
        title="Scanner controls pending"
        description="P0-4 will add sample scan and dry-arbitrage buttons. No live key input will be shown."
      />
    </div>
  );
}
