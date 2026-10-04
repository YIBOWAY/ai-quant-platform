import { describe, expect, it } from "vitest";
import { accountValuation, hasMarketPrice, valuationWarning } from "./accountValuation";

describe("account valuation presentation", () => {
  it("does not treat a cost placeholder as market equity or a valid market price", () => {
    const account = { positions: [{ symbol: "MU", price_kind: "avg_cost_fallback", last_price: 872.14 }], price_source: { kind: "mixed" } };
    expect(accountValuation(account)).toEqual({ complete: false, missingSymbols: ["MU"] });
    expect(hasMarketPrice(account.positions[0])).toBe(false);
  });
  it("accepts actual quotes and cash-only accounts without inventing missing prices", () => {
    expect(accountValuation({ positions: [{ symbol: "MU", price_kind: "futu_snapshot", last_price: 975.26 }] }).complete).toBe(true);
    expect(accountValuation({ positions: [] }).complete).toBe(true);
    expect(accountValuation({ valuation_status: "incomplete", unpriced_symbols: ["MU"], positions: [] }).complete).toBe(false);
  });
  it("cannot turn non-finite prices or an explicit unknown market equity into a complete valuation", () => {
    expect(hasMarketPrice({last_price: Infinity})).toBe(false);
    expect(hasMarketPrice({last_price: 0})).toBe(false);
    expect(hasMarketPrice({last_price: 10, price_kind: "unavailable"})).toBe(false);
    expect(accountValuation({positions: [], market_equity: null}).complete).toBe(false);
    expect(accountValuation({positions: [], market_equity: undefined}).complete).toBe(true);
  });
  it("names missing symbols while explaining that cash and realized P&L remain usable", () => {
    const warning = valuationWarning({positions: [{symbol: "MU", last_price: null}]}, "zh");
    expect(warning).toContain("缺少 MU 的有效行情");
    expect(warning).toContain("现金和已实现盈亏不受此影响");
    expect(valuationWarning({positions: []}, "zh")).toBeNull();
  });
});
