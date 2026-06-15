import { afterEach, describe, expect, it, vi } from "vitest";

import {
  type BuySideOptionsFormValues,
  buildBuySideOptionsPayload,
} from "./buySideOptionsPayload";

const baseValues: BuySideOptionsFormValues = {
  ticker: " meta ",
  view_type: "long_term_aggressive_bullish",
  target_price: 700,
  target_date: "2026-12-31",
  risk_preference: "aggressive",
  allow_capped_upside: false,
  avoid_high_iv: true,
  volatility_view: "expect_iv_crush",
  event_risk: "earnings",
  expected_iv_change_vol_points: -5,
  scenario_spot_changes: "-10, 0, 15, nope",
  scenario_iv_changes: "-5, 0, 3",
  scenario_horizon_date: "2026-07-01",
  bull_probability: 0.35,
  bull_spot_change_pct: 20,
  bull_iv_change_vol_points: -3,
  base_probability: 0.45,
  base_spot_change_pct: 8,
  base_iv_change_vol_points: -5,
  bear_probability: 0.2,
  bear_spot_change_pct: -10,
  bear_iv_change_vol_points: 4,
};

afterEach(() => {
  vi.useRealTimers();
});

describe("buildBuySideOptionsPayload", () => {
  it("normalizes ticker, scenario lists, and EV horizon days", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-01T00:00:00"));

    const payload = buildBuySideOptionsPayload(baseValues);

    expect(payload.ticker).toBe("META");
    expect(payload.scenario_spot_changes).toEqual([-10, 0, 15]);
    expect(payload.scenario_iv_changes).toEqual([-5, 0, 3]);
    expect(payload.scenario_days_passed).toEqual([0, 15, 30]);
    expect(payload.user_scenarios).toEqual([
      {
        label: "bull",
        probability: 0.35,
        spot_change_pct: 20,
        iv_change_vol_points: -3,
        days_passed: 30,
      },
      {
        label: "base",
        probability: 0.45,
        spot_change_pct: 8,
        iv_change_vol_points: -5,
        days_passed: 30,
      },
      {
        label: "bear",
        probability: 0.2,
        spot_change_pct: -10,
        iv_change_vol_points: 4,
        days_passed: 30,
      },
    ]);
  });

  it("falls back to zero scenario lists and 30-day horizon for invalid inputs", () => {
    const payload = buildBuySideOptionsPayload({
      ...baseValues,
      scenario_spot_changes: "n/a",
      scenario_iv_changes: "",
      scenario_horizon_date: "not-a-date",
    });

    expect(payload.scenario_spot_changes).toEqual([0]);
    expect(payload.scenario_iv_changes).toEqual([0]);
    expect(payload.scenario_days_passed).toEqual([0, 15, 30]);
    expect(payload.user_scenarios.every((scenario) => scenario.days_passed === 30)).toBe(true);
  });
});
