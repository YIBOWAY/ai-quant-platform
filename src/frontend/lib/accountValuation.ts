import type { Locale } from "./locale";

type ValuedPosition = { symbol?: string; price_kind?: string | null; last_price?: number | null };
type ValuedAccount = {
  positions?: ValuedPosition[];
  valuation_status?: string | null;
  market_equity?: number | null;
  unpriced_symbols?: string[];
};

export function hasMarketPrice(position: ValuedPosition): boolean {
  return position.price_kind !== "avg_cost_fallback"
    && position.price_kind !== "unavailable"
    && typeof position.last_price === "number"
    && Number.isFinite(position.last_price)
    && position.last_price > 0;
}

export function accountValuation(account: ValuedAccount | null | undefined): {
  complete: boolean; missingSymbols: string[];
} {
  if (!account) return { complete: false, missingSymbols: [] };
  const missingSymbols = [...new Set([
    ...(account.unpriced_symbols ?? []),
    ...(account.positions ?? []).filter((position) => !hasMarketPrice(position))
      .map((position) => position.symbol ?? "").filter(Boolean),
  ])].sort();
  const missingPrice = (account.positions ?? []).some((position) => !hasMarketPrice(position));
  const invalidMarketEquity = account.market_equity !== undefined
    && (account.market_equity === null || !Number.isFinite(account.market_equity));
  return {
    complete: account.valuation_status !== "incomplete"
      && !missingPrice && missingSymbols.length === 0 && !invalidMarketEquity,
    missingSymbols,
  };
}

export function valuationWarning(account: ValuedAccount | null | undefined, locale: Locale): string | null {
  const valuation = accountValuation(account);
  if (valuation.complete) return null;
  const names = valuation.missingSymbols.join("、");
  return locale === "zh"
    ? `${names ? `缺少 ${names} 的有效行情` : "持仓行情不完整"}，当前净值、浮动盈亏和持仓比例暂不能准确计算，已留空。成本只保留作买入记录，不当作现价；现金和已实现盈亏不受此影响。`
    : `${names ? `Valid market prices are missing for ${names}` : "Position prices are incomplete"}. Current equity, unrealized P&L and position weights are unknown. Cost remains a purchase record, not a market price; cash and realized P&L are unaffected.`;
}
