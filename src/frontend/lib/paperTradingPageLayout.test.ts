import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const root = process.cwd();
const source = (relative: string) =>
  readFileSync(path.join(root, relative), "utf8");

/**
 * Layout contract for the redesigned /paper-trading live-account view.
 *
 * The redesign established a strict visual hierarchy:
 *   1. an unboxed account hero (NAV + P&L chip + inline metrics + safety pills),
 *   2. compact TerminalTable-based holdings / pending-order sections,
 *   3. low-frequency ops panels collapsed by default,
 *   4. the manual/advanced action rail beside the content instead of boxed
 *      cards stacked on top of each other.
 * These assertions pin the hierarchy and the bilingual labels so a future
 * refactor cannot silently re-introduce card-in-card stacking or drop a
 * locale.
 */
describe("paper-trading live account layout", () => {
  const page = source("app/paper-trading/page.tsx");

  it("leads with an unboxed account hero instead of a tinted card stack", () => {
    expect(page).toContain('data-paper-account-hero="true"');
    // The hero must not resurrect the card-in-card MetricStat grid.
    expect(page).not.toContain('Card tone="success"');
    // NAV is the single dominant number on the page.
    expect(page).toContain("text-3xl");
  });

  it("renders holdings and pending orders as compact terminal tables", () => {
    expect(page).toContain('data-paper-holdings="true"');
    expect(page).toContain('data-paper-pending-orders="true"');
    expect(page).toContain("TerminalTable");
  });

  it("keeps low-frequency strategy/ops panels collapsed and below the fold", () => {
    // Sleeves panel ships collapsed-by-default; ops opens only on exceptions.
    const sleeves = source("components/forms/PaperStrategySleevesPanel.tsx");
    const ops = source("components/forms/PaperStrategyOpsPanel.tsx");
    expect(sleeves).toContain('data-paper-strategy-sleeves="collapsed-by-default"');
    expect(ops).toContain('data-paper-strategy-ops="exception-first"');
    // Both stay mounted after the holdings section in the page stack.
    expect(page.indexOf("HoldingsSection")).toBeLessThan(
      page.indexOf("<PaperStrategySleevesPanel"),
    );
    expect(page.indexOf("<PaperStrategyOpsPanel")).toBeGreaterThan(
      page.indexOf("<PaperStrategySleevesPanel"),
    );
  });

  it("keeps the manual action rail and the bilingual tab labels stable", () => {
    expect(page).toContain("<AccountTradePanel");
    for (const label of [
      'tabLive: "Live Account"',
      'tabReplay: "Historical Replay"',
      'tabLive: "当前账户"',
      'tabReplay: "历史回放"',
    ]) {
      expect(page).toContain(label);
    }
  });

  it("keeps bilingual labels for the hero and the new table columns in sync", () => {
    for (const pair of [
      ['accountValue: "Account Value"', 'accountValue: "账户净值"'],
      ['accountCash: "Available Cash"', 'accountCash: "可用现金"'],
      ['symbol: "Symbol"', 'symbol: "标的"'],
      ['quantity: "Qty (sh)"', 'quantity: "数量（股）"'],
      ['sourceMix: "Source Mix"', 'sourceMix: "来源拆分"'],
      ['holdingsEmpty: "No open positions.', 'holdingsEmpty: "暂无持仓。'],
      ['openMap: "Open position map"', 'openMap: "打开持仓地图"'],
    ]) {
      expect(page).toContain(pair[0]);
      expect(page).toContain(pair[1]);
    }
  });

  it("keeps the position-map escape hatch and the replay deep-link contract", () => {
    expect(page).toContain('view === "map"');
    expect(page).toContain("PositionMapPageContent");
    expect(page).toContain("openAria: (id: string)");
    expect(page).toContain("aria-label={text.openAria(latestRun.id)}");
  });

  it("pairs every scrollable table with a region role and a sideways-scroll cue", () => {
    // Both TerminalTables take the shared hint node...
    expect(page.match(/scrollHint=\{<TableScrollHint label=\{tableScrollHintText\[locale\]\} \/>\}/g) ?? [])
      .toHaveLength(2);
    // ...and the bare run-history table gets the region wrapper and its own cue.
    expect(page).toContain('aria-label={text.runHistoryTitle}');
    expect(page.match(/<TableScrollHint label=\{tableScrollHintText\[locale\]\} \/>/g) ?? [])
      .toHaveLength(3);
    expect(page.match(/role="region"/g) ?? []).toHaveLength(1);
  });
});
