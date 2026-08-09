import type {
  PaperAccountPerformanceResponse,
  PaperPerformanceRange,
} from "@/lib/api";
import type { BriefArchivePayload } from "@/lib/briefArchive";

export type BriefPerformanceRange = PaperPerformanceRange;
export type BriefPerformanceSnapshot = NonNullable<BriefArchivePayload["performance"]>;

export function resolveBriefArchiveBlockedReason(
  paperEquityBlockedReason: string | null | undefined,
  masterPerformanceApiError: string | null | undefined,
) {
  return paperEquityBlockedReason ?? masterPerformanceApiError ?? null;
}

export function parseBriefPerformanceRange(value: unknown): BriefPerformanceRange {
  const candidate = Array.isArray(value) ? value[0] : value;
  return candidate === "1m" || candidate === "3m" || candidate === "7d"
    ? candidate
    : "7d";
}

export function buildBriefPerformanceSnapshot(
  master: PaperAccountPerformanceResponse,
  selectedRange: BriefPerformanceRange,
): BriefPerformanceSnapshot {
  if (master.range !== "3m") {
    throw new Error("Brief archive performance master must use range=3m");
  }
  return {
    selected_range: selectedRange,
    master_range: "3m",
    granularity: master.granularity,
    benchmarks: [...master.benchmarks],
    requested_start: master.requested_start,
    requested_end: master.requested_end,
    actual_start: master.actual_start,
    actual_end: master.actual_end,
    coverage_complete: master.coverage_complete,
    series: master.series.map((series) => ({
      id: series.id,
      kind: series.kind,
      label: series.label,
      symbol: series.symbol,
      status: series.status,
      source: series.source,
      as_of: series.as_of,
      error_code: series.error_code,
      points: series.points.map((point) => ({
        date: point.date,
        return_ratio: point.return_ratio,
        equity: point.equity,
        close: point.close,
      })),
    })),
    warnings: [...master.warnings],
  };
}

export function selectBriefPerformanceSeries(
  snapshot: BriefPerformanceSnapshot,
): BriefPerformanceSnapshot["series"] {
  const lastDate =
    snapshot.actual_end ??
    snapshot.series
      .flatMap((series) => series.points.map((point) => point.date))
      .sort()
      .at(-1) ??
    null;
  if (!lastDate) {
    return snapshot.series.map((series) => ({
      ...series,
      points: [],
    }));
  }
  const startDate = performanceRangeStart(lastDate, snapshot.selected_range);
  return snapshot.series.map((series) => {
    const points = series.points
      .filter((point) => point.date >= startDate && point.date <= lastDate)
      .sort((a, b) => a.date.localeCompare(b.date));
    const base = 1 + (points[0]?.return_ratio ?? 0);
    return {
      ...series,
      points:
        points.length > 0 && base > 0
          ? points.map((point) => ({
              ...point,
              return_ratio: (1 + point.return_ratio) / base - 1,
            }))
          : [],
    };
  });
}

function performanceRangeStart(
  endValue: string,
  range: BriefPerformanceRange,
) {
  const [year, month, day] = endValue.split("-").map(Number);
  const end = new Date(Date.UTC(year, month - 1, day));
  if (range === "7d") {
    end.setUTCDate(end.getUTCDate() - 6);
    return end.toISOString().slice(0, 10);
  }
  const months = range === "1m" ? 1 : 3;
  const absoluteMonth = year * 12 + month - 1 - months;
  const targetYear = Math.floor(absoluteMonth / 12);
  const targetMonth = absoluteMonth % 12;
  const daysInMonth = new Date(
    Date.UTC(targetYear, targetMonth + 1, 0),
  ).getUTCDate();
  return [
    String(targetYear).padStart(4, "0"),
    String(targetMonth + 1).padStart(2, "0"),
    String(Math.min(day, daysInMonth)).padStart(2, "0"),
  ].join("-");
}
