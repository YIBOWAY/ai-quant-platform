import { apiRequest } from "./apiClient";
import { ensureOwnerSession, ownerPostJson } from "./hermes/workspaceClient";
import type { StrategyStudiesResponse as StrategyStudies, StrategyStudyProfileResponse } from "./api.generated";

/** Saved research only. Reading or selecting a profile never starts a run. */
export type { StrategyStudies };

export type StrategyStudyDetail = Required<StrategyStudyProfileResponse>;

export function getStrategyStudies() {
  return apiRequest<StrategyStudies>("/api/strategy-studies");
}

export function getStrategyStudyProfile(runId: string, profileId: string, signalDate?: string) {
  const path = `/api/strategy-studies/${encodeURIComponent(runId)}/profiles/${encodeURIComponent(profileId)}`;
  return apiRequest<StrategyStudyDetail>(`${path}${signalDate ? `?signal_date=${encodeURIComponent(signalDate)}` : ""}`);
}

export async function refreshStrategyStudies(includeDiscovery = false) {
  await ensureOwnerSession();
  return ownerPostJson<StrategyStudies>("/api/strategy-studies/refresh", {
    include_discovery: includeDiscovery,
  });
}
