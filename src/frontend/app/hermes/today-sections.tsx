import {
  getAgentCandidates,
  getHermesArtifacts,
  getHermesGatewayStatus,
  getHermesResults,
} from "@/lib/api";
import {
  buildAutomation,
  buildHermesTodayOverviewModel,
  buildHqaConclusions,
  buildUnifiedResultsPreview,
  pickLatestAutomation,
} from "@/lib/hermes/viewModel";
import type { Locale } from "@/lib/locale";
import {
  HermesTodayView,
  TodayAutomation,
  TodayResults,
} from "@/components/hermes/today";

/**
 * UI-1 Direction A Suspense boundary 1: greeting + status line + attention +
 * running + technical detail. GET-only, three parallel reads (the gateway
 * read is new for the status line).
 */
export async function HermesTodayOverviewSection({ locale }: { locale: Locale }) {
  const [candidates, artifacts, gateway] = await Promise.all([
    getAgentCandidates(),
    getHermesArtifacts(),
    getHermesGatewayStatus(),
  ]);
  const model = buildHermesTodayOverviewModel({ candidates, artifacts, gateway });

  return <HermesTodayView artifacts={artifacts} locale={locale} model={model} />;
}

/**
 * UI-1 Direction A Suspense boundary 2: merged recent results + automation
 * lane. The artifact read is deduped with boundary 1 by Next fetch
 * memoization; results stay an independent honest read_status.
 */
export async function HermesTodaySecondarySection({ locale }: { locale: Locale }) {
  const [artifacts, results] = await Promise.all([
    getHermesArtifacts(),
    getHermesResults({ limit: 5, offset: 0 }),
  ]);
  const preview = buildUnifiedResultsPreview(results);
  const hqaConclusions = buildHqaConclusions(artifacts);
  const automation = buildAutomation(artifacts);
  const automationArtifact = pickLatestAutomation(artifacts.items);

  return (
    <>
      <TodayResults
        hqaConclusions={hqaConclusions}
        locale={locale}
        preview={preview}
      />
      <TodayAutomation
        artifact={automationArtifact}
        locale={locale}
        summary={automation}
      />
    </>
  );
}
