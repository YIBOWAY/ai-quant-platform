import { BookOpen, ShieldOff } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { PMHistoryBacktestForm } from "@/components/forms/PMHistoryBacktestForm";
import { PredictionMarketDataControls } from "@/components/forms/PredictionMarketDataControls";
import { PMRunForm } from "@/components/forms/PMRunForm";
import { Card, MetricStat, PageHeader, SectionTitle, StatusPill } from "@/components/ui/primitives";
import { getPredictionMarkets } from "@/lib/api";
import { getServerLocale } from "@/lib/serverLocale";

type PolymarketPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

const copy = {
  en: {
    eyebrow: "Prediction Markets · Research",
    heading: "Polymarket Markets",
    sampleWarning:
      "Showing SAMPLE / 模拟数据 — these are not real markets. Switch the provider to Polymarket below to load read-only public market data.",
    disabledTitle: "Live integration intentionally disabled",
    disabledBody:
      "This page only runs read-only scans, dry proposals, and quasi-backtests. No signing, no live trading, no real orders. Sample data is illustrative only.",
    loaded: (count: number) =>
      `Loaded ${count} read-only order books from the local API.`,
    providerLabel: "provider",
    cacheLabel: "cache",
    marketsLabel: "markets",
    booksLabel: "order books",
    marketsTitle: "Order Books",
    marketsHint: "Best bid / ask per outcome token (read-only snapshot).",
    outcomes: "Outcomes",
    bid: "bid",
    ask: "ask",
    emptyTitle: "Live integration disabled",
    emptyDescription:
      "This page only runs read-only scans, dry proposals, and quasi-backtests.",
  },
  zh: {
    eyebrow: "预测市场 · 研究",
    heading: "Polymarket 市场",
    sampleWarning:
      "显示 模拟数据 / SAMPLE —— 这些不是真实市场。请在下方将数据源切换为 Polymarket，以加载只读的公开市场数据。",
    disabledTitle: "实盘集成已被有意禁用",
    disabledBody:
      "本页仅运行只读扫描、模拟提案和准回测。不签名、不实盘交易、不下真实订单。模拟数据仅作示意。",
    loaded: (count: number) => `已从本地 API 加载 ${count} 个只读盘口。`,
    providerLabel: "数据源",
    cacheLabel: "缓存",
    marketsLabel: "市场数",
    booksLabel: "盘口数",
    marketsTitle: "盘口",
    marketsHint: "每个结果代币的最优买价 / 卖价（只读快照）。",
    outcomes: "结果",
    bid: "买价",
    ask: "卖价",
    emptyTitle: "实盘集成已禁用",
    emptyDescription: "本页仅运行只读扫描、模拟提案和准回测。",
  },
} as const;

function single(value: string | string[] | undefined, fallback: string) {
  return typeof value === "string" && value.trim() ? value : fallback;
}

export default async function PolymarketPage({ searchParams }: PolymarketPageProps) {
  const params = (await searchParams) ?? {};
  const locale = await getServerLocale(params);
  const text = copy[locale];
  const provider = single(params.provider, "polymarket");
  const cacheMode = single(params.cache_mode, "prefer_cache");
  const limit = Number.parseInt(single(params.limit, "6"), 10);
  const predictionMarkets = await getPredictionMarkets(provider, cacheMode, limit);
  const isSample = predictionMarkets.provider === "sample";

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-container-padding">
      <ErrorBanner messages={[predictionMarkets.apiError]} />

      <PageHeader
        eyebrow={text.eyebrow}
        icon={<BookOpen size={20} className="text-text-secondary" />}
        title={text.heading}
        subtitle={text.loaded(predictionMarkets.order_books.length)}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill
              label={text.providerLabel}
              value={predictionMarkets.provider}
              tone={isSample ? "warning" : "success"}
            />
            <StatusPill
              label={text.cacheLabel}
              value={predictionMarkets.cache_status ?? "live"}
              tone="info"
            />
          </div>
        }
      />

      {/* Prominent, non-negotiable safety banner: live trading is off. */}
      <Card tone="danger" padded>
        <div className="flex items-start gap-3">
          <ShieldOff size={18} className="mt-0.5 shrink-0 text-danger" />
          <div>
            <h2 className="font-label-caps text-danger">{text.disabledTitle}</h2>
            <p className="mt-1 max-w-3xl font-body-sm text-text-secondary">
              {text.disabledBody}
            </p>
          </div>
        </div>
      </Card>

      {isSample ? (
        <Card tone="warning" padded={false}>
          <p className="p-3 font-body-sm text-warning">{text.sampleWarning}</p>
        </Card>
      ) : null}

      <Card padded>
        <PredictionMarketDataControls
          locale={locale}
          initial={{
            provider: provider === "sample" ? "sample" : "polymarket",
            cache_mode:
              cacheMode === "refresh" || cacheMode === "network_only"
                ? cacheMode
                : "prefer_cache",
            limit: String(Number.isFinite(limit) ? limit : 6),
          }}
        />
        <div className="mt-3 flex flex-wrap gap-2 border-t border-border-subtle pt-3">
          <MetricStat
            size="inline"
            label={text.marketsLabel}
            value={predictionMarkets.markets.length}
          />
          <MetricStat
            size="inline"
            label={text.booksLabel}
            value={predictionMarkets.order_books.length}
          />
        </div>
      </Card>

      {predictionMarkets.markets.length ? (
        <section>
          <SectionTitle title={text.marketsTitle} hint={text.marketsHint} />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
            {predictionMarkets.markets.map((market) => (
              <Card key={market.market_id} padded className="flex flex-col gap-3">
                <div>
                  <div className="font-data-mono text-[10px] uppercase text-text-secondary">
                    {market.market_id}
                  </div>
                  <h3 className="mt-1 font-body-md font-medium text-text-primary">
                    {market.question}
                  </h3>
                  <p className="mt-1 font-body-sm text-text-secondary">
                    <span className="font-label-caps text-[10px] uppercase">
                      {text.outcomes}
                    </span>{" "}
                    {market.outcomes.map((outcome) => outcome.name).join(", ")}
                  </p>
                </div>
                <div className="space-y-1.5">
                  {predictionMarkets.order_books
                    .filter((book) => book.market_id === market.market_id)
                    .slice(0, 4)
                    .map((book) => (
                      <div
                        key={book.token_id}
                        className="grid grid-cols-[1fr_auto_auto] items-center gap-2 rounded-lg border border-border-subtle bg-bg-surface-muted px-2 py-1.5 font-data-mono text-xs"
                      >
                        <span className="truncate text-text-secondary" title={book.token_id}>
                          {book.token_id.length > 13
                            ? `${book.token_id.slice(0, 6)}…${book.token_id.slice(-4)}`
                            : book.token_id}
                        </span>
                        <span className="text-accent-success">
                          {text.bid} {bestPrice(book.bids, "bid")}
                        </span>
                        <span className="text-warning">
                          {text.ask} {bestPrice(book.asks, "ask")}
                        </span>
                      </div>
                    ))}
                </div>
              </Card>
            ))}
          </div>
        </section>
      ) : (
        <EmptyState title={text.emptyTitle} description={text.emptyDescription} />
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <PMRunForm locale={locale} />
        <PMHistoryBacktestForm locale={locale} />
      </div>
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
