import type { components as GeneratedApiComponents } from "@/lib/api.generated";

type HermesSchemas = GeneratedApiComponents["schemas"];

export type HermesResultItem = HermesSchemas["HermesResultItem"];
export type HermesResultKind = HermesResultItem["kind"];
export type HermesResultSource = HermesResultItem["source"];
export type HermesResultAuthority = HermesResultItem["authority"];
export type HermesResultFreshness = HermesResultItem["freshness"];
export type HermesResultItemReadStatus = HermesResultItem["read_status"];
export type HermesResultAggregateReadStatus =
  HermesSchemas["HermesResultsResponse"]["read_status"];
export type HermesResultRunLink = HermesSchemas["HermesResultRunLink"];
export type HermesResultSourceState = HermesSchemas["HermesResultSourceState"];
export type HermesResultWarning = HermesSchemas["HermesResultWarning"];

export type HermesResultsEnvelope = HermesSchemas["HermesResultsResponse"] & {
  /** Transport-level failure added by the frontend read adapter. */
  apiError?: string;
};

export type HermesResultDetailEnvelope =
  HermesSchemas["HermesResultDetailResponse"] & {
    /** Transport-level failure added by the frontend read adapter. */
    apiError?: string;
  };

export type HermesResultsQuery = {
  kind?: HermesResultKind;
  status?: string;
  source?: HermesResultSource;
  search?: string;
  limit?: number;
  offset?: number;
};

export const HERMES_RESULT_KINDS = [
  "backtest",
  "factor",
  "paper",
  "replication",
  "experiment",
  "factor_candidate",
  "portfolio_risk",
  "prediction",
  "market_foresight",
  "weekly_review",
  "opportunity_summary",
  "automation_status",
] as const satisfies readonly HermesResultKind[];

export const HERMES_RESULT_SOURCES = [
  "platform_runs",
  "platform_experiments",
  "platform_candidates",
  "hqa_artifact_feed",
] as const satisfies readonly HermesResultSource[];

const hermesResultKindSet = new Set<string>(HERMES_RESULT_KINDS);
const hermesResultSourceSet = new Set<string>(HERMES_RESULT_SOURCES);
const safeHermesResultResourceId = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$/;

export function isHermesResultKind(value: string): value is HermesResultKind {
  return hermesResultKindSet.has(value);
}

export function isHermesResultSource(value: string): value is HermesResultSource {
  return hermesResultSourceSet.has(value);
}

export function isHermesResultResourceId(value: string): boolean {
  return safeHermesResultResourceId.test(value);
}

/** Decode exactly one Next.js route segment, then re-apply the canonical ID contract. */
export function parseHermesResultRouteResourceId(value: string): string | null {
  let decoded: string;
  try {
    decoded = decodeURIComponent(value);
  } catch {
    return null;
  }
  return isHermesResultResourceId(decoded) ? decoded : null;
}

export type HermesResultsFilterOption = {
  key: string;
  label: string;
  href: string;
  active: boolean;
  count?: number;
};

export type HermesResultsFilterGroup = {
  key: string;
  label: string;
  options: HermesResultsFilterOption[];
};

export type HermesResultsFilterModel = {
  activeSummary: string | null;
  clearHref: string | null;
  search: {
    action: string;
    value: string;
    hiddenFields: Array<{ name: string; value: string }>;
  };
  groups: HermesResultsFilterGroup[];
};

export type HermesResultsPaginationModel = {
  previousHref: string | null;
  nextHref: string | null;
};

export type HermesResultItemHrefs = Readonly<Record<string, string>>;

export function hermesResultKey(
  item: Pick<HermesResultItem, "kind" | "resource_id">,
): string {
  return `${item.kind}:${item.resource_id}`;
}
