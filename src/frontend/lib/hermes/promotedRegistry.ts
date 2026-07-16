export type PromotedRegistryContext = {
  readStatus: "available" | "unavailable";
  registeredCount: number;
  promotedFactorIds: string[];
  truncated: boolean;
  error: string | null;
};

const FACTOR_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$/;
const MAX_FACTOR_ROWS = 2_000;
const MAX_PROMOTED_IDS = 50;
const MAX_ERROR_CHARS = 1_024;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function unavailable(error: string): PromotedRegistryContext {
  return {
    readStatus: "unavailable",
    registeredCount: 0,
    promotedFactorIds: [],
    truncated: false,
    error: error.slice(0, MAX_ERROR_CHARS) || "factor_registry_response_invalid",
  };
}

/**
 * Build the small read-only registry projection required before Agent Studio
 * can be retired. Candidate source is never imported or executed here.
 */
export function buildPromotedRegistryContext(
  value: unknown,
): PromotedRegistryContext {
  if (!isRecord(value) || !Array.isArray(value.factors)) {
    return unavailable("factor_registry_response_invalid");
  }
  if (Object.prototype.hasOwnProperty.call(value, "apiError")) {
    return unavailable(
      typeof value.apiError === "string"
        ? value.apiError
        : "factor_registry_response_invalid",
    );
  }
  if (value.factors.length > MAX_FACTOR_ROWS) {
    return unavailable("factor_registry_response_too_large");
  }

  const promoted: string[] = [];
  const seen = new Set<string>();
  for (const row of value.factors) {
    if (
      !isRecord(row) ||
      typeof row.factor_id !== "string" ||
      !FACTOR_ID_PATTERN.test(row.factor_id) ||
      (row.origin !== "builtin" && row.origin !== "promoted") ||
      seen.has(row.factor_id)
    ) {
      return unavailable("factor_registry_response_invalid");
    }
    seen.add(row.factor_id);
    if (row.origin === "promoted") promoted.push(row.factor_id);
  }

  return {
    readStatus: "available",
    registeredCount: value.factors.length,
    promotedFactorIds: promoted.slice(0, MAX_PROMOTED_IDS),
    truncated: promoted.length > MAX_PROMOTED_IDS,
    error: null,
  };
}
