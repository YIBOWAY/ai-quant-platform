import { HermesTodayView } from "@/components/hermes/today";
import { getAgentCandidates, getHermesArtifacts } from "@/lib/api";
import { buildHermesTodayModel } from "@/lib/hermes/viewModel";
import { getServerLocale } from "@/lib/serverLocale";

export default async function HermesWorkbenchPage() {
  const locale = await getServerLocale();
  const [candidates, artifacts] = await Promise.all([
    getAgentCandidates(),
    getHermesArtifacts(),
  ]);
  const model = buildHermesTodayModel({ candidates, artifacts });

  return <HermesTodayView artifacts={artifacts} locale={locale} model={model} />;
}
