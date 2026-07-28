export type BriefSummaryLocale = "en" | "zh";

export type BriefSummaryMarket = {
  symbol: "SPY" | "QQQ" | "SOXX" | "IGV";
  changePct?: number;
};

export type BriefSummaryInput = {
  locale: BriefSummaryLocale;
  equity: string;
  paperWeekReturn: string;
  markets: BriefSummaryMarket[];
  digestTitles: string[];
};

export type BriefSummary = {
  lede: string;
  marketNote: string;
};

function finiteChange(market: BriefSummaryMarket | undefined): number | undefined {
  return market && Number.isFinite(market.changePct) ? market.changePct : undefined;
}

function formatChange(value: number): string {
  return `${value >= 0 ? "▲" : "▼"} ${Math.abs(value * 100).toFixed(2)}%`;
}

function formatPointSpread(value: number): string {
  return Math.abs(value * 100).toFixed(2);
}

function firstDigestTitle(titles: string[]): string | undefined {
  const title = titles.find((value) => value.trim().length > 0)?.trim();
  if (!title) {
    return undefined;
  }
  return title.length <= 60 ? title : `${title.slice(0, 59)}…`;
}

function buildMarketNote(
  markets: BriefSummaryMarket[],
  locale: BriefSummaryLocale,
): string {
  const complete = markets.filter(
    (market): market is BriefSummaryMarket & { changePct: number } =>
      finiteChange(market) !== undefined,
  );
  if (complete.length < 4) {
    if (locale === "zh") {
      return `四个观察 ETF 中仅 ${complete.length} 只有有效涨跌数据，暂不判断市场广度和行业相对强弱。`;
    }
    return `Only ${complete.length} of four watched ETFs have valid moves; market breadth and sector leadership are not assessed yet.`;
  }

  const ranked = [...complete].sort(
    (left, right) =>
      right.changePct - left.changePct || left.symbol.localeCompare(right.symbol),
  );
  const strongest = ranked[0];
  const weakest = ranked.at(-1) ?? ranked[0];
  const positiveCount = complete.filter((market) => market.changePct >= 0).length;
  const spy = finiteChange(complete.find((market) => market.symbol === "SPY"));
  const qqq = finiteChange(complete.find((market) => market.symbol === "QQQ"));
  const igv = finiteChange(complete.find((market) => market.symbol === "IGV"));
  const soxx = finiteChange(complete.find((market) => market.symbol === "SOXX"));

  const broadDirection =
    spy === undefined || qqq === undefined
      ? locale === "zh"
        ? "宽基数据不完整"
        : "broad-market data are incomplete"
      : spy >= 0 && qqq >= 0
        ? locale === "zh"
          ? "两只宽基同步上涨"
          : "both broad-market ETFs advanced"
        : spy < 0 && qqq < 0
          ? locale === "zh"
            ? "两只宽基同步下跌"
            : "both broad-market ETFs declined"
          : locale === "zh"
            ? "宽基方向分化"
            : "the broad-market ETFs diverged";

  const sectorSpread = (igv ?? 0) - (soxx ?? 0);
  const spreadLabel =
    Math.abs(sectorSpread) >= 0.02
      ? locale === "zh"
        ? "行业表现分化明显"
        : "a pronounced sector split"
      : locale === "zh"
        ? "行业表现差距有限"
        : "a limited sector gap";

  if (locale === "zh") {
    const sectorLeader = sectorSpread >= 0 ? "软件相对半导体领先" : "半导体相对软件领先";
    return `四个观察 ETF 中 ${positiveCount} 只上涨，${broadDirection}；${strongest.symbol} 领涨（${formatChange(strongest.changePct)}），${weakest.symbol} 领跌（${formatChange(weakest.changePct)}）。${sectorLeader} ${formatPointSpread(sectorSpread)} 个百分点，${spreadLabel}。`;
  }

  const sectorLeader =
    sectorSpread >= 0 ? "Software led semiconductors" : "Semiconductors led software";
  return `${positiveCount} of four watched ETFs advanced and ${broadDirection}; ${strongest.symbol} led (${formatChange(strongest.changePct)}) while ${weakest.symbol} lagged (${formatChange(weakest.changePct)}). ${sectorLeader} by ${formatPointSpread(sectorSpread)} percentage points, ${spreadLabel}.`;
}

export function buildBriefSummary(input: BriefSummaryInput): BriefSummary {
  const marketNote = buildMarketNote(input.markets, input.locale);
  const digestTitle = firstDigestTitle(input.digestTitles);
  const digestCount = input.digestTitles.filter((title) => title.trim().length > 0).length;

  if (input.locale === "zh") {
    const digestNote = digestCount
      ? `AI 情报共 ${digestCount} 条${digestTitle ? `，头条关注「${digestTitle}」` : ""}。`
      : "AI 情报源暂无可用条目。";
    return {
      marketNote,
      lede: `今晨模拟盘权益为 ${input.equity}，近 7 日收益 ${input.paperWeekReturn}。市场方面，${marketNote}${digestNote}`,
    };
  }

  const digestNote = digestCount
    ? `The AI intelligence feed contains ${digestCount} item${digestCount === 1 ? "" : "s"}${digestTitle ? `, led by “${digestTitle}”` : ""}.`
    : "No AI intelligence items are currently available.";
  return {
    marketNote,
    lede: `Paper equity is ${input.equity}, with a seven-day return of ${input.paperWeekReturn}. In markets, ${marketNote} ${digestNote}`,
  };
}
