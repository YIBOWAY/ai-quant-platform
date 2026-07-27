import type {
  AgentCandidatesResponse,
  HermesArtifact,
  HermesArtifactShelfEnvelope,
  HermesAutomationStatusArtifactData,
  HermesArtifactSource,
  HermesGatewayStatusResponse,
  HermesResultsResponse,
} from "@/lib/api";
import { hermesRoutes } from "./routes";
import type {
  HermesAttentionItem,
  HermesAutomationSummary,
  HermesGatewaySummary,
  HermesGreetingSlot,
  HermesHqaConclusionSummary,
  HermesSourceRollup,
  HermesTechnicalSource,
  HermesTodayModel,
  HermesTodayModelInput,
  HermesTodayOverviewModel,
  HermesTodayOverviewModelInput,
  HermesUnifiedResultsPreview,
} from "./types";

const KNOWN_JOB_IDS = [
  "daily_close",
  "freshness",
  "weekly",
  "notification_drain",
] as const;

/** Fixed four automation job ids (demo data-contract §2.5). */
export const HERMES_KNOWN_JOB_IDS: readonly string[] = KNOWN_JOB_IDS;

type KnownJobId = (typeof KNOWN_JOB_IDS)[number];

const KNOWN_JOB_ID_SET = new Set<string>(KNOWN_JOB_IDS);

const DEGRADED_NOTIFICATION = new Set([
  "fallback_persisted",
  "delivery_unknown",
]);

const ATTENTION_KIND_ORDER: Record<HermesAttentionItem["kind"], number> = {
  approval: 0,
  failure: 1,
  stale: 2,
  offline: 3,
  degraded: 4,
};

function isKnownJobId(value: string): value is KnownJobId {
  return KNOWN_JOB_ID_SET.has(value);
}

function isAutomationItem(
  item: HermesArtifact,
): item is Extract<HermesArtifact, { kind: "automation_status" }> {
  return item.kind === "automation_status";
}

function occurredAtMillis(value: string): number {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
}

function newestArtifactFirst(a: HermesArtifact, b: HermesArtifact): number {
  const timeDelta = occurredAtMillis(b.occurred_at) - occurredAtMillis(a.occurred_at);
  if (timeDelta !== 0) return timeDelta;
  return b.id.localeCompare(a.id);
}

export function pickLatestAutomation(
  items: HermesArtifact[],
): Extract<HermesArtifact, { kind: "automation_status" }> | null {
  const automationItems = items.filter(isAutomationItem);
  if (automationItems.length === 0) return null;
  return automationItems.slice().sort(newestArtifactFirst)[0] ?? null;
}

/** Newest artifact of a given kind (occurred_at desc, then id). */
export function pickLatestArtifactByKind<K extends HermesArtifact["kind"]>(
  items: HermesArtifact[],
  kind: K,
): Extract<HermesArtifact, { kind: K }> | null {
  const matched = items.filter(
    (item): item is Extract<HermesArtifact, { kind: K }> => item.kind === kind,
  );
  if (matched.length === 0) return null;
  return matched.slice().sort(newestArtifactFirst)[0] ?? null;
}

function jobIsException(
  job: HermesAutomationStatusArtifactData["jobs"][number],
): boolean {
  if (
    job.status === "failed" ||
    job.status === "stale" ||
    job.status === "never_run"
  ) {
    return true;
  }
  return DEGRADED_NOTIFICATION.has(job.notification_status);
}

function exceptionAttentionKind(
  job: HermesAutomationStatusArtifactData["jobs"][number],
): HermesAttentionItem["kind"] {
  if (job.status === "stale") return "stale";
  if (job.status === "failed" || job.status === "never_run") return "failure";
  return "degraded";
}

