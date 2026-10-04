import { HermesSessionDeepLinkBinder } from "@/components/hermes/sessions/HermesSessionDeepLinkBinder";
import { HermesDeskToday } from "@/components/hermes/desk/HermesDeskToday";
import { HermesDeskRunControls } from "@/components/hermes/desk/HermesDeskRunControls";
import {
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
  const unifiedResults = buildUnifiedResultsPreview(results);
  const latestAutomation = pickLatestAutomation(artifacts.items);
  const automationStale = artifacts.warnings.some((warning) => warning.code === "feed_stale");
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
      <HermesDeskToday
        dutyExtra={
          <>
            <HermesDeskRunControls locale={locale} />
            <TodayResults
              hqaConclusions={[]}
              locale={locale}
              preview={unifiedResults}
            />
            <details className="dp-diagnostics">
              <summary>{locale === "zh" ? "运行记录与诊断" : "Automation & diagnostics"}{automationStale ? (locale === "zh" ? " · 有过期记录" : " · Stale records") : ""}</summary>
              <TodayAutomation
                artifact={latestAutomation}
                locale={locale}
                stale={automationStale}
                summary={overview.automation}
              />
            </details>
          </>
        }
      />
    </>
  );
}
