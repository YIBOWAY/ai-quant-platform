import type { AsiaRadarSummary, AsiaRadarSummaryEnvelope } from "@/lib/asiaRadar";

/**
 * Asia Radar `*_pct` fields are already percentage points (59.4 means 59.4%),
 * not fractions. Do not pass them through `formatPercent` (which multiplies by 100).
 */
export function formatPercentPoints(value: number, digits = 1): string {
  if (!Number.isFinite(value)) {
    return "--";
  }
  return `${value.toFixed(digits)}%`;
}

export function buildAsiaRadarNote(
  envelope: AsiaRadarSummaryEnvelope,
  locale: "en" | "zh",
): string {
  const zh = locale === "zh";
  if (!envelope.summary || envelope.summary.status !== "available") {
    return zh ? "亚洲雷达数据暂不可用。" : "Asia Radar is unavailable today.";
  }
  const summary = envelope.summary;
  const top = summary.top_ytd_symbol;
  const bottom = summary.bottom_ytd_symbol;
  const spread = summary.spread_pct;
  if (!top || !bottom || spread === null || spread === undefined) {
    return zh
      ? `亚洲雷达覆盖 ${summary.market_count} 个市场（截至 ${summary.as_of}）。`
      : `Asia Radar covers ${summary.market_count} markets as of ${summary.as_of}.`;
  }
  const winners = summary.winner_symbols.join("/");
  const laggards = summary.laggard_symbols.join("/");
  const spreadText = formatPercentPoints(Math.abs(spread));
  if (zh) {
    return `亚洲雷达（截至 ${summary.as_of}）：${winners} 领跑、${laggards} 落后，YTD 前三后三篮子分化 ${spreadText}。`;
  }
  return `Asia Radar (as of ${summary.as_of}): ${winners} lead while ${laggards} lag, with a ${spreadText} YTD spread between the top-three and bottom-three baskets.`;
}
