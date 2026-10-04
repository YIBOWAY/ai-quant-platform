import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { AccountPositionView, PaperAccountResponse } from "@/lib/api";
import { PositionMapWorkspace } from "./PositionMapWorkspace";

vi.mock("./QuickTradeDrawer", () => ({ QuickTradeDrawer: () => null }));

const unpriced: AccountPositionView = {
  symbol: "MU", quantity: 100, avg_cost: 872.14, last_price: 987.65,
  market_value: 98765, unrealized_pnl: 9999, weight: 1,
  price_kind: "avg_cost_fallback", price_as_of: null, source_breakdown: { manual: 1 },
};

function renderWorkspace(position: AccountPositionView, tab: "positions" | "order-history" = "positions") {
  const account = { positions: [position], kill_switch: true } as PaperAccountResponse;
  return renderToStaticMarkup(<PositionMapWorkspace
    account={account} accountDown={false} backtestExposure={[]} backtestHref={null}
    balanceHistory={[]} initialTab={tab} locale="zh" orderHistory={[]} pendingOrders={[]}
    positions={[position]} priceSourceLabel="混合报价" safety={{paperTrading: true, liveTrading: false}}
    totals={{ orders: 0, orderHistory: 16, balanceHistory: 0, tradeLog: 0 }} tradeLog={[]}
  />);
}

describe("position-map valuation", () => {
  it("retains cost but hides placeholder price, market value, P&L and weights", () => {
    const html = renderWorkspace(unpriced);
    const row = html.match(/<tr[^>]*data-position-row="true"[\s\S]*?<\/tr>/)?.[0] ?? "";
    expect(row).toContain("872.14");
    expect(row).not.toContain("987.65");
    expect(row).not.toContain("98,765");
    expect(row).not.toContain("9,999");
    expect(row).not.toContain("100.0%");
    expect(html).toContain("缺少 MU 的有效行情");
    expect(html).not.toContain("Bar length");
  });

  it("keeps real quoted position values visible", () => {
    const html = renderWorkspace({ ...unpriced, price_kind: "futu_snapshot" });
    expect(html).toContain("987.65");
    expect(html).toContain("98,765");
    expect(html).not.toContain("缺少 MU 的有效行情");
  });

  it("names order records correctly instead of calling cancelled orders fills", () => {
    const html = renderWorkspace(unpriced, "order-history");
    expect(html).toContain("订单记录数");
    expect(html).not.toContain("成交笔数");
  });

  it("labels every scrollable account table and adds a narrow-screen scroll cue", async () => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const source = readFileSync(
      join(process.cwd(), "components/position-map/PositionMapWorkspace.tsx"),
      "utf8",
    );
    expect(source.match(/role="region"/g) ?? []).toHaveLength(5);
    expect(source.match(/<TableScrollHint label=\{text\.tableScrollHint\} \/>/g) ?? []).toHaveLength(5);
    expect(source).toContain("tableScrollHint: tableScrollHintText.en");
    expect(source).toContain("tableScrollHint: tableScrollHintText.zh");

    const html = renderWorkspace({ ...unpriced, price_kind: "futu_snapshot" });
    expect(html).toContain('aria-label="账户持仓"');
    expect(html).toContain("表格可左右滑动查看全部列");
    expect(html).toContain('role="region"');
  });
});
