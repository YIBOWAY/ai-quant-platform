import type { HungSleeveEffectResponse } from "./api";

export function hungSleeveMark(
  hungCount: number,
  effect: HungSleeveEffectResponse,
  locale: "zh" | "en",
): { equity: string; observation: string } {
  const missing =
    locale === "zh"
      ? { equity: "暂不可用", observation: "尚无成交" }
      : { equity: "unavailable", observation: "no fills yet" };
  const unavailable = locale === "zh" ? "效果暂不可用" : "effect unavailable";
  const observationCount = effect.observation_day_count;
  const validObservationCount =
    Number.isInteger(observationCount) && observationCount > 0;
  const dayLabel =
    locale === "zh" ? "日" : observationCount === 1 ? "day" : "days";
  const unavailableObservation = validObservationCount
    ? `${observationCount} ${dayLabel} · ${unavailable}`
    : unavailable;
  if (
    effect.apiError ||
    effect.hung_count !== hungCount
  ) {
    return { equity: missing.equity, observation: unavailableObservation };
  }
  if (
    effect.empty === true &&
    observationCount === 0 &&
    effect.sleeve_equity_status === "empty"
  ) {
    return missing;
  }
  if (
    effect.sleeve_equity_status !== "available" ||
    !Number.isFinite(effect.sleeve_equity)
  ) {
    return { equity: missing.equity, observation: unavailableObservation };
  }
  const equity = Number(effect.sleeve_equity).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const sleeveReturn = effect.sleeve_return_pct;
  const observation = Number.isFinite(sleeveReturn)
    ? `${Number(sleeveReturn) >= 0 ? "▲" : "▼"} ${Math.abs(Number(sleeveReturn)).toFixed(2)}%`
    : locale === "zh"
      ? "效果暂不可用"
      : "effect unavailable";
  const valuationDate = effect.as_of || effect.series.at(-1)?.date;
  const dateAndCoverage = locale === "zh"
    ? `估值截至 ${valuationDate || "日期未知"} · 覆盖 ${effect.covered_sleeve_count ?? "未知"}/${hungCount} 条`
    : `Valued ${valuationDate || "date unknown"} · covers ${effect.covered_sleeve_count ?? "unknown"}/${hungCount} strategies`;
  const basis = effect.observation_day_count === 0
    ? locale === "zh" ? "尚无成交；暂无交易收益样本" : "No fills or trading-return sample"
    : effect.return_method === "net_profit_over_allocated_capital"
    ? locale === "zh" ? "累计盈亏 / 累计投入" : "profit / allocated capital"
    : locale === "zh" ? "首个成交收盘起算" : "since first fill close";
  return {
    equity,
    observation: `${dateAndCoverage} · ${locale === "zh" ? "成交" : "fills on"} ${effect.observation_day_count} ${dayLabel} · ${basis} ${observation}`,
  };
}

export function officialHungCount(book: {
  hung_count?: number;
  apiError?: string;
}): { hungCount: number; bookAvailable: boolean } {
  if (book.apiError) {
    return { hungCount: 0, bookAvailable: false };
  }
  if (typeof book.hung_count !== "number" || book.hung_count < 0) {
    return { hungCount: 0, bookAvailable: false };
  }
  return { hungCount: book.hung_count, bookAvailable: true };
}

export function marketBarsAsOf(asOfValues: Array<string | undefined>): string | undefined {
  const days = asOfValues
    .map((value) => (value ? value.slice(0, 10) : ""))
    .filter((value) => /^\d{4}-\d{2}-\d{2}$/.test(value));
  if (days.length === 0) {
    return undefined;
  }
  return days.sort().at(-1);
}

export function composeBriefLede(input: {
  locale: "zh" | "en";
  hungCount: number;
  bookAvailable: boolean;
  equity: string;
  paperReturn: string;
  performanceLabel: string;
  marketNote: string;
  asiaRadarNote: string;
  digestCount: number;
  marketAsOf?: string;
  sleeveEquity?: string;
  sleeveObservation?: string;
}): string {
  const official = input.bookAvailable && input.hungCount > 0;
  const asOf =
    input.locale === "zh"
      ? input.marketAsOf
        ? `行情截至 ${input.marketAsOf}。`
        : ""
      : input.marketAsOf
        ? ` Market bars through ${input.marketAsOf}.`
        : "";
  const sleeveEquity =
    input.sleeveEquity ?? (input.locale === "zh" ? "暂不可用" : "unavailable");
  const sleeveObservation =
    input.sleeveObservation ?? (input.locale === "zh" ? "尚无成交" : "no fills yet");
  if (input.locale === "zh") {
    if (official) {
      return `已启用 ${input.hungCount} 条模拟策略。最近可用策略估值 ${sleeveEquity}（${sleeveObservation}），不代表实时资产；模拟账户总资产 ${input.equity}（包含手工持仓和历史停用策略持仓），${input.performanceLabel}变动 ${input.paperReturn}。市场方面，${input.marketNote} ${input.asiaRadarNote}${asOf}另整理 ${input.digestCount} 条 AI 新闻。`;
    }
    return `市场方面，${input.marketNote} ${input.asiaRadarNote}${asOf}模拟账户总资产 ${input.equity}（包含手工持仓和历史停用策略持仓），${input.performanceLabel}变动 ${input.paperReturn}。另整理 ${input.digestCount} 条 AI 新闻。`;
  }
  if (official) {
    return `${input.hungCount} simulated strategies are enabled. Latest available strategy valuation ${sleeveEquity} (${sleeveObservation}), not live account equity. Account inventory (including manual and retired strategies) is ${input.equity} with a ${input.paperReturn} ${input.performanceLabel} change. Market note: ${input.marketNote} ${input.asiaRadarNote}${asOf} ${input.digestCount} AI news items are included.`;
  }
  return `Platform market note: ${input.marketNote} ${input.asiaRadarNote}${asOf} Account inventory (manual plus fossils, not official hung observation) prints at ${input.equity} with a ${input.paperReturn} ${input.performanceLabel} change. It has set ${input.digestCount} AI intelligence items in type.`;
}
