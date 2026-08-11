import type {
  AgentCandidatesResponse,
  HermesArtifactShelfEnvelope,
  HermesGatewayStatusResponse,
  HermesResultsResponse,
} from "@/lib/api";

export type HermesAttentionItem = {
  id: string;
  kind: "approval" | "failure" | "stale" | "offline" | "degraded";
  title: string;
  summary: string;
  href?: string;
};

export type HermesHqaConclusionSummary = {
  id: string;
  kind: string;
  title: string;
  summary: string;
  status: string;
  occurredAt: string;
  href?: string;
  limitations: string[];
};

export type HermesTechnicalSource = {
  id: string;
  label: string;
  status: "available" | "degraded" | "unavailable";
  lastSyncedAt?: string;
  details: Array<{ label: string; value: string }>;
};

export type HermesAutomationSummary = {
  healthy: number;
  total: number;
  status: "healthy" | "attention" | "unavailable";
  exceptions: Array<{
    jobId: string;
    status: string;
    reason: string;
  }>;
};

export type HermesUnifiedResultSummary = {
  kind: HermesResultsResponse["items"][number]["kind"];
  resourceId: string;
  displayTitle: string;
  summary: string | null;
  status: string;
  occurredAt: string;
  source: HermesResultsResponse["items"][number]["source"];
};

export type HermesUnifiedResultsPreview = {
  readStatus: HermesResultsResponse["read_status"];
  /** Null means the catalog could not establish a total; zero is a known empty result. */
  total: number | null;
  items: HermesUnifiedResultSummary[];
  warningCode?: string;
};

export type HermesTodayModel = {
  state: "empty" | "normal" | "degraded" | "offline";
  attention: HermesAttentionItem[];
  automation: HermesAutomationSummary;
  hqaConclusions: HermesHqaConclusionSummary[];
  unifiedResults: HermesUnifiedResultsPreview;
  technical: HermesTechnicalSource[];
};

export type HermesTodayModelInput = {
  artifacts: HermesArtifactShelfEnvelope;
  candidates: AgentCandidatesResponse;
  results: HermesResultsResponse;
};

/**
 * UI-1 Direction A: normalized Hermes gateway posture for the status line.
 * readStatus is fail-closed normalized (unknown raw values → unavailable).
 */
export type HermesGatewaySummary = {
  readStatus: "available" | "degraded" | "unavailable";
  connected: boolean;
  /** available + connected — the only posture shown as "online". */
  online: boolean;
  /** True when local managed-session write admission is open (not public cutover). */
  chatWriteReady: boolean;
  blockers: string[];
  warningCodes: string[];
};

/** UI-1 Direction A: aggregated artifact-source posture for the status line. */
export type HermesSourceRollup = {
  total: number;
  available: number;
  degraded: number;
  unavailable: number;
  status: "available" | "degraded" | "unavailable" | "empty";
};

export type HermesGreetingSlot = "morning" | "afternoon" | "evening";

/**
 * UI-1 Direction A overview model (greeting + status line + attention +
 * running + technical). Derived without the results catalog so the results
 * section can carry its own read_status honestly.
 */
export type HermesTodayOverviewModel = {
  state: HermesTodayModel["state"];
  greetingSlot: HermesGreetingSlot;
  attention: HermesAttentionItem[];
  automation: HermesAutomationSummary;
  gateway: HermesGatewaySummary;
  sources: HermesSourceRollup;
  technical: HermesTechnicalSource[];
};

export type HermesTodayOverviewModelInput = {
  artifacts: HermesArtifactShelfEnvelope;
  candidates: AgentCandidatesResponse;
  gateway: HermesGatewayStatusResponse;
  /** Clock injection for deterministic greeting tests. */
  now?: Date;
};

export type HermesDeliveryState =
  | "blocked_in_this_slice"
  | "local_mutation_authorized";

export type HermesFeatureFlags = {
  shell: boolean;
  sessionRead: true;
  /** Operator deny switch; backend admission still decides whether chat opens. */
  chat: boolean;
  execution: false;
  approvalMutations: false;
  unifiedResultsCutoverAccepted: false;
  legacyRedirects: false;
  agentStudioRedirect: boolean;
  deliveryState: HermesDeliveryState;
};

/** Backend CandidateReadItem keys required on every list payload (nullable ≠ optional). */
export type HermesCandidateReadItem =
  AgentCandidatesResponse["candidates"][number];
