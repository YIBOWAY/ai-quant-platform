import type {
  AgentCandidatesResponse,
  HermesArtifactShelfEnvelope,
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

export type HermesDeliveryState = "blocked_in_this_slice";

export type HermesFeatureFlags = {
  shell: boolean;
  sessionRead: true;
  chat: false;
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
