/**
 * Shared equity-curve normalization for backtest pages.
 *
 * Joins strategy and benchmark curves BY TIMESTAMP (date key), never by array
 * index: the two series can have different lengths or holiday gaps, and an
 * index join silently misaligns the chart. Both series are normalized to 1.0
 * at their first positive value so the chart compares relative growth.
 */

export type EquityPoint = {
  timestamp: string;
  strategy: number | null;
  benchmark: number | null;
};

type ParsedRow = { timestamp: string; value: number };

export function normalizeEquity(
  strategyRows: Array<Record<string, unknown>>,
  benchmarkRows?: Array<Record<string, unknown>>,
): EquityPoint[] {
  const parsedStrategy = parseRows(strategyRows);
  const firstStrategy = parsedStrategy.find((row) => row.value > 0)?.value;
  if (!firstStrategy) {
    return [];
  }

  const parsedBenchmark = benchmarkRows ? parseRows(benchmarkRows) : [];
  const firstBenchmark = parsedBenchmark.find((row) => row.value > 0)?.value;
  const benchmarkMap = new Map(
    parsedBenchmark.map((row) => [
      row.timestamp,
      firstBenchmark ? row.value / firstBenchmark : null,
    ]),
  );

  return parsedStrategy.map((row) => ({
    timestamp: row.timestamp,
    strategy: row.value / firstStrategy,
    benchmark: benchmarkMap.get(row.timestamp) ?? null,
  }));
}

function parseRows(rows: Array<Record<string, unknown>>): ParsedRow[] {
  return rows
    .map((row, index) => ({
      timestamp: String(row.timestamp ?? `row-${index + 1}`).slice(0, 10),
      value: toFiniteNumber(row.equity),
    }))
    .filter((row): row is ParsedRow => row.value !== undefined);
}

function toFiniteNumber(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}
