export type SellerScoreBreakdown = {
  yield_score?: number | null;
  liquidity_score?: number | null;
  delta_safety_score?: number | null;
  iv_edge_score?: number | null;
  iv_rank_score?: number | null;
  composite: number;
  weights_used: Record<string, number>;
};

const LABELS = {
  en: {
    yield: "Yield",
    liquidity: "Liquidity",
    delta_safety: "Δ safety",
    iv_edge: "IV edge",
    iv_rank: "IVR",
  },
  zh: {
    yield: "收益",
    liquidity: "流动性",
    delta_safety: "Δ安全",
    iv_edge: "IV估值",
    iv_rank: "IVR",
  },
} as const;

function formatLeg(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "--";
  }
  return String(Math.round(value));
}

/** One-line seller score breakdown for the screener table. */
export function formatSellerScoreLine(
  score: SellerScoreBreakdown | null | undefined,
  locale: "en" | "zh",
): string {
  if (!score) {
    return "";
  }
  const labels = LABELS[locale];
  const legs = [
    `${labels.yield} ${formatLeg(score.yield_score)}`,
    `${labels.liquidity} ${formatLeg(score.liquidity_score)}`,
    `${labels.delta_safety} ${formatLeg(score.delta_safety_score)}`,
    `${labels.iv_edge} ${formatLeg(score.iv_edge_score)}`,
    `${labels.iv_rank} ${formatLeg(score.iv_rank_score)}`,
  ];
  return `${Math.round(score.composite)} · ${legs.join(" · ")}`;
}
