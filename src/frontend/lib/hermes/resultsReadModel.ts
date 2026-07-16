import type {
  HermesResultDetailResponse,
  HermesResultsResponse,
} from "@/lib/api";

import {
  isHermesResultKind,
  isHermesResultResourceId,
  isHermesResultSource,
  type HermesResultItem,
  type HermesResultKind,
  type HermesResultRunLink,
  type HermesResultWarning,
} from "./resultsTypes";

const DIGEST_PATTERN = /^[0-9a-f]{64}$/;
const ITEM_READ_STATUSES = new Set([
  "available",
  "degraded",
  "missing",
  "corrupt",
  "unavailable",
]);
const AGGREGATE_READ_STATUSES = new Set([
  "available",
  "degraded",
  "empty",
  "unavailable",
]);
const FRESHNESS_VALUES = new Set([
  "fresh",
  "stale",
  "not_applicable",
  "unknown",
]);
const AUTHORITIES = new Set([
  "platform_run_artifact",
  "platform_experiment_artifact",
  "platform_candidate_repository",
  "hqa_artifact_manifest",
]);
const RELATIONS = new Set(["input", "output", "context"]);
const MAX_ERROR_CHARS = 1_024;
const MAX_RESOURCE_JSON_CHARS = 1_048_576;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isBoundedString(
  value: unknown,
  minimum: number,
  maximum: number,
): value is string {
  return (
    typeof value === "string" &&
    value.length >= minimum &&
    value.length <= maximum
  );
}

function boundedApiError(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  return value.slice(0, MAX_ERROR_CHARS) || "results_response_invalid";
}

function isRenderBoundedResource(value: Record<string, unknown>): boolean {
  try {
    const serialized = JSON.stringify(value);
    return (
      typeof serialized === "string" &&
      serialized.length <= MAX_RESOURCE_JSON_CHARS
    );
  } catch {
    return false;
  }
}

function isRunLink(value: unknown): value is HermesResultRunLink {
  if (!isRecord(value)) return false;
  return (
    isBoundedString(value.command_id, 1, 64) &&
    isBoundedString(value.hermes_session_id, 1, 256) &&
    isBoundedString(value.hermes_run_id, 1, 256) &&
    typeof value.link_digest === "string" &&
    DIGEST_PATTERN.test(value.link_digest) &&
    typeof value.relation === "string" &&
    RELATIONS.has(value.relation) &&
    isBoundedString(value.observed_at, 1, 64) &&
    (value.source_event_id === undefined ||
      value.source_event_id === null ||
      isBoundedString(value.source_event_id, 1, 256))
  );
}

function hasConsistentAuthority(item: Record<string, unknown>): boolean {
  if (item.source === "platform_runs") {
    return (
      item.authority === "platform_run_artifact" &&
      ["backtest", "factor", "paper", "replication"].includes(
        String(item.kind),
      )
    );
  }
  if (item.source === "platform_experiments") {
    return (
      item.authority === "platform_experiment_artifact" &&
      item.kind === "experiment"
    );
  }
  if (item.source === "platform_candidates") {
    return (
      item.authority === "platform_candidate_repository" &&
      item.kind === "factor_candidate"
    );
  }
  return item.source === "hqa_artifact_feed"
    ? item.authority === "hqa_artifact_manifest" &&
        [
          "portfolio_risk",
          "prediction",
          "market_foresight",
          "weekly_review",
          "opportunity_summary",
          "automation_status",
        ].includes(String(item.kind))
    : false;
}

function isResultItem(value: unknown): value is HermesResultItem {
  if (!isRecord(value)) return false;
  if (
    typeof value.kind !== "string" ||
    !isHermesResultKind(value.kind) ||
    typeof value.resource_id !== "string" ||
    !isHermesResultResourceId(value.resource_id) ||
    !isBoundedString(value.display_title, 1, 256) ||
    !(
      value.summary === null ||
      value.summary === undefined ||
      isBoundedString(value.summary, 1, 1_000)
    ) ||
    !isBoundedString(value.status, 1, 128) ||
    !isBoundedString(value.occurred_at, 1, 64) ||
    typeof value.source !== "string" ||
    !isHermesResultSource(value.source) ||
    typeof value.authority !== "string" ||
    !AUTHORITIES.has(value.authority) ||
    typeof value.freshness !== "string" ||
    !FRESHNESS_VALUES.has(value.freshness) ||
    typeof value.read_status !== "string" ||
    !ITEM_READ_STATUSES.has(value.read_status) ||
    !isBoundedString(value.detail_href, 1, 1_000) ||
    value.detail_href !==
      `/api/hermes/results/${value.kind}/${value.resource_id}` ||
    !isBoundedString(value.original_href, 1, 1_000) ||
    !value.original_href.startsWith("/api/") ||
    !hasConsistentAuthority(value)
  ) {
    return false;
  }
  return (
    value.run_links === undefined ||
    value.run_links === null ||
    (Array.isArray(value.run_links) &&
      value.run_links.length <= 100 &&
      value.run_links.every(isRunLink))
  );
}

