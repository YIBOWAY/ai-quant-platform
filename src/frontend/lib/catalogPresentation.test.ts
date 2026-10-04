import { describe, expect, it } from "vitest";

import {
  localizedFactorDescription,
  localizedFactorName,
  localizedStrategyDescription,
  localizedStrategyName,
  localizedUniverseName,
} from "./catalogPresentation";

describe("catalog presentation", () => {
  it("prefers API Chinese strategy and factor names", () => {
    expect(
      localizedStrategyName(
        { id: "custom", name: "Custom English", display_name_zh: "自定义策略" },
        "zh",
      ),
    ).toBe("自定义策略");
    expect(
      localizedFactorName(
        {
          factor_id: "custom_factor",
          factor_name: "Custom factor",
          display_name_zh: "自定义因子",
        },
        "zh",
      ),
    ).toBe("自定义因子");
  });

  it("uses deterministic Chinese names for the four existing stock pools", () => {
    expect(localizedUniverseName({ id: "etf", name: "ETF Core" }, "zh")).toBe(
      "核心 ETF 股票池",
    );
    expect(localizedUniverseName({ id: "technology", name: "Technology" }, "zh")).toBe(
      "科技股股票池",
    );
    expect(localizedUniverseName({ id: "defense", name: "Defense" }, "zh")).toBe(
      "国防与航空航天股票池",
    );
    expect(localizedUniverseName({ id: "healthcare", name: "Healthcare" }, "zh")).toBe(
      "医疗保健股票池",
    );
  });

  it("never exposes English descriptions in the Chinese primary view", () => {
    expect(
      localizedFactorDescription(
        { factor_id: "momentum", description: "Close-to-close momentum." },
        "zh",
      ),
    ).toBe("衡量一段时间内价格涨跌的相对强弱。");
    expect(
      localizedFactorDescription(
        { factor_id: "future_factor", description: "Future English description." },
        "zh",
      ),
    ).toBe("已登记因子；英文技术说明已在中文主视图隐藏。对照原始编号时可查看技术信息。");
    expect(
      localizedStrategyDescription(
        { id: "cross_sectional_top_n", description: "Ranks a universe." },
        "zh",
      ),
    ).toBe("按多因子得分对股票池排序，持有得分最高的若干标的。");
  });
});
