import { ErrorBanner } from "@/components/ErrorBanner";
import { isSampleSource } from "@/components/DataSourceBadge";
import { FactorLabDashboard } from "@/components/forms/FactorLabDashboard";
import { getFactorLabDashboard, getFactorRuns, getUniverses } from "@/lib/api";
import { shouldIncludeSampleRuns } from "@/lib/runSource";
import { getServerLocale } from "@/lib/serverLocale";

type FactorLabProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function single(value: string | string[] | undefined, fallback: string) {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

export default async function FactorLab({ searchParams }: FactorLabProps) {
  const params = (await searchParams) ?? {};
  const locale = await getServerLocale(params);
  const provider = single(params.provider, "futu").toLowerCase();
  const universeId = single(params.universe_id, "etf");
  const symbol = single(params.symbol, "QQQ").toUpperCase();
  const benchmarkSymbol = single(params.benchmark_symbol, symbol).toUpperCase();

  const [dashboard, factorRuns, universes] = await Promise.all([
    getFactorLabDashboard({ provider, universeId, symbol, benchmarkSymbol }),
    getFactorRuns(),
    getUniverses(),
  ]);
  const includeSample = shouldIncludeSampleRuns(params);
  const visibleRuns = includeSample
    ? factorRuns.runs
    : factorRuns.runs.filter((run) => !isSampleSource(run.source));
  const hiddenSampleCount = factorRuns.runs.length - visibleRuns.length;

  return (
    <div className="flex h-full min-h-0 flex-col bg-bg-base">
      <ErrorBanner locale={locale} messages={[dashboard.apiError, factorRuns.apiError, universes.apiError]} />
      <FactorLabDashboard
        controlsInitial={{ provider, universeId, symbol, benchmarkSymbol }}
        dashboard={dashboard}
        hiddenSampleCount={hiddenSampleCount}
        locale={locale}
        runs={visibleRuns}
        universes={universes.universes}
      />
    </div>
  );
}
