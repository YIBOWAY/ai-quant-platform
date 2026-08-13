import { HermesSessionDeepLinkBinder } from "@/components/hermes/sessions/HermesSessionDeepLinkBinder";
import { D34ResearchWorkbench } from "@/components/hermes/d34";
import {
  HermesTodayView,
  RecentResults,
  TodayAutomation,
  TodayResults,
} from "@/components/hermes/today";
import {
  getAgentCandidates,
  getHermesArtifacts,
  getHermesGatewayStatus,
  getHermesResults,
} from "@/lib/api";
import {
  buildHermesTodayOverviewModel,
  buildHqaConclusions,
  buildUnifiedResultsPreview,
  pickLatestAutomation,
} from "@/lib/hermes/viewModel";
import { isUsableHermesApiSessionId } from "@/lib/hermes/transcriptHelpers";
import { getServerLocale } from "@/lib/serverLocale";

type HermesWorkbenchPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function HermesWorkbenchPage({
  searchParams: searchParamsPromise,
}: HermesWorkbenchPageProps) {
  const locale = await getServerLocale();
  const [candidates, artifacts, gateway, results, searchParams] = await Promise.all([
    getAgentCandidates(),
    getHermesArtifacts(),
    getHermesGatewayStatus(),
    getHermesResults({ limit: 5, offset: 0 }),
    searchParamsPromise,
  ]);
  const overview = buildHermesTodayOverviewModel({
    candidates,
    artifacts,
    gateway,
  });
  const hqaConclusions = buildHqaConclusions(artifacts);
  const unifiedResults = buildUnifiedResultsPreview(results);
  const latestAutomation = pickLatestAutomation(artifacts.items);
  const rawSessionId = searchParams.hermes_session_id;
  const requestedSessionId = Array.isArray(rawSessionId)
    ? rawSessionId[0]
    : rawSessionId;
  const deepLinkedSessionId = isUsableHermesApiSessionId(requestedSessionId)
    ? requestedSessionId.trim()
    : null;

  return (
    <>
      {deepLinkedSessionId ? (
        <HermesSessionDeepLinkBinder hermesSessionId={deepLinkedSessionId} />
      ) : null}
      <div className="flex flex-col gap-6">
        <HermesTodayView artifacts={artifacts} locale={locale} model={overview} />
        <D34ResearchWorkbench locale={locale} />
        <TodayResults
          hqaConclusions={[]}
          locale={locale}
          preview={unifiedResults}
        />
        <RecentResults
          artifacts={artifacts}
          locale={locale}
          results={hqaConclusions}
        />
        <TodayAutomation
          artifact={latestAutomation}
          locale={locale}
          summary={overview.automation}
        />
      </div>
    </>
  );
}