export function buildAutomation(
  artifacts: HermesArtifactShelfEnvelope,
): HermesAutomationSummary {
  if (artifacts.read_status === "unavailable") {
    return {
      healthy: 0,
      total: KNOWN_JOB_IDS.length,
      status: "unavailable",
      exceptions: [],
    };
  }

  const latest = pickLatestAutomation(artifacts.items);
  if (!latest) {
    return {
      healthy: 0,
      total: KNOWN_JOB_IDS.length,
      status: "unavailable",
      exceptions: [],
    };
  }

  const jobs = latest.data.jobs.filter((job) => isKnownJobId(job.job_id));
  const exceptions = jobs
    .filter(jobIsException)
    .map((job) => ({
      jobId: job.job_id,
      status: job.status,
      reason:
        job.reason_code ??
        (DEGRADED_NOTIFICATION.has(job.notification_status)
          ? `notification:${job.notification_status}`
          : job.status),
    }))
    .sort((a, b) => a.jobId.localeCompare(b.jobId));

  const healthy = jobs.length - exceptions.length;
  return {
    healthy,
    total: KNOWN_JOB_IDS.length,
    status: exceptions.length > 0 ? "attention" : "healthy",
    exceptions,
  };
}

function automationAttention(
  artifacts: HermesArtifactShelfEnvelope,
  automation: HermesAutomationSummary,
): HermesAttentionItem[] {
  const latest = pickLatestAutomation(artifacts.items);
  if (!latest) return [];
  const byId = new Map<
    string,
    HermesAutomationStatusArtifactData["jobs"][number]
  >(
    latest.data.jobs
      .filter((job) => isKnownJobId(job.job_id))
      .map((job) => [job.job_id, job]),
  );

  return automation.exceptions.map((exception) => {
    const job = byId.get(exception.jobId);
    const kind = job ? exceptionAttentionKind(job) : "degraded";
    return {
      id: `automation:${exception.jobId}`,
      kind,
      title: `Automation job ${exception.jobId}`,
      summary: exception.reason,
      href: hermesRoutes.tasks,
    };
  });
}

function candidateAttention(
  candidates: AgentCandidatesResponse,
): HermesAttentionItem[] {
  const items: HermesAttentionItem[] = [];
  if (candidates.apiError) {
    items.push({
      id: "candidate-feed",
      kind: "degraded",
      title: "Candidate source unavailable",
      summary: candidates.apiError,
    });
  }
  for (const raw of candidates.candidates) {
    const candidate = raw;
    const id = candidate.candidate_id;
    const integrity = candidate.integrity_state ?? null;
    const approvalEnabled = candidate.approval_enabled === true;
    const pending =
      candidate.status === "pending" ||
      candidate.approval_binding === "pending";

    if (
      integrity === "verified" &&
      approvalEnabled &&
      pending &&
      candidate.manifest_digest
    ) {
      items.push({
        id,
        kind: "approval",
        title: "Research approval item",
        summary: candidate.goal ?? id,
        href: hermesRoutes.approvals,
      });
      continue;
    }

    if (
      integrity === "migration_required" ||
      integrity === "corrupt" ||
      candidate.approval_binding === "legacy_unbound"
    ) {
      items.push({
        id,
        kind: "degraded",
        title:
          integrity === "migration_required"
            ? "Candidate requires migration"
            : integrity === "corrupt"
              ? "Candidate integrity failed"
              : "Legacy unbound candidate",
        summary:
          integrity === "corrupt"
            ? candidate.integrity_error_code ?? id
            : candidate.goal ?? id,
      });
    }
  }
  return items;
}

function offlineAttention(
  artifacts: HermesArtifactShelfEnvelope,
): HermesAttentionItem[] {
  if (artifacts.read_status !== "unavailable") return [];
  return [
    {
      id: "artifact-feed",
      kind: "offline",
      title: "Hermes artifact sources unavailable",
      summary:
        artifacts.warnings[0]?.code ??
        artifacts.apiError ??
        "artifact_feed_unavailable",
    },
  ];
}

function sortAttention(items: HermesAttentionItem[]): HermesAttentionItem[] {
  return [...items].sort((a, b) => {
    const kindDelta =
      ATTENTION_KIND_ORDER[a.kind] - ATTENTION_KIND_ORDER[b.kind];
    if (kindDelta !== 0) return kindDelta;
    return a.id.localeCompare(b.id);
  });
}

function limitationsFromData(data: Record<string, unknown>): string[] {
  const value = data.limitations;
  if (!Array.isArray(value)) return [];
  return value.filter((entry): entry is string => typeof entry === "string");
}

