import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const briefPagePath = path.join(process.cwd(), "app/brief/page.tsx");

function readBriefPage() {
  return readFileSync(briefPagePath, "utf8");
}

describe("/brief route contract", () => {
  it("uses the existing dashboard read-only fetch surface", () => {
    const source = readBriefPage();

    for (const getter of [
      "getCachedSettings",
      "getSymbols",
      "getFactors",
      "getBacktests",
      "getPaperRuns",
      "getCachedBriefPaperAccount",
      "getCachedBriefPaperAccountEquityCurve",
      "getCachedBriefPaperAccountPerformance",
      "getRecentRuns",
      "getAgentCandidates",
      "getNewsItems",
      "getOptionsDailyScanStatus",
      "getCachedBriefMarketDataHistory",
      "getServerLocale",
      "BriefPerformanceChart",
      "BriefPerformanceRangeSelector",
    ]) {
      expect(source).toContain(getter);
    }

    expect(source).toContain('getNewsItems({ take: 6, preference: "auto" })');
    expect(source).toContain("buildBriefAiNewsDigest");
    expect(source).not.toContain("getAiHotItems");

    for (const symbol of ["SPY", "QQQ", "SOXX", "IGV"]) {
      expect(source).toContain(`getCachedBriefMarketDataHistory("${symbol}"`);
    }
    expect(source).not.toContain("getMarketDataHistory(");
    expect(source).not.toContain("getPaperAccountPerformance(");
    expect(source).not.toContain("getPaperAccount(");
    expect(source).not.toContain("getPaperAccountEquityCurve(");
  });

  it("does not call the provider-coupled health route during SSR", () => {
    expect(readBriefPage()).not.toContain("/api/health");
  });

  it("keeps the morning lede free of implementation-template meta language", () => {
    const source = readBriefPage();
    for (const banned of [
      "平台模板提示",
      "确定性模板",
      "deterministic template",
      "template lede",
    ]) {
      expect(source).not.toContain(banned);
    }
  });

  it("includes the Asia Radar summary through the same fail-closed cache path", () => {
    const source = readBriefPage();
    expect(source).toContain("getCachedAsiaRadarSummary");
    expect(source).toContain("buildAsiaRadarNote");
    expect(source).toContain("@/lib/briefAsiaRadarNote");
  });

  it("reuses dashboard formatting, run-link, and locale helpers", () => {
    const source = readBriefPage();

    for (const helper of [
      "formatMoney",
      "formatPercent",
      "dashboardRunHref",
      "dashboardRunKindLabel",
      "dashboardRunSummary",
      "localizePath",
    ]) {
      expect(source).toContain(helper);
    }
    expect(source).toContain("masterPerformance.apiError");
  });

  it("stays isolated from navigation, backend mutation, and generated-copy APIs", () => {
    const source = readBriefPage();

    expect(source).toContain("paper-ink");
    expect(source).toContain("text-ink");
    expect(source).toContain("font-editorial-display");
    expect(source).toContain("Daily Morning Brief");
    expect(source).toContain("每日晨报");
    expect(source).toContain("PAPER VS SPY · QQQ");
    expect(source).toContain("Futu QFQ daily closes");
    expect(source).toContain("account ledger");
    expect(source).toContain("selectedRange");
    expect(source).toContain("平台市场手记");
    expect(source).toContain("Platform recorded backtest");
    expect(source).toContain("Options daily scan");
    expect(source).toContain("safeExternalUrl(item.url)");
    expect(source).toContain("target=\"_blank\"");
    expect(source).toContain("rel=\"noreferrer noopener\"");
    expect(source).toContain("Compiled from platform facts");
    expect(source).toContain("live trading");
    expect(source).toContain("never implied active");

    // Manual archive control is gone: archiving is automated and the sidebar
    // owns archive navigation, so the page must not rebuild the save surface.
    expect(source).not.toContain("BriefArchiveControl");
    expect(source).not.toContain("getLatestBriefIssue");
    expect(source).not.toContain("getBriefIssueList");
    expect(source).not.toContain("archivePayload");
    expect(source).not.toContain("sourceWatermark");
    expect(source).not.toContain("stripTitle");

    expect(source).not.toContain("Hermes completed backtest");
    expect(source).not.toContain("lede prepared by Hermes");

    expect(source).not.toContain("navConfig");
    expect(source).not.toContain("apiRequest");
    expect(source).not.toContain("fetch(");
    expect(source).not.toContain("POST");
    expect(source).not.toContain("balance history proxy");
    expect(source).not.toContain("generateCopy");
    expect(source).not.toContain("generateWithLlm");
    expect(source).not.toContain("llm");
    expect(source).not.toContain("getBacktestDetail");
    expect(source).not.toContain("strategy={strategyCurve}");
    expect(source).not.toContain("text.symbols");
    expect(source).not.toContain("text.factors");
    expect(source).not.toContain("text.candidates");
    expect(source).not.toContain("text.hermesReady");
    expect(source).not.toContain("RunLog runs=");
  });
});
