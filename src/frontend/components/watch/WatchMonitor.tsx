import Link from "next/link";
import { AsiaRadarView } from "@/components/asia-radar/AsiaRadarDashboard";
import { MarketCrossSectionView } from "@/components/market-cross-section/MarketCrossSectionDashboard";
import { DataExplorerView } from "@/components/watch/DataExplorerView";
import type { Locale } from "@/lib/locale";
import {
  parseWatchBasket,
  parseWatchPane,
  WATCH_PANE_LABELS,
  WATCH_PANES,
  watchHref,
  type WatchPane,
} from "@/lib/watchPanes";

export async function WatchMonitor({
  locale,
  pane,
  params = {},
}: {
  locale: Locale;
  pane?: WatchPane;
  params?: Record<string, string | string[] | undefined>;
}) {
  const active = pane ?? parseWatchPane(params.pane ?? (params.symbol ? "quotes" : undefined));
  const quotes = active === "quotes" ? await DataExplorerView({ locale, params }) : null;
  const initialBasket = parseWatchBasket(params.basket);

  return (
    <div className="flex h-full min-h-0 w-full flex-col bg-bg-base" data-testid="watch-monitor">
      <nav
        aria-label={locale === "zh" ? "市场研判" : "Market Outlook"}
        className="flex shrink-0 flex-wrap gap-1 border-b border-border-subtle px-4 py-3 lg:px-8"
      >
        {WATCH_PANES.map((id) => {
          const label = WATCH_PANE_LABELS[id][locale];
          const current = id === active;
          return (
            <Link
              key={id}
              prefetch={false}
              aria-current={current ? "page" : undefined}
              className={`app-touch-target inline-flex items-center rounded-md px-4 font-sans text-[13px] ${
                current
                  ? "bg-warning/10 font-semibold text-warning"
                  : id === "quotes" ? "ml-auto text-text-secondary hover:text-text-primary" : "text-text-secondary hover:bg-bg-sidebar-muted hover:text-text-primary"
              }`}
              data-watch-pane={id}
              href={watchHref(id, locale, params)}
            >
              {label}
            </Link>
          );
        })}
      </nav>
      <div className="min-h-0 flex-1 overflow-hidden">
        {active === "quotes" ? <section
          className="h-full min-h-0 overflow-hidden"
          data-watch-capability={WATCH_PANE_LABELS.quotes[locale]}
        >
          {quotes}
        </section> : null}
        {active === "cross" ? <section
          className="h-full min-h-0 overflow-hidden"
          data-watch-capability={WATCH_PANE_LABELS.cross[locale]}
        >
          <MarketCrossSectionView initialBasket={initialBasket} locale={locale} />
        </section> : null}
        {active === "radar" ? <section
          className="h-full min-h-0 overflow-hidden"
          data-watch-capability={WATCH_PANE_LABELS.radar[locale]}
        >
          <AsiaRadarView locale={locale} />
        </section> : null}
      </div>
    </div>
  );
}
