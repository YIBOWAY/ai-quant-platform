import { notFound } from "next/navigation";

import { UnifiedResultDetail } from "@/components/hermes/results";
import { getHermesResultDetail } from "@/lib/api";
import {
  buildHermesOriginalResultHref,
  type HermesResultsSearchParams,
} from "@/lib/hermes/resultsRouting";
import {
  isHermesResultKind,
  parseHermesResultRouteResourceId,
} from "@/lib/hermes/resultsTypes";
import { localizePath } from "@/lib/locale";
import { getServerLocale } from "@/lib/serverLocale";

type HermesResultDetailPageProps = {
  params: Promise<{ kind: string; resourceId: string }>;
  searchParams?: Promise<HermesResultsSearchParams>;
};

/** Safe, read-only detail route. Invalid identities never reach the backend. */
export default async function HermesResultDetailPage({
  params,
  searchParams,
}: HermesResultDetailPageProps) {
  const rawSearchParams = (await searchParams) ?? {};
  const locale = await getServerLocale(rawSearchParams);
  const { kind, resourceId: routeResourceId } = await params;
  const resourceId = parseHermesResultRouteResourceId(routeResourceId);
  if (!isHermesResultKind(kind) || resourceId === null) {
    notFound();
  }

  const envelope = await getHermesResultDetail(kind, resourceId);
  const originalResourceHref = envelope.item
    ? buildHermesOriginalResultHref(envelope.item, locale)
    : null;

  return (
    <UnifiedResultDetail
      backHref={localizePath("/hermes/results", locale)}
      envelope={envelope}
      locale={locale}
      originalResourceHref={originalResourceHref}
    />
  );
}
