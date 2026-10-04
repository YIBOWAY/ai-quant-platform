import type { Locale } from "@/lib/locale";

export type Tone = "neutral" | "success" | "warning" | "danger" | "info";

export function formatDateTime(value: string, locale: Locale) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Shanghai",
  }).format(parsed);
}

export function formatMoney(
  value: number | null | undefined,
  currency: string | null | undefined,
  locale: Locale,
) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  try {
    return new Intl.NumberFormat(locale === "zh" ? "zh-CN" : "en-US", {
      style: "currency",
      currency: currency || "USD",
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${currency || "USD"} ${value.toFixed(2)}`;
  }
}

export function formatPercent(value: number | null | undefined, locale: Locale) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  return new Intl.NumberFormat(locale === "zh" ? "zh-CN" : "en-US", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

export function formatDecimal(value: number | null | undefined, digits: number) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  return value.toFixed(digits);
}

export function formatDuration(seconds: number, locale: Locale) {
  const units =
    locale === "zh"
      ? { day: "天", hour: "小时", minute: "分钟", second: "秒" }
      : { day: "days", hour: "hours", minute: "minutes", second: "seconds" };
  if (seconds % 86_400 === 0) return `${seconds / 86_400} ${units.day}`;
  if (seconds % 3_600 === 0) return `${seconds / 3_600} ${units.hour}`;
  if (seconds % 60 === 0) return `${seconds / 60} ${units.minute}`;
  return `${seconds} ${units.second}`;
}

export function safeDomId(value: string) {
  return value.replace(/[^a-zA-Z0-9_-]/g, "-");
}

export function assertNever(value: never): never {
  throw new Error(`Unsupported Hermes artifact variant: ${JSON.stringify(value)}`);
}

export function humanizeReasonCode(code: string, locale: Locale) {
  const labels =
    locale === "zh"
      ? {
          never_run: "从未运行",
          freshness_budget_exceeded: "超过时效窗口",
          last_attempt_degraded: "最近一次运行已降级",
          no_successful_run: "尚无成功运行",
          read_only_research_summary: "只读研究汇总",
          historical_relationship_not_forecast: "历史关系并非预测",
          partial_series_gap: "序列存在缺口",
          degraded_feed: "降级 feed",
          "no risk policy thresholds configured": "未配置风险阈值",
          no_risk_policy_thresholds_configured: "未配置风险阈值",
          "account base currency only no fx conversion": "仅按账户本位币统计，未做汇率换算",
          account_base_currency_only_no_fx_conversion: "仅按账户本位币统计，未做汇率换算",
          "price freshness age unavailable": "无法确认价格时效",
          price_freshness_age_unavailable: "无法确认价格时效",
          "current exposure uses single snapshot": "当前敞口基于单一快照",
          current_exposure_uses_single_snapshot: "当前敞口基于单一快照",
        }
      : {
          never_run: "Never run",
          freshness_budget_exceeded: "Freshness window exceeded",
          last_attempt_degraded: "Latest attempt was degraded",
          no_successful_run: "No successful run yet",
          read_only_research_summary: "Read-only research summary",
          historical_relationship_not_forecast: "Historical relationship is not a forecast",
          partial_series_gap: "Partial series gap",
          degraded_feed: "Degraded feed",
        };
  if (code in labels) return labels[code as keyof typeof labels];
  if (locale === "zh" && !/[\u3400-\u9fff]/u.test(code)) return "其他技术限制";
  return code.replaceAll("_", " ");
}

export function artifactStatusLabel(status: string, locale: Locale): string {
  const labels: Record<string, string> =
    locale === "zh"
      ? {
          available: "可用",
          degraded: "已降级",
          unavailable: "不可用",
          approved: "已批准",
          completed: "已完成",
          fresh: "当前有效",
          stale: "已过期",
          failed: "失败",
          pending: "待处理",
        }
      : {
          available: "Available",
          degraded: "Degraded",
          unavailable: "Unavailable",
          approved: "Approved",
          completed: "Completed",
          fresh: "Current",
          stale: "Stale",
          failed: "Failed",
          pending: "Pending",
        };
  return labels[status] ?? (locale === "zh" ? "状态待确认" : status);
}

export function qualityTone(quality: string): Tone {
  if (quality === "available") return "success";
  if (quality === "degraded") return "warning";
  if (quality === "unavailable") return "danger";
  return "neutral";
}

export function sourceStatusTone(status: string): Tone {
  if (status === "available") return "success";
  if (status === "degraded") return "warning";
  if (status === "unavailable") return "danger";
  if (status === "empty") return "neutral";
  return "neutral";
}

export function automationStatusTone(
  status: "fresh" | "stale" | "failed" | "never_run",
): Tone {
  if (status === "fresh") return "success";
  if (status === "failed") return "danger";
  return "warning";
}
