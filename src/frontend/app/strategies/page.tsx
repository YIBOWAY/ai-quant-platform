import { ErrorBanner } from "@/components/ErrorBanner";
import { StrategyCatalogWorkbench } from "@/components/forms/StrategyCatalogWorkbench";
import { getFactors, getStrategies, getUniverses } from "@/lib/api";
import { getCachedHealth } from "@/lib/serverApi";
import { getServerLocale } from "@/lib/serverLocale";

export default async function StrategiesPage({ searchParams }: { searchParams?: Promise<Record<string, string | string[] | undefined>> }) {
  const params = (await searchParams) ?? {};
  const locale = await getServerLocale();
  const [strategies, universes, factors, health] = await Promise.all([
    getStrategies(),
    getUniverses(),
    getFactors(),
    getCachedHealth(),
  ]);
  const futuReachable = health.futu_opend?.reachable !== false;

  return (
    <div className="flex h-full min-h-0 flex-col bg-bg-base">
      <ErrorBanner messages={[strategies.apiError, universes.apiError, factors.apiError]} />
      <StrategyCatalogWorkbench
        initialStrategyId={typeof params.strategy === "string" ? params.strategy : undefined}
        factors={factors.factors}
        locale={locale}
        strategies={strategies.strategies}
        universes={universes.universes}
        futuReachable={futuReachable}
      />
    </div>
  );
}
