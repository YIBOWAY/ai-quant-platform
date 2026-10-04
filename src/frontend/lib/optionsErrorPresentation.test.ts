import { describe, expect, it } from "vitest";

import { ApiClientError } from "./apiClient";
import { optionsErrorMessage } from "./optionsErrorPresentation";

describe("optionsErrorMessage", () => {
  it("distinguishes a wrong bullish target from stale market data", () => {
    expect(optionsErrorMessage(new ApiClientError("[invalid_buy_side_target_price] bullish target price must be above current spot", 422), "zh"))
      .toBe("目标价必须高于当前股价。这是看涨策略，请修改目标价后重新分析。");
    expect(optionsErrorMessage(new ApiClientError("[option_quote_stale] quote expired", 503), "zh"))
      .toContain("期权合约报价已过期");
    expect(optionsErrorMessage(new ApiClientError("invalid parameters", 422), "zh"))
      .toContain("输入参数");
  });
  it("maps stale IV screen failures to actionable Chinese copy", () => {
    expect(
      optionsErrorMessage(
        new ApiClientError(
          "[invalid_options_screen] atm30_iv_quote_stale",
          422,
        ),
        "zh",
      ),
    ).toBe("期权隐含波动率报价已过期。可以立即更新，自动流程每日 22:00 运行。");
  });

  it("maps legacy recommendation snapshots without exposing internal codes", () => {
    const message = optionsErrorMessage(
      new Error("[legacy_snapshot_contract] unavailable"),
      "zh",
    );
    expect(message).toBe("旧版快照，可以立即更新；自动流程每日 22:00 运行。");
    expect(message).not.toContain("legacy_snapshot_contract");
  });

  it("names an API-cleared stale snapshot instead of the generic unavailable copy", () => {
    const zhMessage = optionsErrorMessage("snapshot_stale", "zh");
    expect(zhMessage).toBe(
      "快照已过期，今日尚无新鲜可交易推荐；请立即更新，自动流程每日 22:00 运行。",
    );
    expect(zhMessage).not.toBe("期权数据暂不可用，请稍后重试。");
    expect(zhMessage).toContain("每日 22:00");
    const enMessage = optionsErrorMessage("snapshot_stale", "en");
    expect(enMessage).not.toContain("snapshot_stale");
    expect(enMessage).toContain("22:00");
  });

  it("keeps the exact stale-snapshot key from hijacking the IV-stale substring branch", () => {
    expect(
      optionsErrorMessage("[invalid_options_screen] atm30_iv_quote_stale", "zh"),
    ).toBe("期权隐含波动率报价已过期。可以立即更新，自动流程每日 22:00 运行。");
    expect(optionsErrorMessage("atm30_iv_quote_stale", "zh")).toBe(
      "期权隐含波动率报价已过期。可以立即更新，自动流程每日 22:00 运行。",
    );
  });

  it.each([
    ["delta_outside_range", "Delta 不在 0.15–0.35 范围"],
    ["earnings_data_missing", "缺少财报日期"],
    ["earnings_within_dte", "到期前存在财报"],
    ["ex_dividend_data_missing", "备兑看涨缺少除息或股息证据"],
    ["extrinsic_value_invalid", "外在价值无效"],
    ["implied_volatility_missing", "缺少隐含波动率"],
    ["mid_below_minimum", "权利金低于 0.05 美元"],
    ["mid_missing", "缺少有效中间价"],
    ["open_interest_below_minimum", "未平仓量低于 100"],
    ["quote_stale", "期权报价已过期"],
    ["spread_above_maximum", "买卖价差超过中间价的 5%"],
    ["spread_missing", "缺少有效买卖价差"],
    ["ValueError", "期权数据校验失败"],
  ])("maps recommendation exclusion %s to specific Chinese copy", (reason, expected) => {
    expect(optionsErrorMessage(reason, "zh")).toBe(expected);
  });

  it("keeps a bounded generic message for unknown Chinese errors", () => {
    expect(optionsErrorMessage(new Error("provider exploded internally"), "zh")).toBe(
      "期权数据暂不可用，请稍后重试。",
    );
  });
});
