import {
  HERMES_RESULT_KINDS,
  HERMES_RESULT_SOURCES,
  hermesResultKey,
  isHermesResultKind,
  isHermesResultResourceId,
  isHermesResultSource,
  type HermesResultItem,
  type HermesResultItemHrefs,
  type HermesResultsEnvelope,
  type HermesResultsFilterModel,
  type HermesResultsPaginationModel,
  type HermesResultsQuery,
} from "./resultsTypes";
import { resultKindLabel, resultSourceLabel } from "./resultsPresentation";
import { localizePath, type Locale } from "@/lib/locale";

export type HermesResultsSearchParams = Record<
  string,
  string | string[] | undefined
>;

export type ParsedHermesResultsQuery = HermesResultsQuery & {
  limit: number;
  offset: number;
};

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function boundedInteger(
  value: string | undefined,
  fallback: number,
  minimum: number,
  maximum: number,
): number {
  if (value === undefined || !/^-?\d+$/.test(value)) return fallback;
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed)) return fallback;
  return Math.min(maximum, Math.max(minimum, parsed));
}

function boundedText(
  value: string | undefined,
  maximumLength: number,
): string | undefined {
  const trimmed = value?.trim();
  return trimmed && trimmed.length <= maximumLength ? trimmed : undefined;
}

export function parseHermesResultsSearchParams(
  raw: HermesResultsSearchParams,
): ParsedHermesResultsQuery {
  const kindValue = first(raw.kind);
  const sourceValue = first(raw.source);
  const kind = kindValue && isHermesResultKind(kindValue) ? kindValue : undefined;
  const source =
    sourceValue && isHermesResultSource(sourceValue) ? sourceValue : undefined;
  const status = boundedText(first(raw.status), 128);
  const search = boundedText(first(raw.search), 256);

  return {
    ...(kind ? { kind } : {}),
    ...(source ? { source } : {}),
    ...(status ? { status } : {}),
    ...(search ? { search } : {}),
    limit: boundedInteger(first(raw.limit), 20, 1, 100),
    offset: boundedInteger(first(raw.offset), 0, 0, 10_000),
  };
}

const routingCopy = {
  en: {
    all: "All",
    kind: "Result type",
    source: "Source",
    status: "Status",
    search: "Search",
  },
  zh: {
    all: "全部",
    kind: "结果类型",
    source: "来源",
    status: "状态",
    search: "搜索",
  },
} as const;

function buildResultsHref(
  locale: Locale,
  query: ParsedHermesResultsQuery,
): string {
  const params = new URLSearchParams();
  if (query.kind) params.set("kind", query.kind);
  if (query.status) params.set("status", query.status);
  if (query.source) params.set("source", query.source);
  if (query.search) params.set("search", query.search);
  if (query.limit !== 20) params.set("limit", String(query.limit));
  if (query.offset > 0) params.set("offset", String(query.offset));
  const base = localizePath("/hermes/results", locale);
  const encoded = params.toString();
  return encoded ? `${base}?${encoded}` : base;
}

function withFilter(
  query: ParsedHermesResultsQuery,
  key: "kind" | "source" | "status",
  value: string | undefined,
): ParsedHermesResultsQuery {
  const next = { ...query, offset: 0 };
  if (value === undefined) {
    delete next[key];
  } else if (key === "kind" && isHermesResultKind(value)) {
    next.kind = value;
  } else if (key === "source" && isHermesResultSource(value)) {
    next.source = value;
  } else if (key === "status") {
    next.status = value;
  }
  return next;
}

