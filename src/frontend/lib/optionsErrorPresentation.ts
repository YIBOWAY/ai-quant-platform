import type { Locale } from "./locale";
import { ApiClientError } from "./apiClient";

function rawMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error ?? "");
}

export function optionsErrorMessage(error: unknown, locale: Locale): string {
  const raw = rawMessage(error);
  const normalized = raw.toLowerCase();
  if (normalized.includes("positive_integer_shares_required")) {
    return locale === "zh" ? "本工具仅支持正整数股数，请输入 1 股或以上的整数；不会自动取整。"
      : "This tool supports positive integer share counts only; fractional shares are not rounded.";
  }
  if (normalized.includes("nonstandard_option_contract_unsupported")) {
    return locale === "zh" ? "本工具仅支持每张对应 100 股的标准期权；当前合约为非标准或规格未知，未生成对冲结构。"
      : "Only standard 100-share options are supported. No structure was created for a nonstandard or invalid contract size.";
  }
  if (normalized.includes("positive_finite_hedge_prices_required")) {
    return locale === "zh" ? "持仓成本和当前股价必须是大于零的有效数字。"
      : "Cost basis and spot price must be finite positive values.";
  }

  if (normalized.includes("invalid_buy_side_target_price")) {
    return locale === "zh"
      ? "目标价必须高于当前股价。这是看涨策略，请修改目标价后重新分析。"
      : "The target must be above the current stock price for this bullish strategy. Change the target and analyze again.";
  }
  if (normalized.includes("option_quote_stale")) {
    return locale === "zh"
      ? "期权合约报价已过期，尚不能计算当前情景。请在有新报价后重新分析；修改目标价不能解决报价过期。"
      : "The option contract quote is stale. Analyze again when a fresh quote is available; changing the target does not fix stale data.";
  }
  if (normalized.includes("insufficient_fear_inputs")) {
    return locale === "zh"
      ? "恐慌评分缺少必要指标，暂不能给出价差入场信号。请先查看恐慌评分中的数据缺项。"
      : "Required fear-score inputs are missing. No spread-entry signal can be calculated; review the missing inputs first.";
  }

  if (normalized.includes("legacy_snapshot_contract")) {
    return locale === "zh"
      ? "旧版快照，可以立即更新；自动流程每日 22:00 运行。"
      : "This is a legacy snapshot. Update it now, or wait for the daily 22:00 run.";
  }
  if (
    normalized.includes("atm30_iv_quote_stale") ||
    normalized.includes("iv_history_stale") ||
    normalized.includes("options_snapshot_stale")
  ) {
    return locale === "zh"
      ? "期权隐含波动率报价已过期。可以立即更新，自动流程每日 22:00 运行。"
      : "The options implied-volatility quote is stale. Update it now, or wait for the daily 22:00 run.";
  }
  if (
    normalized.includes("atm30_iv_quote_future") ||
    normalized.includes("atm30_iv_quote_missing")
  ) {
    return locale === "zh"
      ? "期权隐含波动率数据的时间点无效，请等待下一次数据刷新后重试。"
      : "The options implied-volatility timestamp is invalid. Retry after the next data refresh.";
  }
  if (locale === "zh") {
    const reasons: Record<string, string> = {
      delta_outside_range: "Delta 不在 0.15–0.35 范围",
      earnings_data_missing: "缺少财报日期",
      earnings_in_dte_window: "到期前存在财报",
      earnings_within_dte: "到期前存在财报",
      ex_dividend_data_missing: "备兑看涨缺少除息或股息证据",
      ex_dividend_date_past: "只有历史除息日，下一次除息日期未知",
      invalid_recommendation_snapshot: "旧快照未通过当前计算校验，请点击立即更新生成新结果",
      extrinsic_value_invalid: "外在价值无效",
      implied_volatility_missing: "缺少隐含波动率",
      missing_quote: "缺少有效期权报价",
      mid_below_minimum: "权利金低于 0.05 美元",
      mid_missing: "缺少有效中间价",
      open_interest_below_minimum: "未平仓量低于 100",
      quote_stale: "期权报价已过期",
      real_futu_snapshot_unavailable: "缺少真实 Futu 快照",
      snapshot_stale: "快照已过期，今日尚无新鲜可交易推荐；请立即更新，自动流程每日 22:00 运行。",
      spread_above_maximum: "买卖价差超过中间价的 5%",
      spread_missing: "缺少有效买卖价差",
      ValueError: "期权数据校验失败",
      universe_scan_incomplete: "扫描标的范围不完整",
      iv_rank_missing: "缺少隐含波动率排名",
      insufficient_ivr_history: "隐含波动率历史样本不足",
      non_positive_excess_ev: "期望赔付不低于权利金（物理 EV 不为正）",
    };
    const exactReason = reasons[raw.trim()];
    if (exactReason) return exactReason;
  }
  if (locale === "en") {
    const reasons: Record<string, string> = {
      non_positive_excess_ev:
        "Expected payout meets or exceeds the premium (non-positive physical EV)",
      snapshot_stale:
        "The snapshot is stale; there are no fresh tradeable recommendations today. Update now — the automatic job runs daily at 22:00.",
    };
    const exactReason = reasons[raw.trim()];
    if (exactReason) return exactReason;
  }
  if (error instanceof ApiClientError && error.status === 422) {
    return locale === "zh"
      ? "输入参数未通过校验，请检查目标价、目标日期和必填项目后重新分析。"
      : "The inputs failed validation. Check the target price, target date and required fields before analyzing again.";
  }
  if (locale === "zh") return "期权数据暂不可用，请稍后重试。";
  return raw || "Options data is temporarily unavailable. Try again later.";
}

/**
 * Human label for an options scan exclusion reason code. Falls back to the
 * shared error presentation so raw codes such as `snapshot_stale: 1` never
 * reach the reader.
 */
export function optionsReasonLabel(reason: string, locale: Locale): string {
  if (reason === "ticker_concentration_limit") {
    return locale === "zh" ? "按每标的最多 2 条去重" : "Maximum 2 contracts per symbol";
  }
  if (reason === "legacy_snapshot_contract") {
    return locale === "zh" ? "旧版快照格式" : "legacy snapshot format";
  }
  if (locale === "zh") {
    const labels: Record<string, string> = {
      eligible_contracts_below_limit: "符合条件的合约少于 20 条",
      ticker_scan_failed: "部分标的扫描失败",
      universe_scan_incomplete: "未完全覆盖跟踪标的",
      provider_failed: "行情数据源请求失败",
    };
    if (labels[reason]) return labels[reason];
  }
  return optionsErrorMessage(reason, locale);
}
