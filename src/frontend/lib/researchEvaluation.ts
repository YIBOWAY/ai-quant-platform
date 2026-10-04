import type { components } from "./api.generated";
import { apiRequest } from "./apiClient";
import { ensureOwnerSession, ownerPostJson } from "./hermes/workspaceClient";

export type ResearchEvaluation = components["schemas"]["ResearchEvaluationResponse"];
export type PaperEvaluation = components["schemas"]["PaperEvaluationResponse"];
export type EvaluationObject = Record<string, unknown>;

export function object(value: unknown): EvaluationObject {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as EvaluationObject : {};
}

export function objects(value: unknown): EvaluationObject[] {
  return Array.isArray(value) ? value.filter(row => row !== null && typeof row === "object" && !Array.isArray(row)) as EvaluationObject[] : [];
}

export function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((row): row is string => typeof row === "string") : [];
}

export function valueNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function getResearchEvaluation(key: string | null = null) {
  return apiRequest<ResearchEvaluation>(`/api/research-evaluation${key ? `?key=${encodeURIComponent(key)}` : ""}`);
}

export async function refreshResearchEvaluation(key: string | null = null) {
  await ensureOwnerSession();
  return ownerPostJson<ResearchEvaluation>("/api/research-evaluation/refresh", { key });
}

export function getPaperEvaluation() {
  return apiRequest<PaperEvaluation>("/api/paper-evaluation");
}

export async function refreshPaperEvaluation() {
  await ensureOwnerSession();
  return ownerPostJson<PaperEvaluation>("/api/paper-evaluation/refresh", {});
}
