export type ExperimentFactorSummary = {
  factorId: string;
  weight: number;
  weightLabel: string;
  direction: string;
  directionLabel: string;
};

export type ExperimentStrategySummary = {
  factorCount: number;
  factors: ExperimentFactorSummary[];
  rebalanceEveryNBars: number | null;
  totalAbsoluteWeight: number;
};

export function summarizeExperimentStrategy(config: unknown): ExperimentStrategySummary {
  const configRecord = asRecord(config);
  const factorBlend = asRecord(configRecord?.factor_blend);
  const factors = Array.isArray(factorBlend?.factors)
    ? factorBlend.factors.map(parseFactor).filter((factor) => factor !== null)
    : [];

  return {
    factorCount: factors.length,
    factors,
    rebalanceEveryNBars: positiveNumberOrNull(factorBlend?.rebalance_every_n_bars),
    totalAbsoluteWeight: factors.reduce((total, factor) => total + Math.abs(factor.weight), 0),
  };
}

function parseFactor(value: unknown): ExperimentFactorSummary | null {
  const record = asRecord(value);
  const factorId = stringOrNull(record?.factor_id);
  if (!factorId) {
    return null;
  }

  const weight = numberOrDefault(record?.weight, 1);
  const direction = stringOrNull(record?.direction) ?? "higher_is_better";
  return {
    factorId,
    weight,
    weightLabel: `${weight.toFixed(2)}x`,
    direction,
    directionLabel: directionLabel(direction),
  };
}

function directionLabel(direction: string) {
  if (direction === "higher_is_better") {
    return "higher is better";
  }
  if (direction === "lower_is_better") {
    return "lower is better";
  }
  return direction.replaceAll("_", " ");
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function numberOrDefault(value: unknown, fallback: number) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function positiveNumberOrNull(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

function stringOrNull(value: unknown) {
  return typeof value === "string" && value.trim() ? value : null;
}
