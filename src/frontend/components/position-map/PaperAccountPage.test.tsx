import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PaperAccountResponse } from "@/lib/api";
import PaperTrading from "@/app/paper-trading/page";
import { PositionMapPageContent } from "./PositionMapPageContent";

const mocks = vi.hoisted(() => ({ account: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  getPaperAccount: mocks.account,
  getPaperAccountLedger: async () => ({entries: []}),
  getPaperRuns: async () => ({paper_runs: []}),
  getStrategies: async () => ({strategies: []}),
  getPaperStrategyConfigs: async () => ({configs: []}),
  getPaperStrategySleeves: async () => ({sleeves: []}),
  getBacktests: async () => ({backtests: []}),
  getPaperAccountActivity: async () => ({account: await mocks.account(), balance_history: [], order_history: [], pending_orders: [], trade_log: [], pending_order_total: 0, order_history_total: 0, balance_history_total: 0, trade_log_total: 0}),
}));
vi.mock("@/lib/serverLocale", () => ({getServerLocale: async () => "zh"}));
vi.mock("@/lib/serverApi", () => ({
  getCachedHealth: async () => ({safety: {paper_trading: true, live_trading_enabled: false}}),
  getCachedSettings: async () => ({safety: {paper_trading: true, live_trading_enabled: false}}),
}));
vi.mock("@/components/AccountRefreshControl", () => ({AccountRefreshControl: () => null}));
vi.mock("@/components/position-map/QuickTradeDrawer", () => ({QuickTradeDrawer: () => null}));
vi.mock("@/components/forms/AccountTradePanel", () => ({AccountTradePanel: () => null}));
vi.mock("@/components/forms/PaperRunForm", () => ({PaperRunForm: () => null}));
vi.mock("@/components/forms/PaperStrategyOpsPanel", () => ({PaperStrategyOpsPanel: () => null}));
vi.mock("@/components/forms/PaperStrategySleevesPanel", () => ({PaperStrategySleevesPanel: () => null}));

const account: PaperAccountResponse = {
  account_id: "test", base_currency: "USD", initial_cash: 100000,
  cash: 5000, available_cash: 5000, manual_available_cash: 5000, reserved_cash: 0,
  equity: 98765, unrealized_pnl: 9999, realized_pnl: 123, pnl_abs: 10122, pnl_pct: 0.10122,
  invested_pct: 0.95, kill_switch: true, price_source: {kind: "mixed", as_of: null},
  created_at: "2026-09-01", updated_at: "2026-09-15", pending_orders: [],
  positions: [{ symbol: "MU", quantity: 100, avg_cost: 872.14, last_price: 987.65,
    market_value: 98765, unrealized_pnl: 9999, weight: 0.95,
    price_kind: "avg_cost_fallback", price_as_of: null, source_breakdown: {manual: 1} }],
};

describe("paper-account valuation presentation", () => {
  beforeEach(() => { mocks.account.mockResolvedValue(account); });
  it("does not display reference equity, fake position price or zero-loss placeholders", async () => {
    const html = renderToStaticMarkup(await PaperTrading({}));
    expect(html).toContain("缺少 MU 的有效行情");
    expect(html).toContain("872.14");
    expect(html).toContain("$5,000");
    expect(html).not.toContain("$98,765");
    expect(html).not.toContain("987.65");
    expect(html).not.toContain("$9,999");
    expect(html).not.toContain("10.12%");
  });
  it("preserves normal real-price account values", async () => {
    mocks.account.mockResolvedValue({...account, positions: account.positions.map((p) => ({...p, price_kind: "futu_snapshot"}))});
    const html = renderToStaticMarkup(await PaperTrading({}));
    expect(html).toContain("$98,765");
    expect(html).toContain("987.65");
    expect(html).not.toContain("缺少 MU 的有效行情");
  });

  it("uses the same missing-price policy for map equity, unrealized returns and exposure", async () => {
    const html = renderToStaticMarkup(await PositionMapPageContent({}));
    expect(html).toContain("缺少 MU 的有效行情");
    expect(html).toContain("已实现损益");
    expect(html).toContain("$123");
    expect(html).toContain("$5,000");
    expect(html).not.toContain("98,765");
    expect(html).not.toContain("9,999");
    expect(html).not.toContain("10.12%");
  });
});