function resultTitle(item: HermesArtifact): string {
  if (item.kind === "weekly_review") {
    return `Weekly review · ${item.data.week_id}`;
  }
  if (item.kind === "opportunity_summary") {
    return "Opportunity review";
  }
  if (item.kind === "prediction") {
    return `Prediction · ${item.data.symbol}`;
  }
  if (item.kind === "market_foresight") {
    return item.data.summary || "Market foresight";
  }
  if (item.kind === "portfolio_risk") {
    return "Portfolio risk";
  }
  return item.kind;
}

function resultSummary(item: HermesArtifact): string {
  if (item.kind === "weekly_review") {
    return `signals=${item.data.unique_signal_count}; missed=${item.data.opportunity_missed_count}`;
  }
  if (item.kind === "opportunity_summary") {
    return `total=${item.data.total_count}`;
  }
  if (item.kind === "prediction") {
    return `${item.data.direction} · ${item.data.state}`;
  }
  if (item.kind === "market_foresight") {
    return `${item.data.candidate_count} market prediction proposals`;
  }
  if (item.kind === "portfolio_risk") {
    return item.data.largest_symbol
      ? `largest=${item.data.largest_symbol}`
      : "portfolio risk snapshot";
  }
  return item.status;
}

export function buildHqaConclusions(
  artifacts: HermesArtifactShelfEnvelope,
): HermesHqaConclusionSummary[] {
  return artifacts.items
    .filter((item) => item.kind !== "automation_status")
    .slice()
    .sort(newestArtifactFirst)
    .map((item) => ({
      id: item.id,
      kind: item.kind,
      title: resultTitle(item),
      summary: resultSummary(item),
      status: item.status,
      occurredAt: item.occurred_at,
      href: hermesRoutes.results,
      limitations: limitationsFromData(
        item.data as unknown as Record<string, unknown>,
      ),
    }));
}

function boundedProjectionText(
  value: unknown,
  maximum: number,
): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > maximum) return null;
  return trimmed;
}

export function buildUnifiedResultsPreview(
  results: HermesResultsResponse,
): HermesUnifiedResultsPreview {
  const items = results.items.slice(0, 5).map((item) => {
    const projection = item as typeof item & Record<string, unknown>;
    return {
      kind: item.kind,
      resourceId: item.resource_id,
      displayTitle:
        boundedProjectionText(projection.display_title, 256) ??
        `${item.kind} · ${item.resource_id}`,
      summary: boundedProjectionText(projection.summary, 1_000),
      status: item.status,
      occurredAt: item.occurred_at,
      source: item.source,
    };
  });
  const warningCode = boundedProjectionText(results.warnings[0]?.code, 128);
  return {
    readStatus: results.read_status,
    total:
      results.read_status === "unavailable" ||
      results.read_status === "degraded" ||
      !results.total_is_exact
        ? null
        : (results.total ?? null),
    items,
    ...(warningCode ? { warningCode } : {}),
  };
}

function mapSourceStatus(
  status: HermesArtifactSource["status"],
): HermesTechnicalSource["status"] {
  if (status === "degraded") return "degraded";
  if (status === "unavailable") return "unavailable";
  return "available";
}

function buildTechnical(
  artifacts: HermesArtifactShelfEnvelope,
): HermesTechnicalSource[] {
  const sources: HermesTechnicalSource[] = artifacts.sources
    .slice()
    .sort((a, b) => a.kind.localeCompare(b.kind))
    .map((source) => {
      const details: HermesTechnicalSource["details"] = [
        { label: "status", value: source.status },
      ];
      if (source.reason_code) {
        details.push({ label: "reason_code", value: source.reason_code });
      }
      if (source.latest_at) {
        details.push({ label: "latest_at", value: source.latest_at });
      }
      return {
        id: source.kind,
        label: source.kind,
        status: mapSourceStatus(source.status),
        lastSyncedAt: source.latest_at ?? undefined,
        details,
      };
    });

  if (artifacts.warnings.length > 0) {
    sources.push({
      id: "artifact_feed_warnings",
      label: "artifact_feed",
      status:
        artifacts.read_status === "unavailable" ? "unavailable" : "degraded",
      details: artifacts.warnings.map((warning) => ({
        label: warning.source,
        value: warning.code,
      })),
    });
  }

  if (artifacts.as_of) {
    sources.push({
      id: "feed_as_of",
      label: "as_of",
      status: "available",
      lastSyncedAt: artifacts.as_of,
      details: [{ label: "as_of", value: artifacts.as_of }],
    });
  }

  return sources;
}

