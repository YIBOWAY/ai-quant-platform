export type BuySideOptionsFormValues = {
  ticker: string;
  view_type: string;
  target_price: number;
  target_date: string;
  risk_preference: string;
  allow_capped_upside: boolean;
  avoid_high_iv: boolean;
  volatility_view: string;
  event_risk: string;
  expected_iv_change_vol_points: number;
  scenario_spot_changes: string;
  scenario_iv_changes: string;
  scenario_horizon_date: string;
  bull_probability: number;
  bull_spot_change_pct: number;
  bull_iv_change_vol_points: number;
  base_probability: number;
  base_spot_change_pct: number;
  base_iv_change_vol_points: number;
  bear_probability: number;
  bear_spot_change_pct: number;
  bear_iv_change_vol_points: number;
};

export function buildBuySideOptionsPayload(values: BuySideOptionsFormValues) {
  const scenarioDays = scenarioDaysFromHorizon(values.scenario_horizon_date);
  const evDays = scenarioDays.at(-1) ?? 30;
  return {
    ticker: values.ticker.trim().toUpperCase(),
    view_type: values.view_type,
    target_price: values.target_price,
    target_date: values.target_date,
    risk_preference: values.risk_preference,
    allow_capped_upside: values.allow_capped_upside,
    avoid_high_iv: values.avoid_high_iv,
    volatility_view: values.volatility_view,
    event_risk: values.event_risk,
    expected_iv_change_vol_points: values.expected_iv_change_vol_points,
    scenario_spot_changes: numberList(values.scenario_spot_changes),
    scenario_iv_changes: numberList(values.scenario_iv_changes),
    scenario_days_passed: scenarioDays,
    user_scenarios: [
      {
        label: "bull",
        probability: values.bull_probability,
        spot_change_pct: values.bull_spot_change_pct,
        iv_change_vol_points: values.bull_iv_change_vol_points,
        days_passed: evDays,
      },
      {
        label: "base",
        probability: values.base_probability,
        spot_change_pct: values.base_spot_change_pct,
        iv_change_vol_points: values.base_iv_change_vol_points,
        days_passed: evDays,
      },
      {
        label: "bear",
        probability: values.bear_probability,
        spot_change_pct: values.bear_spot_change_pct,
        iv_change_vol_points: values.bear_iv_change_vol_points,
        days_passed: evDays,
      },
    ],
  };
}

function daysUntil(dateString: string) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(`${dateString}T00:00:00`);
  if (Number.isNaN(target.getTime())) {
    return 30;
  }
  return Math.max(0, Math.round((target.getTime() - today.getTime()) / 86_400_000));
}

function scenarioDaysFromHorizon(dateString: string) {
  const horizon = daysUntil(dateString);
  const midpoint = Math.max(1, Math.round(horizon / 2));
  return [...new Set([0, midpoint, horizon])].sort((left, right) => left - right);
}

function numberList(value: string) {
  const parsed = value
    .split(",")
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item));
  return parsed.length ? parsed : [0];
}
