import { BookOpen } from "lucide-react";
import { getPredictionMarkets } from "@/lib/api";

export default async function OrderBookPage() {
  const predictionMarkets = await getPredictionMarkets();

  return (
    <div className="flex-1 flex flex-col items-center justify-center h-full min-h-[50vh] text-zinc-400">
      <BookOpen size={48} className="mb-4 text-zinc-600" />
      <h2 className="text-xl font-semibold mb-2 font-sans tracking-tight text-zinc-200">Order Book</h2>
      <p className="text-sm font-sans max-w-md text-center">
        Loaded {predictionMarkets.order_books.length} sample order books from the Phase 9 API.
        Live Polymarket trading and signing remain disabled.
      </p>
    </div>
  );
}