function deriveState(input: {
  artifacts: HermesArtifactShelfEnvelope;
  attention: HermesAttentionItem[];
  automation: HermesAutomationSummary;
  hqaConclusions: HermesHqaConclusionSummary[];
  unifiedResults: HermesUnifiedResultsPreview;
}): HermesTodayModel["state"] {
  if (input.artifacts.read_status === "unavailable") {
    return "offline";
  }
  if (input.attention.some((item) => item.kind === "offline")) {
    return "offline";
  }
  // Approval-only attention is healthy desk work, not a degraded posture.
  // System degradation comes from non-approval attention, automation exceptions,
  // degraded feed status, or automation attention.
  const hasSystemDegradation =
    input.attention.some((item) => item.kind !== "approval") ||
    input.automation.exceptions.length > 0 ||
    input.unifiedResults.readStatus === "unavailable" ||
    input.unifiedResults.readStatus === "degraded" ||
    input.artifacts.read_status === "degraded" ||
    input.automation.status === "attention" ||
    (input.automation.status === "unavailable" &&
      input.artifacts.read_status !== "empty");
  if (hasSystemDegradation) {
    return "degraded";
  }
  if (
    input.artifacts.read_status === "empty" ||
    (input.hqaConclusions.length === 0 &&
      input.attention.length === 0 &&
      input.artifacts.items.length === 0 &&
      input.unifiedResults.items.length === 0)
  ) {
    if (input.unifiedResults.items.length === 0) return "empty";
  }
  return "normal";
}

/**
 * Pure derivation of the read-only Hermes Today workbench model.
 * No timers, network, or capability probes.
 */
export function buildHermesTodayModel(input: HermesTodayModelInput): HermesTodayModel {  const automation = buildAutomation(input.artifacts);
  const attention = sortAttention([
    ...candidateAttention(input.candidates),
    ...automationAttention(input.artifacts, automation),
    ...offlineAttention(input.artifacts),
  ]);
  const hqaConclusions = buildHqaConclusions(input.artifacts);
  const unifiedResults = buildUnifiedResultsPreview(input.results);
  const technical = buildTechnical(input.artifacts);
  const state = deriveState({
    artifacts: input.artifacts,
    attention,
    automation,
    hqaConclusions,
    unifiedResults,
  });

  return {
    state,
    attention,
    automation,
    hqaConclusions,
    unifiedResults,
    technical,
  };
}

/* ------------------------------------------------------------------ */
/* UI-1 Direction A: overview derivations (greeting + status line).    */
/* ------------------------------------------------------------------ */

const GATEWAY_READ_STATUSES = new Set(["available", "degraded", "unavailable"]);

function boundedStrings(value: unknown, maximum: number, maxItems = 8): string[] {
  if (!Array.isArray(value)) return [];
  const out: string[] = [];
  for (const entry of value) {
    const text = boundedProjectionText(entry, maximum);
    if (text && !out.includes(text)) out.push(text);
    if (out.length >= maxItems) break;
  }
  return out;
}

/**
 * Fail-closed normalization of GET /api/hermes/gateway. Unknown or missing
 * read_status values collapse to "unavailable"; "online" requires both an
 * available read and connected=true.
 */
export function buildGatewaySummary(
  gateway: HermesGatewayStatusResponse,
): HermesGatewaySummary {
  const raw = String(gateway.read_status);
  const readStatus = (
    GATEWAY_READ_STATUSES.has(raw) ? raw : "unavailable"
  ) as HermesGatewaySummary["readStatus"];
  const connected = gateway.connected === true;
  const blockers = [
    ...boundedStrings(gateway.blockers, 128),
    ...boundedStrings(gateway.upstream_blockers, 128),
    ...boundedStrings(gateway.platform_delivery_blockers, 128),
  ].filter((code, index, all) => all.indexOf(code) === index);
  const warningCodes = Array.isArray(gateway.warnings)
    ? gateway.warnings
        .map((warning) => boundedProjectionText(warning?.code, 128))
        .filter((code): code is string => code !== null)
        .slice(0, 8)
    : [];
  return {
    readStatus,
    connected,
    online: readStatus === "available" && connected,
    blockers,
    warningCodes,
  };
}

