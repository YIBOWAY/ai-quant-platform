import type { Locale } from "@/lib/locale";
import type { MarketRiskResponse } from "@/lib/marketCrossSection";

const names = {
  zh: { trend_200d: "相对 200 日均线", drawdown_252d: "距 252 日最高收盘", vix_level: "波动水平", vix_change: "单日变化", vix_term: "期限结构" },
  en: { trend_200d: "Distance from 200D MA", drawdown_252d: "Below 252D closing high", vix_level: "Volatility level", vix_change: "One-session change", vix_term: "Term structure" },
} as const;

const reasons: Record<string, [string, string]> = {
  below_200dma: ["跌破长期均线", "Below long-term trend"],
  above_200dma: ["位于长期均线上方", "Above long-term trend"],
  extended_above_200dma: ["上涨偏离较大，仅作背景", "Extended upward; context only"],
  drawdown_pressure: ["回撤达到观察阈值", "Drawdown threshold reached"],
  drawdown_below_threshold: ["回撤未达到观察阈值", "Drawdown below threshold"],
  volatility_elevated: ["隐含波动水平较高", "Elevated implied volatility"],
  volatility_below_threshold: ["波动水平未达到阈值", "Volatility below threshold"],
  volatility_rising: ["波动快速升温", "Volatility rising quickly"],
  volatility_change_below_threshold: ["单日升幅未达到阈值", "Daily rise below threshold"],
  term_inverted: ["短期波动不低于三个月", "Short-term volatility at or above three-month"],
  term_upward: ["短期波动低于三个月", "Short-term volatility below three-month"],
  price_stale: ["价格未更新，无法判断", "Price history is stale"],
  insufficient_history: ["历史长度不足", "Insufficient history"],
  invalid_price: ["价格数据无效", "Invalid price data"],
  benchmark_not_in_basket: ["当前观察范围未包含此基准", "Benchmark not in the selected group"],
  missing_history: ["缺少历史数据", "History unavailable"],
  vix_cache_unreadable: ["波动缓存无法读取", "Volatility cache unreadable"],
  invalid_observation: ["观测值无效", "Invalid observation"],
  volatility_stale: ["波动数据过期", "Volatility history is stale"],
  nonconsecutive_sessions: ["缺少前一个交易日", "Previous trading session unavailable"],
  session_mismatch: ["VIX 与 VIX3M 日期不一致", "VIX and VIX3M dates do not match"],
};

export function MarketRiskPanel({ risk, locale }: { risk?: MarketRiskResponse | null; locale: Locale }) {
  const zh = locale === "zh";
  const label = risk?.status === "attention"
    ? (zh ? "有压力信号" : "Pressure observed")
    : risk?.status === "normal"
      ? (zh ? "未触发观察规则" : "No observation threshold reached")
      : (zh ? "资料不齐，无法完整判断" : "Incomplete evidence");
  return (
    <section className="border-b border-border-subtle pb-6" data-market-risk={risk?.status ?? "unavailable"} aria-label={zh ? "市场风险观察" : "Market risk observations"}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">{zh ? "市场风险观察" : "Market risk observations"}</h2>
          <p className="mt-1 text-xs leading-5 text-text-secondary">{zh ? "先看趋势失守、回撤和波动压力，再看下方谁在走强。" : "Check trend, drawdown and volatility pressure before comparing relative strength."}</p>
        </div>
        <span role="status" className={`rounded-md px-3 py-2 text-xs ${risk?.status === "attention" ? "bg-warning/10 text-warning" : "bg-bg-surface text-text-secondary"}`}>{label}</span>
      </div>
      {!risk ? <p className="mt-4 text-sm text-text-secondary">{zh ? "尚未取得风险输入；不能据此判断市场正常。" : "Risk inputs are unavailable; this does not establish normal market conditions."}</p> : <>
        <p className="mt-4 text-xs text-text-secondary">
          {zh ? `以 ${risk.expected_session} 美股收盘为基准 · ${risk.attention_count} 项触发 · ${risk.unavailable_count} 项无法判断` : `Reference: US close ${risk.expected_session} · ${risk.attention_count} triggered · ${risk.unavailable_count} unavailable`}
        </p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[620px] text-left text-xs">
            <thead className="border-b border-border-subtle text-text-secondary"><tr>
              <th className="py-3 pr-4">{zh ? "观察项" : "Observation"}</th>
              <th className="pr-4">{zh ? "当前值" : "Value"}</th>
              <th className="pr-4">{zh ? "压力观察阈值" : "Pressure threshold"}</th>
              <th>{zh ? "数据日期 / 来源" : "Data date / source"}</th>
            </tr></thead>
            <tbody>{risk.observations.map((item) => {
              const percent = item.key === "trend_200d" || item.key === "drawdown_252d" || item.key === "vix_change";
              const operator = item.key === "trend_200d" ? "<" : item.key === "drawdown_252d" ? "≤" : "≥";
              const reason = reasons[item.reason]?.[zh ? 0 : 1] ?? item.reason;
              return <tr key={`${item.symbol}-${item.key}`} className="border-b border-border-subtle/60" data-risk-observation={`${item.symbol}:${item.key}`} data-risk-status={item.status}>
                <td className="py-3 pr-4"><div className="font-medium">{item.symbol} · {names[locale][item.key]}</div><div className={`mt-1 ${item.status === "attention" ? "text-warning" : "text-text-secondary"}`}>{reason}</div></td>
                <td className="pr-4 font-mono tabular-nums">{item.value == null ? "—" : `${item.value.toFixed(2)}${percent ? "%" : ""}`}</td>
                <td className="pr-4 font-mono text-text-secondary">{operator} {item.threshold}{percent ? "%" : ""}</td>
                <td className="font-mono text-text-secondary"><div>{item.as_of ?? "—"}</div><div className="mt-1 text-[10px]">{item.source === "public_cache" ? (zh ? "公共行情本地缓存" : "Local public-data cache") : item.source === "futu_cache" ? "Futu · cache · QFQ" : "Futu · QFQ"}</div></td>
              </tr>;
            })}</tbody>
          </table>
        </div>
        <p className="mt-4 text-xs leading-5 text-text-secondary">
          {zh
            ? `这是未做概率校准的观察规则，不是崩盘预测。高于 200 日均线 ${risk.trend_extension_pct}% 仅提示上涨偏离，不计入压力触发；价格窗口不足 200 / 252 个交易日时不估算。允许最多 1 个完整美股交易日的发布滞后；期限结构必须同日配对，单日变化必须相邻交易日。`
            : `These are uncalibrated observation rules, not a crash forecast. More than ${risk.trend_extension_pct}% above the 200D MA is upward-extension context only. Price windows need all 200 / 252 sessions. Data may lag by at most one completed US session; the term ratio needs matching dates and daily change needs consecutive sessions.`}
        </p>
      </>}
      <p className="mt-2 text-xs leading-5 text-text-secondary">{zh ? "这里统计当前观察范围的价格和波动。估值与宏观判断请看上方研判结果。" : "This section covers prices and volatility in the selected group. Valuation and macro evidence appear in the assessment above."}</p>
    </section>
  );
}
