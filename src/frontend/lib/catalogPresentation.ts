import type { Locale } from "./locale";

type StrategyPresentationInput = {
  id: string;
  name?: string | null;
  display_name_zh?: string | null;
  description?: string | null;
};

type FactorPresentationInput = {
  factor_id: string;
  factor_name?: string | null;
  display_name_zh?: string | null;
  description?: string | null;
};

type UniversePresentationInput = { id: string; name?: string | null };

const strategyNamesZh: Record<string, string> = {
  cross_sectional_top_n: "横截面 Top-N",
  reversal_momentum: "短期反转 / 长期动量",
  mean_reversion_top_n: "均值回归 Top-N",
  drift_regime_reversal_top_n_v1: "漂移状态反转 Top-N（研究草稿）",
};

const strategyDescriptionsZh: Record<string, string> = {
  cross_sectional_top_n: "按多因子得分对股票池排序，持有得分最高的若干标的。",
  reversal_momentum: "复现短期反转与长期动量组合，仅用于研究。",
  mean_reversion_top_n: "按近期超跌程度排序，持有最可能向均值回归的若干标的。",
  drift_regime_reversal_top_n_v1: "研究草稿，仅用于验证漂移状态与短期反转组合。",
};

const factorDescriptionsZh: Record<string, string> = {
  momentum: "衡量一段时间内价格涨跌的相对强弱。",
  volatility: "衡量近期价格波动幅度，数值越低越稳定。",
  liquidity: "衡量近期成交金额与交易活跃度。",
  rsi: "衡量相对强弱及超买、超卖状态。",
  macd: "衡量快慢均线差及其变化趋势。",
  agent_candidate_wave2_sceneb_mom20_v3: "衡量 20 日价格动量，仅用于已登记的模拟研究。",
  paper_reversal_momentum_proxy_v2: "用于模拟研究的短期反转与长期动量代理因子。",
};

const universeNamesZh: Record<string, string> = {
  etf: "核心 ETF 股票池",
  technology: "科技股股票池",
  defense: "国防与航空航天股票池",
  healthcare: "医疗保健股票池",
};

function clean(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed || null;
}

export function localizedStrategyName(
  strategy: StrategyPresentationInput,
  locale: Locale,
): string {
  if (locale === "en") return clean(strategy.name) ?? strategy.id;
  return clean(strategy.display_name_zh) ?? strategyNamesZh[strategy.id] ?? "未命名策略";
}

export function localizedStrategyDescription(
  strategy: StrategyPresentationInput,
  locale: Locale,
): string {
  if (locale === "en") return clean(strategy.description) ?? "";
  return strategyDescriptionsZh[strategy.id] ?? "已登记策略；英文技术说明已在中文主视图隐藏。";
}

export function localizedFactorName(
  factor: FactorPresentationInput,
  locale: Locale,
): string {
  if (locale === "en") return clean(factor.factor_name) ?? factor.factor_id;
  return clean(factor.display_name_zh) ?? "未命名因子";
}

export function localizedFactorDescription(
  factor: FactorPresentationInput,
  locale: Locale,
): string {
  if (locale === "en") return clean(factor.description) ?? "";
  return (
    factorDescriptionsZh[factor.factor_id] ??
    "已登记因子；英文技术说明已在中文主视图隐藏。对照原始编号时可查看技术信息。"
  );
}

export function localizedUniverseName(
  universe: UniversePresentationInput,
  locale: Locale,
): string {
  if (locale === "en") return clean(universe.name) ?? universe.id;
  return universeNamesZh[universe.id] ?? "自定义股票池";
}
