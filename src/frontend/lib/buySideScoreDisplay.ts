/** Fields already present on BuySideRecommendation — no new API shape. */
export type BuySideScoreFields = {
  score: number;
  buyer_friendliness_score?: number | null;
  liquidity_score?: number | null;
  iv_crash_risk_score?: number | null;
  risk_reward?: number | null;
  theta_burn_7d_pct?: number | null;
};

const LABELS = {
  en: {
    total: "Score",
    buyer: "Buyer",
    liquidity: "Liquidity",
    ivCrash: "IV crush risk",
    rr: "R/R",
    theta: "7d theta",
  },
  zh: {
    total: "总分",
    buyer: "买方友好",
    liquidity: "流动性",
    ivCrash: "IV挤压风险",
    rr: "盈亏比",
    theta: "7日theta",
  },
} as const;

function formatScore(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "--";
  }
  return String(Math.round(value));
}

function formatRatio(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value) || !Number.isFinite(value)) {
    return "--";
  }
  return value.toFixed(2);
}

function formatThetaPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value) || !Number.isFinite(value)) {
    return "--";
  }
  const normalized = Math.abs(value) > 1.5 ? value : value * 100;
  return `${normalized.toFixed(1)}%`;
}

/** One-line buy-side score breakdown for recommendation cards. */
export function formatBuySideScoreLine(
  item: BuySideScoreFields | null | undefined,
  locale: "en" | "zh",
): string {
  if (!item) {
    return "";
  }
  const labels = LABELS[locale];
  const legs = [
    `${labels.buyer} ${formatScore(item.buyer_friendliness_score)}`,
    `${labels.liquidity} ${formatScore(item.liquidity_score)}`,
    `${labels.ivCrash} ${formatScore(item.iv_crash_risk_score)}`,
    `${labels.rr} ${formatRatio(item.risk_reward)}`,
    `${labels.theta} ${formatThetaPct(item.theta_burn_7d_pct)}`,
  ];
  return `${labels.total} ${formatScore(item.score)} · ${legs.join(" · ")}`;
}
