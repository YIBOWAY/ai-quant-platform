import type { StrategyMetadata } from "./api";

const fallbackAccountRebalanceStrategies: StrategyMetadata[] = [
  {
    id: "cross_sectional_top_n",
    name: "Cross-Sectional Top-N",
    description: "",
    paper_source: null,
    run_endpoint: "/api/backtests/run",
    result_type: "backtest",
    supports_account_rebalance: true,
    parameter_schema: {},
    default_payload: {},
  },
  {
    id: "mean_reversion_top_n",
    name: "Mean-Reversion Top-N",
    description: "",
    paper_source: null,
    run_endpoint: "/api/backtests/run",
    result_type: "backtest",
    supports_account_rebalance: true,
    parameter_schema: {},
    default_payload: {},
  },
];

export function accountRebalanceStrategies(strategies: StrategyMetadata[]) {
  const supported = strategies.filter(
    (strategy) => strategy.supports_account_rebalance === true,
  );
  return supported.length ? supported : fallbackAccountRebalanceStrategies;
}
