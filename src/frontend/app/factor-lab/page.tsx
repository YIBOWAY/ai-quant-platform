import { ErrorBanner } from "@/components/ErrorBanner";
import { FactorLabDashboard } from "@/components/forms/FactorLabDashboard";
import { getFactorLabDashboard, getFactorRuns } from "@/lib/api";
import { selectDisplayRun, shouldIncludeSampleRuns } from "@/lib/runSource";
import { getServerLocale } from "@/lib/serverLocale";

type FactorLabProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function FactorLab({ searchParams }: FactorLabProps) {
  const params = (await searchParams) ?? {};
  const locale = await getServerLocale(params);
  const [dashboard, factorRuns] = await Promise.all([
    getFactorLabDashboard(),
    getFactorRuns(),
  ]);
  const latestRun = selectDisplayRun(factorRuns.runs, shouldIncludeSampleRuns(params));

  return (
    <div className="flex h-full min-h-0 flex-col bg-base">
      <ErrorBanner messages={[dashboard.apiError, factorRuns.apiError]} />
      <FactorLabDashboard
        dashboard={dashboard}
        latestRun={latestRun}
        locale={locale}
      />
    </div>
  );
}
