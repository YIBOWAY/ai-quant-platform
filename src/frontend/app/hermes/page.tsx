import { HermesTodayView } from "@/components/hermes/today";
import {
  getAgentCandidates,
  getHermesArtifacts,
  getHermesResults,
} from "@/lib/api";
import { buildHermesTodayModel } from "@/lib/hermes/viewModel";
import { getServerLocale } from "@/lib/serverLocale";

export default async function HermesWorkbenchPage() {
  const locale = await getServerLocale();
  const [candidates, artifacts, results] = await Promise.all([
    getAgentCandidates(),
    getHermesArtifacts(),
    getHermesResults({ limit: 5, offset: 0 }),
  ]);
  const model = buildHermesTodayModel({ candidates, artifacts, results });

  return <HermesTodayView artifacts={artifacts} locale={locale} model={model} />;
}
