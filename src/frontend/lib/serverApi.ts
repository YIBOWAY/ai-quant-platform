import { cache } from "react";
import { unstable_cache } from "next/cache";
import {
  getEffectivePaperSafety,
  getHealth,
  getHungSleeveEffect,
  getMarketDataHistory,
  getPaperAccount,
  getPaperAccountEquityCurve,
  getPaperAccountPerformance,
  getRemoteBook,
  getSettings,
} from "@/lib/api";

export const getCachedHealth = cache(getHealth);
export const getCachedSettings = cache(getSettings);
export const getCachedEffectivePaperSafety = cache(getEffectivePaperSafety);
export const getCachedBriefMarketDataHistory = unstable_cache(
  (ticker: string, start: string, end: string, freq = "1d") =>
    getMarketDataHistory(ticker, start, end, freq),
  ["brief-market-history-v1"],
  { revalidate: 60 },
);
export const getCachedBriefPaperAccountPerformance = unstable_cache(
  () => getPaperAccountPerformance("3m"),
  ["brief-paper-account-performance-v1"],
  { revalidate: 5 },
);
export const getCachedBriefPaperAccount = unstable_cache(
  () => getPaperAccount(),
  ["brief-paper-account-v1"],
  { revalidate: 1 },
);
export const getCachedBriefPaperAccountEquityCurve = unstable_cache(
  () => getPaperAccountEquityCurve(7),
  ["brief-paper-account-equity-curve-v1"],
  { revalidate: 1 },
);

export const getCachedRemoteBook = unstable_cache(
  () => getRemoteBook(),
  ["brief-remote-book-v1"],
  { revalidate: 5 },
);

export const getCachedHungSleeveEffect = unstable_cache(
  () => getHungSleeveEffect(),
  ["brief-hung-sleeve-effect-v1"],
  { revalidate: 5 },
);

export const getCachedAsiaRadarSummary = unstable_cache(
  async () => {
    const { getAsiaRadarSummarySafe } = await import("@/lib/asiaRadar");
    return getAsiaRadarSummarySafe();
  },
  ["brief-asia-radar-summary-v1"],
  { revalidate: 300 },
);
