import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { PaperRuntimeStatus } from "@/lib/api";
import { PaperRuntimeEvidence, paperRuntimeLabel } from "./PaperRuntimeEvidence";

const runtime: PaperRuntimeStatus = {
  checked_at: "2026-09-23T04:00:00Z", sleeve_id: "artificial-sleeve", config_id: "test-config",
  config_version: 1, enabled: true,
  configuration: { status: "blocked", reason: "strategy_algorithm_source_mismatch" },
  signal: { status: "blocked", reason: "strategy_algorithm_source_mismatch", signal_date: "2026-09-15" },
  fills: { status: "verified", count: 0, days: 0 },
  valuation: { status: "cash_only", reason: "no_committed_fills" },
};

describe("paper lifecycle evidence", () => {
  it("shows version blockage and zero fills ahead of the old generated signal", () => {
    const html = renderToStaticMarkup(<PaperRuntimeEvidence runtime={runtime} locale="zh"/>);
    expect(paperRuntimeLabel(runtime, "zh")).toBe("已启用 · 信号受阻");
    expect(html).toContain("因版本失配未生成信号");
    expect(html).toContain("0 笔已提交成交");
    expect(html).toContain("纯现金；尚无成交后的策略收益");
    expect(html).not.toContain("已有保存信号");
  });

  it("does not claim zero fills when the journal evidence is unavailable", () => {
    const unknown = { ...runtime, fills: { status: "unavailable", count: null, days: null }, valuation: { status: "not_checked" } };
    const html = renderToStaticMarkup(<PaperRuntimeEvidence runtime={unknown} locale="zh"/>);
    expect(html).toContain("成交账证据未核验");
    expect(html).not.toContain("0 笔已提交成交");
    expect(html).not.toContain("纯现金");
  });

  it("keeps a compatible saved signal separate from fill and valuation proof", () => {
    const compatible = { ...runtime, configuration: { status: "compatible" }, signal: { status: "generated", signal_date: "2026-09-23" } };
    const html = renderToStaticMarkup(<PaperRuntimeEvidence runtime={compatible} locale="en"/>);
    expect(html).toContain("Saved signal · 2026-09-23");
    expect(html).toContain("0 committed fills");
    expect(html).not.toContain("signal blocked");
  });
});
