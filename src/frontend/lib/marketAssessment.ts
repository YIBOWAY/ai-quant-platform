import { apiRequest } from "./apiClient";
import { ensureOwnerSession, ownerPostJson } from "./hermes/workspaceClient";
import type { components } from "./api.generated";

export type MarketAssessment = components["schemas"]["MarketAssessmentResponse"];
export type MarketScope = MarketAssessment["scope"];

export function getMarketAssessment(scope: MarketScope, signal?: AbortSignal) {
  return apiRequest<MarketAssessment>(`/api/market-assessment?scope=${scope}`, { signal });
}

export async function refreshMarketAssessment(scope: MarketScope) {
  await ensureOwnerSession();
  return ownerPostJson<MarketAssessment>("/api/market-assessment/refresh", { scope, include_ai: true });
}
