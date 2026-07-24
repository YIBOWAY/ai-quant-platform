import type {
  HermesArtifactShelfEnvelope,
  HermesAutomationStatusArtifactData,
  HermesGatewayStatusResponse,
} from "@/lib/api";
import type { HermesCandidateReadItem } from "./types";

const KNOWN_JOB_IDS = [
  "daily_close",
  "freshness",
  "weekly",
  "notification_drain",
] as const;

type KnownJobId = (typeof KNOWN_JOB_IDS)[number];

const JOB_SCHEDULES: Record<
  KnownJobId,
  { expected_schedule: string; freshness_budget_seconds: number }
> = {
  daily_close: {
    expected_schedule: "15 8 * * 2-6",
    freshness_budget_seconds: 108_000,
  },
  freshness: {
    expected_schedule: "17 */2 * * *",
    freshness_budget_seconds: 10_800,
  },
  weekly: {
    expected_schedule: "0 9 * * 0",
    freshness_budget_seconds: 691_200,
  },
  notification_drain: {
    expected_schedule: "*/15 * * * *",
    freshness_budget_seconds: 1_800,
  },
};

function freshJob(
  jobId: KnownJobId,
): HermesAutomationStatusArtifactData["jobs"][number] {
  const meta = JOB_SCHEDULES[jobId];
  return {
    job_id: jobId,
    expected_schedule: meta.expected_schedule,
    timezone: "Asia/Shanghai",
    freshness_budget_seconds: meta.freshness_budget_seconds,
    last_attempt_at: "2026-07-12T00:50:00Z",
    last_success_at: "2026-07-12T00:50:00Z",
    fresh_until: "2026-07-13T06:50:00Z",
    status: "fresh",
    reason_code: null,
    last_run_id: `run-${jobId}-healthy`,
    notification_status: "delivered",
  };
}

function automationItem(
  jobs: HermesAutomationStatusArtifactData["jobs"],
  overall: "fresh" | "degraded",
  occurredAt = "2026-07-12T00:57:00Z",
) {
  return {
    id: "automation-latest",
    kind: "automation_status" as const,
    occurred_at: occurredAt,
    quality: overall === "fresh" ? ("available" as const) : ("degraded" as const),
    status: overall,
    data: {
      checked_at: occurredAt,
      overall_status: overall,
      jobs,
      proposal_only: true as const,
      trading_allowed: false as const,
    },
  };
}

const weeklyReviewItem = {
  id: "weekly-2026-W28",
  kind: "weekly_review" as const,
  occurred_at: "2026-07-12T00:59:00Z",
  quality: "available" as const,
  status: "available",
  data: {
    week_id: "2026-W28",
    period_start: "2026-07-05T00:00:00Z",
    period_end: "2026-07-12T00:00:00Z",
    safety_alert_count: 1,
    unique_signal_count: 3,
    review_draft_count: 2,
    review_confirmed_count: 1,
    prediction_created_count: 0,
    prediction_scored_count: 0,
    prediction_hit_count: 0,
    mean_direction_brier: null,
    opportunity_observed_count: 4,
    opportunity_missed_count: 1,
    opportunity_coverage_unknown_count: 1,
    limitations: ["read_only_research_summary"],
    proposal_only: true as const,
    trading_allowed: false as const,
  },
};

const baseSources = [
  {
    kind: "weekly_review" as const,
    status: "available" as const,
    latest_at: "2026-07-12T00:59:00Z",
    reason_code: null,
  },
  {
    kind: "automation_status" as const,
    status: "available" as const,
    latest_at: "2026-07-12T00:57:00Z",
    reason_code: null,
  },
];

/**
 * Shared builder enumerating every required CandidateReadItem field,
 * including required nullable keys (null ≠ omitted).
 */
export function candidateFixture(
  overrides: Partial<HermesCandidateReadItem> = {},
): HermesCandidateReadItem {
  return {
    candidate_id: "factor-complete-fixture",
    artifact_type: "factor",
    goal: "Evaluate a deterministic factor",
    universe: ["AAPL"],
    status: "pending",
    integrity_state: "verified",
    manifest_digest: "a".repeat(64),
    observed_manifest_digest: null,
    approval_binding: "pending",
    approval_enabled: true,
    integrity_error_code: null,
    ...overrides,
  } satisfies HermesCandidateReadItem;
}

export const healthyArtifacts = {
  schema_version: "1.1",
  read_status: "available",
  as_of: "2026-07-12T01:00:00Z",
  items: [
    weeklyReviewItem,
    automationItem(KNOWN_JOB_IDS.map((id) => freshJob(id)), "fresh"),
  ],
  sources: baseSources,
  warnings: [],
} satisfies HermesArtifactShelfEnvelope;

export const degradedArtifacts = {
  schema_version: "1.1",
  read_status: "available",
  as_of: "2026-07-12T01:00:00Z",
  items: [
    weeklyReviewItem,
    automationItem(
      [
        freshJob("daily_close"),
        freshJob("freshness"),
        {
          ...freshJob("weekly"),
          status: "stale",
          reason_code: "freshness_budget_exceeded",
          last_success_at: "2026-07-05T01:00:11Z",
          fresh_until: "2026-07-13T01:00:00Z",
          last_run_id: "run-weekly-stale",
          notification_status: "queued",
        },
        freshJob("notification_drain"),
      ],
      "degraded",
    ),
  ],
  sources: baseSources,
  warnings: [],
} satisfies HermesArtifactShelfEnvelope;

export function noArtifacts(
  mode: "empty" | "unavailable",
): HermesArtifactShelfEnvelope {
  if (mode === "empty") {
    return {
      schema_version: "1.1",
      read_status: "empty",
      as_of: null,
      items: [],
      sources: [],
      warnings: [{ source: "artifact_feed", code: "feed_not_built" }],
    } satisfies HermesArtifactShelfEnvelope;
  }
  return {
    schema_version: "1.1",
    read_status: "unavailable",
    as_of: null,
    items: [],
    sources: [],
    warnings: [{ source: "artifact_feed", code: "api_unavailable" }],
  } satisfies HermesArtifactShelfEnvelope;
}

/** UI-1 Direction A: GET /api/hermes/gateway fixture (fail-closed friendly). */
export function gatewayFixture(
  overrides: Partial<HermesGatewayStatusResponse> = {},
): HermesGatewayStatusResponse {
  return {
    read_status: "available",
    connected: true,
    model: "fixture-model",
    session_api_available: true,
    chat_write_ready: false,
    features: {},
    upstream_blockers: [],
    platform_delivery_blockers: [],
    blockers: [],
    warnings: [],
    ...overrides,
  } as HermesGatewayStatusResponse;
}