function isWarning(value: unknown): value is HermesResultWarning {
  if (!isRecord(value)) return false;
  return (
    isBoundedString(value.source, 1, 128) &&
    isBoundedString(value.code, 1, 128) &&
    (value.kind === undefined ||
      value.kind === null ||
      (typeof value.kind === "string" && isHermesResultKind(value.kind))) &&
    (value.resource_id === undefined ||
      value.resource_id === null ||
      isBoundedString(value.resource_id, 1, 1_000))
  );
}

function failureList(
  limit: number,
  offset: number,
  error: string,
): HermesResultsResponse {
  const apiError = boundedApiError(error) ?? "results_response_invalid";
  return {
    read_status: "unavailable",
    total: null,
    total_is_exact: false,
    limit,
    offset,
    has_more: false,
    items: [],
    sources: [],
    warnings: [
      {
        source: "results_catalog",
        code: apiError,
        kind: null,
        resource_id: null,
      },
    ],
    apiError,
  };
}

export function normalizeHermesResultsResponse(
  value: unknown,
  expected: { limit: number; offset: number },
): HermesResultsResponse {
  if (!isRecord(value)) {
    return failureList(expected.limit, expected.offset, "results_response_invalid");
  }
  if (Object.prototype.hasOwnProperty.call(value, "apiError")) {
    const upstreamError = boundedApiError(value.apiError);
    return failureList(
      expected.limit,
      expected.offset,
      upstreamError ?? "results_response_invalid",
    );
  }
  if (
    typeof value.read_status !== "string" ||
    !AGGREGATE_READ_STATUSES.has(value.read_status) ||
    typeof value.total_is_exact !== "boolean" ||
    !(
      (value.total_is_exact === true &&
        Number.isInteger(value.total) &&
        (value.total as number) >= 0) ||
      (value.total_is_exact === false && value.total === null)
    ) ||
    value.limit !== expected.limit ||
    value.offset !== expected.offset ||
    typeof value.has_more !== "boolean" ||
    !Array.isArray(value.items) ||
    value.items.length > 100 ||
    !value.items.every(isResultItem) ||
    !Array.isArray(value.sources) ||
    value.sources.length > 32 ||
    !value.sources.every(
      (source) =>
        isRecord(source) &&
        isBoundedString(source.source, 1, 128) &&
        typeof source.read_status === "string" &&
        AGGREGATE_READ_STATUSES.has(source.read_status) &&
        Number.isInteger(source.item_count) &&
        (source.item_count as number) >= 0,
    ) ||
    !Array.isArray(value.warnings) ||
    value.warnings.length > 200 ||
    !value.warnings.every(isWarning)
  ) {
    return failureList(expected.limit, expected.offset, "results_response_invalid");
  }
  if (value.total_is_exact === true) {
    const total = value.total as number;
    const expectedItemCount = Math.min(
      expected.limit,
      Math.max(0, total - expected.offset),
    );
    const expectedHasMore = expected.offset + value.items.length < total;
    if (
      value.items.length !== expectedItemCount ||
      value.has_more !== expectedHasMore
    ) {
      return failureList(expected.limit, expected.offset, "results_response_invalid");
    }
  }
  return value as HermesResultsResponse;
}

function failureDetail(
  kind: HermesResultKind,
  resourceId: string,
  error: string,
): HermesResultDetailResponse {
  const apiError = boundedApiError(error) ?? "results_response_invalid";
  return {
    read_status: "unavailable",
    item: null,
    resource: null,
    warnings: [
      {
        source: "results_catalog",
        code: apiError,
        kind,
        resource_id: resourceId,
      },
    ],
    apiError,
  };
}

export function normalizeHermesResultDetailResponse(
  value: unknown,
  expected: { kind: HermesResultKind; resourceId: string },
): HermesResultDetailResponse {
  if (!isRecord(value)) {
    return failureDetail(
      expected.kind,
      expected.resourceId,
      "results_response_invalid",
    );
  }
  if (Object.prototype.hasOwnProperty.call(value, "apiError")) {
    const upstreamError = boundedApiError(value.apiError);
    return failureDetail(
      expected.kind,
      expected.resourceId,
      upstreamError ?? "results_response_invalid",
    );
  }
  const item = value.item;
  const resource = value.resource;
  const itemIsValid = item === null || isResultItem(item);
  const resourceIsValid =
    resource === null || (isRecord(resource) && isRenderBoundedResource(resource));
  const exactIdentity =
    item === null ||
    (isRecord(item) &&
      item.kind === expected.kind &&
      item.resource_id === expected.resourceId);
  const nullsAreConsistent = item !== null || resource === null;
  const stateIsConsistent =
    value.read_status === "available"
      ? item !== null && resource !== null
      : value.read_status === "degraded"
        ? item !== null
      : value.read_status === "missing" || value.read_status === "unavailable"
        ? item === null && resource === null
        : nullsAreConsistent;
  if (
    typeof value.read_status !== "string" ||
    !ITEM_READ_STATUSES.has(value.read_status) ||
    !itemIsValid ||
    !resourceIsValid ||
    !exactIdentity ||
    !stateIsConsistent ||
    !Array.isArray(value.warnings) ||
    value.warnings.length > 20 ||
    !value.warnings.every(isWarning)
  ) {
    return failureDetail(
      expected.kind,
      expected.resourceId,
      "results_response_invalid",
    );
  }
  return value as HermesResultDetailResponse;
}
