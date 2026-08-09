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
      "getCachedHealth",
      "getSymbols",
      "getFactors",
      "getBacktests",
      "getPaperRuns",
      "getPaperAccount",
      "getPaperAccountEquityCurve",
      "getPaperAccountPerformance",
      "getRecentRuns",
      "getAgentCandidates",
      "getNewsItems",
      "getOptionsDailyScanStatus",
      "getMarketDataHistory",
      "getServerLocale",
      "getLatestBriefIssue",
      "BriefArchiveControl",
      "BriefPerformanceChart",
      "BriefPerformanceRangeSelector",
    ]) {
      expect(source).toContain(getter);
    }

    expect(source).toContain('getNewsItems({ take: 6, preference: "auto" })');
    expect(source).toContain("buildBriefAiNewsDigest");
    expect(source).not.toContain("getAiHotItems");

    for (const symbol of ["SPY", "QQQ", "SOXX", "IGV"]) {
      expect(source).toContain(`getMarketDataHistory("${symbol}"`);
    }
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
      "resolveBriefArchiveBlockedReason",
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
    expect(source).toContain("buildBriefPerformanceSnapshot");
    expect(source).toContain("selectedRange");
    expect(source).toContain("平台市场手记");
    expect(source).toContain("Platform recorded backtest");
    expect(source).toContain("Options daily scan");
    expect(source).toContain("safeExternalUrl(item.url)");
    expect(source).toContain("target=\"_blank\"");
    expect(source).toContain("rel=\"noreferrer noopener\"");
    expect(source).toContain("Compiled from platform facts");
    expect(source).toContain("template");
    expect(source).toContain("live trading");
    expect(source).toContain("never implied active");
    expect(source).toContain("payload={archivePayload}");
    expect(source).toContain("sourceWatermark={sourceWatermark}");
    expect(source).toContain("archiveBlockedReason");

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
