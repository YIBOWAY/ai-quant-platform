import { UnifiedResultsIndex } from "@/components/hermes/results";
import { getHermesResults } from "@/lib/api";
import {
  buildHermesResultsPageModel,
  parseHermesResultsSearchParams,
  type HermesResultsSearchParams,
} from "@/lib/hermes/resultsRouting";
import { getServerLocale } from "@/lib/serverLocale";

type HermesResultsPageProps = {
  searchParams?: Promise<HermesResultsSearchParams>;
};

/** Read-only index over the backend's authoritative Unified Results catalog. */
export default async function HermesResultsPage({
  searchParams,
}: HermesResultsPageProps) {
  const rawSearchParams = (await searchParams) ?? {};
  const locale = await getServerLocale(rawSearchParams);
  const query = parseHermesResultsSearchParams(rawSearchParams);
  const envelope = await getHermesResults(query);
  const model = buildHermesResultsPageModel({ envelope, locale, query });

  return (
    <UnifiedResultsIndex
      envelope={envelope}
      filters={model.filters}
      itemHrefs={model.itemHrefs}
      locale={locale}
      pagination={model.pagination}
    />
  );
}
