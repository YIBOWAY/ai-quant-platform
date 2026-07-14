import type {
  AgentCandidatesResponse,
  HermesArtifactShelfEnvelope,
} from "@/lib/api";

export type HermesAttentionItem = {
  id: string;
  kind: "approval" | "failure" | "stale" | "offline" | "degraded";
  title: string;
  summary: string;
  href?: string;
};

export type HermesResultSummary = {
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

export type HermesTodayModel = {
  state: "empty" | "normal" | "degraded" | "offline";
  attention: HermesAttentionItem[];
  automation: HermesAutomationSummary;
  recentResults: HermesResultSummary[];
  technical: HermesTechnicalSource[];
};

export type HermesTodayModelInput = {
  artifacts: HermesArtifactShelfEnvelope;
  candidates: AgentCandidatesResponse;
};

export type HermesDeliveryState = "blocked_in_this_slice";

export type HermesFeatureFlags = {
  shell: boolean;
  chat: false;
  execution: false;
  unifiedResults: false;
  legacyRedirects: false;
  deliveryState: HermesDeliveryState;
};

/** Backend CandidateReadItem keys required on every list payload (nullable ≠ optional). */
export type HermesCandidateReadItem =
  AgentCandidatesResponse["candidates"][number];