export function buildHermesResultsPageModel({
  envelope,
  locale,
  query,
}: {
  envelope: HermesResultsEnvelope;
  locale: Locale;
  query: ParsedHermesResultsQuery;
}): {
  itemHrefs: HermesResultItemHrefs;
  filters: HermesResultsFilterModel;
  pagination: HermesResultsPaginationModel;
} {
  const text = routingCopy[locale];
  const itemHrefs: Record<string, string> = {};
  for (const item of envelope.items) {
    if (!isHermesResultResourceId(item.resource_id)) continue;
    itemHrefs[hermesResultKey(item)] = localizePath(
      `/hermes/results/${item.kind}/${encodeURIComponent(item.resource_id)}`,
      locale,
    );
  }

  const statusValues = Array.from(
    new Set(
      [query.status, ...envelope.items.map((item) => item.status)].filter(
        (value): value is string => Boolean(value),
      ),
    ),
  ).sort((left, right) => left.localeCompare(right));
  const groups: HermesResultsFilterModel["groups"] = [
    {
      key: "kind",
      label: text.kind,
      options: [
        {
          key: "all",
          label: text.all,
          href: buildResultsHref(locale, withFilter(query, "kind", undefined)),
          active: query.kind === undefined,
        },
        ...HERMES_RESULT_KINDS.map((kind) => ({
          key: kind,
          label: resultKindLabel(kind, locale),
          href: buildResultsHref(locale, withFilter(query, "kind", kind)),
          active: query.kind === kind,
        })),
      ],
    },
    {
      key: "source",
      label: text.source,
      options: [
        {
          key: "all",
          label: text.all,
          href: buildResultsHref(locale, withFilter(query, "source", undefined)),
          active: query.source === undefined,
        },
        ...HERMES_RESULT_SOURCES.map((source) => ({
          key: source,
          label: resultSourceLabel(source, locale),
          href: buildResultsHref(locale, withFilter(query, "source", source)),
          active: query.source === source,
        })),
      ],
    },
  ];
  if (statusValues.length) {
    groups.push({
      key: "status",
      label: text.status,
      options: [
        {
          key: "all",
          label: text.all,
          href: buildResultsHref(locale, withFilter(query, "status", undefined)),
          active: query.status === undefined,
        },
        ...statusValues.map((status) => ({
          key: status,
          label: status,
          href: buildResultsHref(locale, withFilter(query, "status", status)),
          active: query.status === status,
        })),
      ],
    });
  }

  const activeParts = [
    query.kind ? `${text.kind}: ${resultKindLabel(query.kind, locale)}` : null,
    query.source ? `${text.source}: ${resultSourceLabel(query.source, locale)}` : null,
    query.status ? `${text.status}: ${query.status}` : null,
    query.search ? `${text.search}: ${query.search}` : null,
  ].filter((value): value is string => value !== null);
  const hasFilters = activeParts.length > 0;
  const cleared: ParsedHermesResultsQuery = {
    limit: query.limit,
    offset: 0,
  };
  const authoritativeQuery = {
    ...query,
    limit: envelope.limit,
    offset: envelope.offset,
  };
  const searchHiddenFields = [
    query.kind ? { name: "kind", value: query.kind } : null,
    query.status ? { name: "status", value: query.status } : null,
    query.source ? { name: "source", value: query.source } : null,
    query.limit !== 20 ? { name: "limit", value: String(query.limit) } : null,
  ].filter((field): field is { name: string; value: string } => field !== null);
  const exactTotal =
    envelope.total_is_exact && typeof envelope.total === "number"
      ? envelope.total
      : null;
  const previousOffset =
    exactTotal !== null && envelope.offset >= exactTotal
    ? Math.max(
        0,
        Math.floor(Math.max(0, exactTotal - 1) / envelope.limit) *
          envelope.limit,
      )
    : Math.max(0, envelope.offset - envelope.limit);

  return {
    itemHrefs,
    filters: {
      activeSummary: activeParts.length ? activeParts.join(" · ") : null,
      clearHref: hasFilters ? buildResultsHref(locale, cleared) : null,
      search: {
        action: localizePath("/hermes/results", locale),
        value: query.search ?? "",
        hiddenFields: searchHiddenFields,
      },
      groups,
    },
    pagination: {
      previousHref:
        envelope.offset > 0
          ? buildResultsHref(locale, {
              ...authoritativeQuery,
              offset: previousOffset,
            })
          : null,
      nextHref: envelope.has_more
        ? buildResultsHref(locale, {
            ...authoritativeQuery,
            offset: envelope.offset + envelope.limit,
          })
        : null,
    },
  };
}

export function buildHermesOriginalResultHref(
  item: HermesResultItem,
  locale: Locale,
): string | null {
  if (!isHermesResultResourceId(item.resource_id)) return null;
  const resourceId = encodeURIComponent(item.resource_id);
  switch (item.kind) {
    case "backtest":
      return localizePath(`/backtest/${resourceId}`, locale);
    case "factor":
      return localizePath(`/factor-lab/${resourceId}`, locale);
    case "paper":
      return localizePath(`/paper-trading/${resourceId}`, locale);
    case "replication":
      return localizePath(`/strategies/${resourceId}`, locale);
    case "experiment":
      return localizePath(`/experiments?experiment=${resourceId}`, locale);
    case "factor_candidate":
      return localizePath(`/hermes/approvals?candidate=${resourceId}`, locale);
    default:
      return null;
  }
}
