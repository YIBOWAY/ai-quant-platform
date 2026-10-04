import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

function source(file: string) {
  return readFileSync(path.join(process.cwd(), file), "utf8");
}

describe("Chinese catalog presentation wiring", () => {
  it("localizes the backtest form strategy, stock-pool, and factor labels", () => {
    const text = source("components/forms/BacktestForm.tsx");
    expect(text).toContain("localizedStrategyName(strategy, locale)");
    expect(text).toContain("localizedUniverseName(universe, locale)");
    expect(text).toContain("localizedFactorName(factor, locale)");
  });

  it("localizes factor-lab names and hides English descriptions", () => {
    const dashboard = source("components/forms/FactorLabDashboard.tsx");
    const controls = source("components/forms/FactorLabControls.tsx");
    expect(dashboard).toContain("localizedUniverseName(dashboard.universe, locale)");
    expect(dashboard).toContain("localizedFactorName(factor, locale)");
    expect(dashboard).toContain("localizedFactorDescription(factor, locale)");
    expect(dashboard).toContain("factorById");
    expect(dashboard).toContain('columns={["factor_id", "factor_name", "direction"');
    expect(dashboard).toContain('columns={["factor_id", "factor_name", "sharpe"');
    expect(dashboard).not.toContain('locale === "zh"\n              ? ["factor_name"');
    expect(controls).toContain("localizedUniverseName(u, locale)");
  });

  it("localizes strategy catalog cards, inputs, and factor-weight labels", () => {
    const text = source("components/forms/StrategyCatalogWorkbench.tsx");
    expect(text).toContain("localizedStrategyName(strategy, locale)");
    expect(text).toContain("localizedStrategyDescription(strategy, locale)");
    expect(text).toContain("localizedUniverseName(universe, locale)");
    expect(text).toContain("localizedFactorName(factor, locale)");
    expect(text).toContain("localizedFactorName(selectedFactor, locale)");
    expect(text).toContain('source: "策略说明"');
    expect(text).not.toContain('source: "论文出处"');
  });
});
