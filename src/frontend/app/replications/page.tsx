import { ErrorBanner } from "@/components/ErrorBanner";
import { StrategyCatalogWorkbench } from "@/components/forms/StrategyCatalogWorkbench";
import { getFactors, getStrategies, getUniverses } from "@/lib/api";
import { getCachedHealth } from "@/lib/serverApi";
import { getServerLocale } from "@/lib/serverLocale";

export default async function ReplicationsPage() {
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
        factors={factors.factors}
        locale={locale}
        strategies={strategies.strategies}
        universes={universes.universes}
        futuReachable={futuReachable}
      />
    </div>
  );
}
