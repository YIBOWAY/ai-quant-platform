import { ErrorBanner } from "@/components/ErrorBanner";
import { StrategyCatalogWorkbench } from "@/components/forms/StrategyCatalogWorkbench";
import {
  getFactors,
  getHealth,
  getReversalMomentumReplicationDetail,
  getStrategies,
  getUniverses,
} from "@/lib/api";
import { getServerLocale } from "@/lib/serverLocale";

type ReplicationRunDetailPageProps = {
  params: Promise<{ runId: string }>;
};

export default async function ReplicationRunDetailPage({
  params,
}: ReplicationRunDetailPageProps) {
  const locale = await getServerLocale();
  const runId = (await params)?.runId ?? "";
  const [detail, strategies, universes, factors, health] = await Promise.all([
    getReversalMomentumReplicationDetail(runId),
    getStrategies(),
    getUniverses(),
    getFactors(),
    getHealth(),
  ]);
  const futuReachable = health.futu_opend?.reachable !== false;
  const initialResult = Object.keys(detail.result ?? {}).length ? detail.result : null;

  return (
    <div className="flex h-full min-h-0 flex-col bg-bg-base">
      <ErrorBanner
        messages={[detail.apiError, strategies.apiError, universes.apiError, factors.apiError]}
      />
      <StrategyCatalogWorkbench
        factors={factors.factors}
        locale={locale}
        strategies={strategies.strategies}
        universes={universes.universes}
        futuReachable={futuReachable}
        initialStrategyId="reversal_momentum"
        initialResult={initialResult}
      />
    </div>
  );
}
