import { describe, expect, it } from "vitest";

import { buildBriefSummary } from "./briefSummary";

describe("buildBriefSummary", () => {
  it("turns complete Chinese market facts into a quantified editorial summary", () => {
    const summary = buildBriefSummary({
      locale: "zh",
      equity: "$1,005,540",
      paperWeekReturn: "▲ 0.55%",
      markets: [
        { symbol: "SPY", changePct: 0.0012 },
        { symbol: "QQQ", changePct: -0.004 },
        { symbol: "SOXX", changePct: -0.0205 },
        { symbol: "IGV", changePct: 0.0333 },
      ],
      digestTitles: ["OpenAI 发布新的企业智能体能力", "芯片行业资本开支继续增长"],
    });

    expect(summary.marketNote).toBe(
      "四个观察 ETF 中 2 只上涨，宽基方向分化；IGV 领涨（▲ 3.33%），SOXX 领跌（▼ 2.05%）。软件相对半导体领先 5.38 个百分点，行业表现分化明显。",
    );
    expect(summary.lede).toBe(
      "今晨模拟盘权益为 $1,005,540，近 7 日收益 ▲ 0.55%。市场方面，四个观察 ETF 中 2 只上涨，宽基方向分化；IGV 领涨（▲ 3.33%），SOXX 领跌（▼ 2.05%）。软件相对半导体领先 5.38 个百分点，行业表现分化明显。AI 情报共 2 条，头条关注「OpenAI 发布新的企业智能体能力」。",
    );
    expect(summary.lede).not.toContain("模板");
  });

  it("fails closed when the market set is incomplete", () => {
    const summary = buildBriefSummary({
      locale: "zh",
      equity: "--",
      paperWeekReturn: "--",
      markets: [
        { symbol: "SPY", changePct: 0.0012 },
        { symbol: "QQQ" },
        { symbol: "SOXX", changePct: -0.0205 },
        { symbol: "IGV" },
      ],
      digestTitles: [],
    });

    expect(summary.marketNote).toBe(
      "四个观察 ETF 中仅 2 只有有效涨跌数据，暂不判断市场广度和行业相对强弱。",
    );
    expect(summary.lede).toContain("AI 情报源暂无可用条目");
    expect(summary.lede).not.toContain("领先");
  });

  it("renders the same evidence in English without template language", () => {
    const summary = buildBriefSummary({
      locale: "en",
      equity: "$1,005,540",
      paperWeekReturn: "▲ 0.55%",
      markets: [
        { symbol: "SPY", changePct: 0.0012 },
        { symbol: "QQQ", changePct: -0.004 },
        { symbol: "SOXX", changePct: -0.0205 },
        { symbol: "IGV", changePct: 0.0333 },
      ],
      digestTitles: ["OpenAI expands enterprise agent capabilities"],
    });

    expect(summary.marketNote).toContain("Software led semiconductors by 5.38 percentage points");
    expect(summary.lede).toContain("led by “OpenAI expands enterprise agent capabilities”");
    expect(summary.lede.toLowerCase()).not.toContain("template");
  });
});
