import Link from "next/link";
import type { PaperRuntimeStatus } from "@/lib/api";
import { localizePath, type Locale } from "@/lib/locale";
import { strategyIssueText } from "@/lib/strategyLibrary";

export function paperRuntimeLabel(runtime: PaperRuntimeStatus | null | undefined, locale: Locale) {
  const zh = locale === "zh";
  if (runtime?.configuration.status === "blocked") return zh ? "已启用 · 信号受阻" : "Enabled · signal blocked";
  return zh ? "已启用 · 运行证据另列" : "Enabled · evidence below";
}

export function PaperRuntimeEvidence({ runtime, locale }: {
  runtime?: PaperRuntimeStatus | null; locale: Locale;
}) {
  const zh = locale === "zh";
  const signal = runtime?.signal;
  const blocked = signal?.status === "blocked";
  const mismatch = signal?.reason?.includes("source_mismatch") || signal?.reason?.includes("config_mismatch");
  const signalText = blocked
    ? (mismatch ? (zh ? "因版本失配未生成信号" : "Signal blocked by version mismatch") : (zh ? "当前信号受阻" : "Current signal blocked"))
    : signal?.status === "generated"
      ? (zh ? `已有保存信号 · ${signal.signal_date ?? "日期未知"}` : `Saved signal · ${signal.signal_date ?? "date unknown"}`)
      : signal?.status === "data_unavailable" ? (zh ? "行情不可用，未生成有效信号" : "Market data unavailable; no valid signal")
        : signal?.status === "not_generated" ? (zh ? "尚无本版本信号" : "No signal for this version yet")
          : (zh ? "信号状态未核验" : "Signal status unverified");
  const fills = runtime?.fills;
  const fillText = fills?.status === "verified"
    ? (zh ? `${fills.count} 笔已提交成交 · ${fills.days} 个成交日` : `${fills.count} committed fills · ${fills.days} fill days`)
    : (zh ? "成交账证据未核验" : "Committed fill evidence unverified");
  return <section className="mt-3 border-l-2 border-border-strong pl-3 text-xs leading-6" aria-label={zh ? "自然模拟运行证据" : "Natural paper execution evidence"}>
    <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[auto_1fr]">
      <dt className="text-text-secondary">{zh ? "启用" : "Enablement"}</dt><dd>{runtime ? runtime.enabled ? (zh ? "已启用，等待原日程自然检查" : "Enabled for scheduled checks") : (zh ? "当前未启用" : "Currently not enabled") : (zh ? "未取得当前启用证据" : "Current enablement evidence unavailable")}</dd>
      <dt className="text-text-secondary">{zh ? "信号" : "Signal"}</dt><dd className={blocked ? "text-warning" : ""}>{signalText}</dd>
      <dt className="text-text-secondary">{zh ? "成交" : "Fills"}</dt><dd>{fillText}</dd>
      <dt className="text-text-secondary">{zh ? "估值" : "Valuation"}</dt><dd>{runtime?.valuation.status === "cash_only" ? (zh ? "纯现金；尚无成交后的策略收益" : "Cash only; no post-fill strategy return") : (zh ? "查看已保存复盘；估值天数不等于成交天数" : "See saved review; valuation days are not fill days")}</dd>
    </dl>
    {blocked ? <p className="mt-2 text-warning">{strategyIssueText(signal?.reason, locale)} {zh ? "原验证与历史信号保留。须取得当前版本资格并完成版本替换后，再观察原日程；不会补造历史成交。" : "Original validation and signals are retained. A qualified replacement must precede scheduled observation; past fills are not reconstructed."}</p> : null}
    {fills?.status === "verified" && fills.count === 0 ? <p className="mt-1 text-text-secondary">{zh ? "0 成交不代表策略已被市场验证。下一步先核对信号资格，再等待自然周期。" : "Zero fills do not establish market performance. Check signal eligibility before observing the next scheduled cycle."}</p> : null}
    {fills?.status === "unavailable" ? <p className="mt-1 text-warning">{zh ? "成交与记账证据尚不完整，请核对原执行记录；不能将缺失填成 0。" : "Fill and journal evidence is incomplete. Inspect the original executions; missing evidence is not zero."}</p> : null}
    <div className="mt-2 flex flex-wrap gap-x-4 text-text-secondary"><Link className="text-[var(--color-hermes)] hover:underline" href={localizePath("/research-evaluation?tab=paper", locale)}>{zh ? "查看模拟复盘与估值" : "Open paper review and valuation"}</Link>{runtime?.checked_at ? <span>{zh ? "核对于" : "Checked"} {runtime.checked_at.replace("T", " ").slice(0, 19)} UTC</span> : null}</div>
  </section>;
}