/**
 * One-line aggregate of artifact shelf sources. Envelope unavailable wins;
 * any degraded/unavailable source degrades the line; a feed with no sources
 * is honestly "empty" rather than healthy.
 */
export function buildSourceRollup(
  artifacts: HermesArtifactShelfEnvelope,
): HermesSourceRollup {
  const sources = Array.isArray(artifacts.sources) ? artifacts.sources : [];
  const rollup: HermesSourceRollup = {
    total: sources.length,
    available: 0,
    degraded: 0,
    unavailable: 0,
    status: "empty",
  };
  for (const source of sources) {
    const mapped = mapSourceStatus(source.status);
    if (mapped === "available") rollup.available += 1;
    else if (mapped === "degraded") rollup.degraded += 1;
    else rollup.unavailable += 1;
  }
  if (artifacts.read_status === "unavailable") {
    rollup.status = "unavailable";
  } else if (sources.length === 0) {
    rollup.status = "empty";
  } else if (rollup.degraded > 0 || rollup.unavailable > 0) {
    rollup.status = "degraded";
  } else {
    rollup.status = "available";
  }
  return rollup;
}

export function greetingSlotForHour(hour: number): HermesGreetingSlot {
  if (!Number.isFinite(hour)) return "morning";
  const normalized = ((Math.trunc(hour) % 24) + 24) % 24;
  if (normalized < 12) return "morning";
  if (normalized < 18) return "afternoon";
  return "evening";
}

function shanghaiHour(now: Date): number {
  try {
    const parts = new Intl.DateTimeFormat("en-US", {
      hour: "numeric",
      hour12: false,
      timeZone: "Asia/Shanghai",
    }).formatToParts(now);
    const hour = Number(parts.find((part) => part.type === "hour")?.value);
    return Number.isFinite(hour) ? hour % 24 : 12;
  } catch {
    return 12;
  }
}

function deriveOverviewState(input: {
  artifacts: HermesArtifactShelfEnvelope;
  attention: HermesAttentionItem[];
  automation: HermesAutomationSummary;
  gateway: HermesGatewaySummary;
}): HermesTodayOverviewModel["state"] {
  if (
    input.artifacts.read_status === "unavailable" ||
    input.gateway.readStatus === "unavailable" ||
    input.attention.some((item) => item.kind === "offline")
  ) {
    return "offline";
  }
  // Approval-only attention is healthy desk work, not degradation.
  const hasSystemDegradation =
    input.attention.some((item) => item.kind !== "approval") ||
    input.automation.exceptions.length > 0 ||
    input.automation.status === "attention" ||
    input.artifacts.read_status === "degraded" ||
    input.gateway.readStatus === "degraded" ||
    (input.gateway.readStatus === "available" && !input.gateway.connected) ||
    (input.automation.status === "unavailable" &&
      input.artifacts.read_status !== "empty");
  if (hasSystemDegradation) {
    return "degraded";
  }
  if (
    input.artifacts.read_status === "empty" &&
    input.artifacts.items.length === 0 &&
    input.attention.length === 0
  ) {
    return "empty";
  }
  return "normal";
}

/**
 * UI-1 Direction A overview derivation. Same attention/automation/technical
 * inputs as buildHermesTodayModel, plus the gateway status line, and no
 * dependency on the results catalog (that Suspense boundary is independent).
 */
export function buildHermesTodayOverviewModel(
  input: HermesTodayOverviewModelInput,
): HermesTodayOverviewModel {
  const automation = buildAutomation(input.artifacts);
  const attention = sortAttention([
    ...candidateAttention(input.candidates),
    ...automationAttention(input.artifacts, automation),
    ...offlineAttention(input.artifacts),
  ]);
  const technical = buildTechnical(input.artifacts);
  const gateway = buildGatewaySummary(input.gateway);
  const sources = buildSourceRollup(input.artifacts);
  const state = deriveOverviewState({
    artifacts: input.artifacts,
    attention,
    automation,
    gateway,
  });
  const greetingSlot = greetingSlotForHour(
    shanghaiHour(input.now ?? new Date()),
  );

  return {
    state,
    greetingSlot,
    attention,
    automation,
    gateway,
    sources,
    technical,
  };
}
