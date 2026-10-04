import type { components } from "./api.generated";
import { apiRequest } from "./apiClient";
import { ensureOwnerSession, ownerPostJson } from "./hermes/workspaceClient";

export type FactorScorecards = components["schemas"]["FactorScorecardsResponse"];

export function getFactorScorecards() {
  return apiRequest<FactorScorecards>("/api/factor-scorecards");
}

export async function refreshFactorScorecards(request: Record<string, unknown> = {}) {
  await ensureOwnerSession();
  return ownerPostJson<FactorScorecards>("/api/factor-scorecards/refresh", request);
}
