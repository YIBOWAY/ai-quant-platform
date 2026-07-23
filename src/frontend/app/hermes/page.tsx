import { HermesSessionDeepLinkBinder } from "@/components/hermes/sessions/HermesSessionDeepLinkBinder";
import { HermesTodayView } from "@/components/hermes/today";
import {
  getAgentCandidates,
  getHermesArtifacts,
  getHermesResults,
} from "@/lib/api";
import { buildHermesTodayModel } from "@/lib/hermes/viewModel";
import { isUsableHermesApiSessionId } from "@/lib/hermes/transcriptHelpers";
import { getServerLocale } from "@/lib/serverLocale";

type HermesWorkbenchPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function HermesWorkbenchPage({
  searchParams: searchParamsPromise,
}: HermesWorkbenchPageProps) {
  const locale = await getServerLocale();
  const [candidates, artifacts, results, searchParams] = await Promise.all([
    getAgentCandidates(),
    getHermesArtifacts(),
    getHermesResults({ limit: 5, offset: 0 }),
    searchParamsPromise,
  ]);
  const model = buildHermesTodayModel({ candidates, artifacts, results });
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
      <HermesTodayView artifacts={artifacts} locale={locale} model={model} />
    </>
  );
}
