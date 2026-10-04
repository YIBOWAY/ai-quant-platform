export const WATCH_PANES = ["cross", "radar", "quotes"] as const;

export type WatchPane = (typeof WATCH_PANES)[number];

export const WATCH_PANE_LABELS = {
  quotes: { en: "Symbol Charts", zh: "个股行情" },
  cross: { en: "US Risk", zh: "美股风险" },
  radar: { en: "Asia Valuation", zh: "亚洲泡沫" },
} as const;

export const WATCH_PANE_ALIASES: Record<string, WatchPane> = {
  quotes: "quotes",
  explorer: "quotes",
  "data-explorer": "quotes",
  cross: "cross",
  "cross-section": "cross",
  "market-cross-section": "cross",
  radar: "radar",
  "asia-radar": "radar",
};

export const WATCH_BASKETS = ["ai_watch", "us_sectors"] as const;

export type WatchBasket = (typeof WATCH_BASKETS)[number];

export function parseWatchPane(value: unknown): WatchPane {
  const raw = Array.isArray(value) ? value[0] : value;
  if (typeof raw === "string" && raw in WATCH_PANE_ALIASES) {
    return WATCH_PANE_ALIASES[raw];
  }
  return "cross";
}

export function parseWatchBasket(value: unknown): WatchBasket | undefined {
  const raw = Array.isArray(value) ? value[0] : value;
  if (typeof raw === "string" && (WATCH_BASKETS as readonly string[]).includes(raw)) {
    return raw as WatchBasket;
  }
  return undefined;
}

export function watchHref(
  pane: WatchPane,
  locale: "en" | "zh",
  params: Record<string, string | string[] | undefined> = {},
): string {
  const search = new URLSearchParams();
  search.set("pane", pane);
  if (pane === "quotes") {
    for (const key of ["symbol", "start", "end", "freq", "provider"] as const) {
      const raw = params[key];
      const value = Array.isArray(raw) ? raw[0] : raw;
      if (value) search.set(key, value);
    }
  }
  if (pane === "cross") {
    const basket = parseWatchBasket(params.basket);
    if (basket) search.set("basket", basket);
  }
  return `/${locale}/watch?${search.toString()}`;
}
