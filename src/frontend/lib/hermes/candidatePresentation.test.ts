import { describe, expect, it } from "vitest";

import { candidatePresentation } from "./candidatePresentation";

describe("candidatePresentation", () => {
  it("gives the two existing remote candidates stable Chinese names without exposing ids", () => {
    expect(
      candidatePresentation(
        {
          candidate_id: "artifact-d489583fb04bdc04",
          factor_id: "d34_a729eaa08c87d0e9a03b5e16",
          objective: "Discover and falsify momentum.",
          universe: ["SPY", "QQQ", "NVDA", "AAPL"],
          status: "hung",
        },
        "zh",
      ),
    ).toEqual({
      name: "21 日横截面动量策略",
      summary: "在 SPY、QQQ、NVDA、AAPL 中比较 21 日横截面动量，模拟运行中并按每日信号执行。",
    });

    expect(
      candidatePresentation(
        {
          candidate_id: "artifact-a604ad9ad2792c32",
          factor_id: "d34_4eb6fc0baf6a51693334004f",
          objective: "Discover and falsify mean reversion.",
          universe: ["SPY", "QQQ", "IWM", "DIA"],
          status: "verified",
        },
        "zh",
      ).name,
    ).toBe("低配置横截面选股因子");
  });

  it("prefers producer-supplied Chinese copy and uses a Chinese-only fallback for future rows", () => {
    expect(
      candidatePresentation(
        {
          candidate_id: "artifact-future",
          factor_id: "d34_future_hash",
          display_name_zh: "成交量异动因子",
          summary_zh: "比较近期成交量变化。",
          universe: ["SPY", "QQQ"],
          status: "verified",
        },
        "zh",
      ),
    ).toEqual({ name: "成交量异动因子", summary: "比较近期成交量变化。" });

    const fallback = candidatePresentation(
      {
        candidate_id: "artifact-0123456789abcdef",
        factor_id: "d34_0123456789abcdef",
        objective: "English text must not leak into the Chinese primary view.",
        universe: ["SPY", "QQQ"],
        status: "verified",
      },
      "zh",
    );
    expect(fallback).toEqual({
      name: "SPY、QQQ 标的因子候选",
      summary: "该因子已完成研究验证，尚未启用模拟运行。",
    });
    expect(`${fallback.name}${fallback.summary}`).not.toMatch(/artifact|d34_|English|[a-f0-9]{16}/i);
  });

  it("explains why a research-verified candidate cannot start simulated running", () => {
    expect(
      candidatePresentation(
        {
          candidate_id: "artifact-a604ad9ad2792c32",
          status: "verified",
          activation_eligibility: {
            eligible: false,
            reason: "cost_sensitivity_failed",
          },
        },
        "zh",
      ).activationNote,
    ).toBe("仅供研究复核；计入交易成本后不适合模拟运行。");

    expect(
      candidatePresentation(
        {
          candidate_id: "artifact-a604ad9ad2792c32",
          status: "verified",
          activation_eligibility: {
            eligible: false,
            reason: "cost_sensitivity_failed",
          },
        },
        "en",
      ).activationNote,
    ).toBe(
      "Research review only; not suitable for simulated running after trading costs.",
    );
  });

  it("explains incomplete current family ahead of the resulting unfunded grade", () => {
    const result = candidatePresentation({ activation_eligibility: { eligible: false,
      reason: "new_capital_quality_failed:family_evidence_incomplete,unfunded_tier,dsr_failed",
    } }, "zh");
    expect(result.activationNote).toContain("同一试验族还有缺失证据");
    expect(result.activationNote).toContain("补齐原件后重新评价");
  });

  it("keeps raw factor ids out of the English title and explains every fixed blocker", () => {
    const fallback = candidatePresentation(
      {
        factor_id: "d34_private_hash_like_factor",
        universe: ["SPY", "QQQ"],
        status: "verified",
      },
      "en",
    );
    expect(fallback.name).toBe("SPY, QQQ factor candidate");
    expect(fallback.name).not.toContain("d34_");

    const expected: Record<string, string> = {
      dsr_performance_required: "缺少可用于模拟运行准入的收益序列",
      dsr_failed: "统计稳健性未通过当前要求",
      correlated_duplicate: "与正在运行的策略过于相似",
      cost_unmeasured_blocked: "缺少交易成本评估",
      cost_sensitivity_failed: "计入交易成本后不适合模拟运行",
    };
    for (const [reason, message] of Object.entries(expected)) {
      expect(
        candidatePresentation(
          {
            activation_eligibility: { eligible: false, reason },
          },
          "zh",
        ).activationNote,
      ).toContain(message);
    }
  });
});
