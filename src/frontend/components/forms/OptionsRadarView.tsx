'use client';

import { useQuery } from "@tanstack/react-query";
import { Download, ShieldCheck } from "lucide-react";
import { Fragment, useMemo, useState } from "react";
import type {
  OptionsRadarCandidate,
  OptionsRadarDatesResponse,
  OptionsRadarResponse,
} from "@/lib/api";
import { apiRequest } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };
const sectors = [
  "Communication Services",
  "Consumer Discretionary",
  "Consumer Staples",
  "Energy",
  "Financials",
  "Health Care",
  "Healthcare",
  "Industrials",
  "Information Technology",
  "Materials",
  "Real Estate",
  "Technology",
  "Utilities",
  "ETF",
];

const copy = {
  en: {
    title: "Options Radar",
    intro: "Daily read-only scan for seller option candidates. No orders, no account unlock, no live trading.",
    date: "Run date",
    strategy: "Strategy",
    all: "All",
    sellPut: "Sell Put",
    coveredCall: "Covered Call",
    sector: "Sector",
    dte: "DTE bucket",
    top: "Top N",
    safety: "Read-only research output. These rows are not trade instructions and cannot place orders.",
    export: "Export CSV",
    noData: "No daily scan snapshot found. Run `quant-system options daily-scan --provider sample --top 5` for an offline sample.",
    rows: "Rows",
    scanned: "Scanned",
    failed: "Failed",
    regime: "Market regime",
    regimeUnknown: "Unknown - run `quant-system options refresh-vix` then re-scan to populate VIX history.",
    regimeNormal: "Normal - no market-regime score penalty.",
    regimeElevated: "Elevated - seller candidates receive a moderate score penalty.",
    regimePanic: "Panic - seller candidates receive a heavy score penalty.",
    zh: "中文",
    details: "Details",
    headings: ["Symbol", "Sector", "Strategy", "Expiry", "Strike", "Mid", "APR", "IV", "IVR", "Delta", "OI", "Spread", "Earnings", "Score", "Rating", ""],
  },
  zh: {
    title: "期权雷达",
    intro: "每日只读扫描卖方期权候选。不会下单、不会解锁账户、不会接入实盘。",
    date: "扫描日期",
    strategy: "策略",
    all: "全部",
    sellPut: "卖出看跌",
    coveredCall: "备兑看涨",
    sector: "行业",
    dte: "DTE 区间",
    top: "显示数量",
    safety: "仅用于研究筛选。这些结果不是交易指令，也不能发出真实订单。",
    export: "导出 CSV",
    noData: "还没有每日扫描快照。可以先运行 `quant-system options daily-scan --provider sample --top 5` 生成离线样例。",
    rows: "候选",
    scanned: "已扫描",
    failed: "失败",
    regime: "市场状态",
    regimeUnknown: "未知 - 请先运行 `quant-system options refresh-vix` 刷新 VIX 历史后再扫描。",
    regimeNormal: "Normal - 不施加市场状态扣分。",
    regimeElevated: "Elevated - 对卖方候选施加中等评分扣分。",
    regimePanic: "Panic - 对卖方候选施加较重评分扣分。",
    zh: "English",
    details: "详情",
    headings: ["标的", "行业", "策略", "到期", "行权价", "中间价", "年化", "IV", "IVR", "Delta", "未平仓", "价差", "财报", "分数", "评级", ""],
  },
};

export function OptionsRadarView({ locale = "en" }: { locale?: "en" | "zh" }) {
  const hydrated = useIsHydrated();
  const text = copy[locale];
  const [date, setDate] = useState("");
  const [strategy, setStrategy] = useState("all");
  const [sector, setSector] = useState("");
  const [dteBucket, setDteBucket] = useState("");
  const [top, setTop] = useState(50);
  const [expanded, setExpanded] = useState<string | null>(null);

  const datesQuery = useQuery({
    queryKey: ["options-radar-dates"],
    enabled: hydrated,
    queryFn: () => apiRequest<OptionsRadarDatesResponse>("/api/options/daily-scan/dates"),
  });

  const activeDate = date || datesQuery.data?.dates[0] || "";
  const scanQuery = useQuery({
    queryKey: ["options-radar", activeDate, strategy, sector, dteBucket, top],
    enabled: hydrated,
    queryFn: () => {
      const params = new URLSearchParams({
        strategy,
        top: String(top),
      });
      if (activeDate) params.set("date", activeDate);
      if (sector) params.set("sector", sector);
      if (dteBucket) params.set("dte_bucket", dteBucket);
      return apiRequest<OptionsRadarResponse>(`/api/options/daily-scan?${params.toString()}`);
    },
  });

  const candidates = useMemo(
    () => scanQuery.data?.candidates ?? [],
    [scanQuery.data?.candidates],
  );
  const csv = useMemo(() => buildCsv(candidates), [candidates]);
  const regime = useMemo(() => deriveRegime(candidates), [candidates]);

  function exportCsv() {
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `options-radar-${scanQuery.data?.run_date ?? "latest"}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-[360px_1fr] overflow-hidden bg-base text-text-primary">
      <aside className="overflow-y-auto border-r border-border-subtle bg-bg-surface p-4">
        <h1 className="font-headline-lg text-text-primary">{text.title}</h1>
        <p className="mt-2 font-body-sm text-text-secondary">{text.intro}</p>
        <a
          className="mt-3 inline-flex font-body-sm text-info"
          href={locale === "zh" ? "/options-radar?lang=en" : "/options-radar?lang=zh"}
        >
          {text.zh}
        </a>
        <form className="mt-5 flex flex-col gap-4" onSubmit={(event) => event.preventDefault()}>
          <label className="flex flex-col gap-1 font-body-sm">
            {text.date}
            <select
              className="rounded border border-border-subtle bg-surface-muted px-3 py-2 text-text-primary"
              onChange={(event) => setDate(event.target.value)}
              value={activeDate}
            >
              {datesQuery.data?.dates.map((item) => (
                <option key={item} style={optionStyle} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 font-body-sm">
            {text.strategy}
            <select
              className="rounded border border-border-subtle bg-surface-muted px-3 py-2 text-text-primary"
              onChange={(event) => setStrategy(event.target.value)}
              value={strategy}
            >
              <option style={optionStyle} value="all">{text.all}</option>
              <option style={optionStyle} value="sell_put">{text.sellPut}</option>
              <option style={optionStyle} value="covered_call">{text.coveredCall}</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 font-body-sm">
            {text.sector}
            <select
              className="rounded border border-border-subtle bg-surface-muted px-3 py-2 text-text-primary"
              onChange={(event) => setSector(event.target.value)}
              value={sector}
            >
              <option style={optionStyle} value="">{text.all}</option>
              {sectors.map((item) => (
                <option key={item} style={optionStyle} value={item}>{item}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 font-body-sm">
            {text.dte}
            <select
              className="rounded border border-border-subtle bg-surface-muted px-3 py-2 text-text-primary"
              onChange={(event) => setDteBucket(event.target.value)}
              value={dteBucket}
            >
              <option style={optionStyle} value="">{text.all}</option>
              <option style={optionStyle} value="7-21">7-21</option>
              <option style={optionStyle} value="21-45">21-45</option>
              <option style={optionStyle} value="45-60">45-60</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 font-body-sm">
            {text.top}
            <input
              className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary"
              min={1}
              max={250}
              onChange={(event) => setTop(Number(event.target.value))}
              type="number"
              value={top}
            />
          </label>
          <button
            className="rounded bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:opacity-50"
            disabled={!csv || candidates.length === 0}
            onClick={exportCsv}
            type="button"
          >
            <Download className="mr-2 inline" size={16} />
            {text.export}
          </button>
        </form>
      </aside>
      <main className="min-w-0 overflow-y-auto p-5">
        <div className="mb-4 flex items-center gap-2 rounded border border-warning/40 bg-warning/10 p-3 font-body-sm text-warning">
          <ShieldCheck size={18} />
          {text.safety}
        </div>
        <RegimeBanner regime={regime} text={text} />
        <section className="mb-4 grid grid-cols-3 gap-3">
          <Metric label={text.rows} value={String(candidates.length)} />
          <Metric label={text.scanned} value={String(scanQuery.data?.scanned_tickers ?? 0)} />
          <Metric label={text.failed} value={String(scanQuery.data?.failed_tickers.length ?? 0)} />
        </section>
        {scanQuery.isLoading ? (
          <div className="rounded border border-border-subtle bg-bg-surface p-6 font-body-sm text-text-secondary">
            Loading daily scan...
          </div>
        ) : scanQuery.isError || candidates.length === 0 ? (
          <div className="rounded border border-border-subtle bg-bg-surface p-6 font-body-sm text-text-secondary">
            {scanQuery.error instanceof Error ? scanQuery.error.message : text.noData}
          </div>
        ) : (
          <div className="overflow-x-auto rounded border border-border-subtle bg-bg-surface">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-border-subtle">
                  {text.headings.map((heading) => (
                    <th className="px-3 py-2 font-label-caps text-text-secondary" key={heading}>
                      {heading}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="font-data-mono text-data-mono text-text-primary">
                {candidates.map((candidate) => (
                  <Fragment key={candidate.symbol}>
                    <tr className="border-b border-border-subtle/50">
                      <td className="px-3 py-2">{candidate.ticker}</td>
                      <td className="px-3 py-2">{candidate.sector ?? "--"}</td>
                      <td className="px-3 py-2">{candidate.strategy}</td>
                      <td className="px-3 py-2">{candidate.expiry}</td>
                      <td className="px-3 py-2">{fmt(candidate.strike)}</td>
                      <td className="px-3 py-2">{fmt(candidate.mid)}</td>
                      <td className="px-3 py-2">{pct(candidate.annualized_yield)}</td>
                      <td className="px-3 py-2">{pct(candidate.implied_volatility)}</td>
                      <td className="px-3 py-2">{fmt(candidate.iv_rank, 1)}</td>
                      <td className="px-3 py-2">{fmt(candidate.delta, 3)}</td>
                      <td className="px-3 py-2">{fmt(candidate.open_interest, 0)}</td>
                      <td className="px-3 py-2">{pct(candidate.spread_pct)}</td>
                      <td className="px-3 py-2">{candidate.earnings_in_window ? "Yes" : "No"}</td>
                      <td className="px-3 py-2">{fmt(candidate.global_score, 1)}</td>
                      <td className="px-3 py-2">{candidate.rating}</td>
                      <td className="px-3 py-2">
                        <button
                          className="text-info"
                          onClick={() => setExpanded(expanded === candidate.symbol ? null : candidate.symbol)}
                          type="button"
                        >
                          {text.details}
                        </button>
                      </td>
                    </tr>
                    {expanded === candidate.symbol ? (
                      <tr className="border-b border-border-subtle/50">
                        <td className="px-3 py-3 font-body-sm text-text-secondary" colSpan={16}>
                          {candidate.notes.length ? candidate.notes.join(" | ") : "No notes"}
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border-subtle bg-bg-surface p-3">
      <div className="font-label-caps text-text-secondary">{label}</div>
      <div className="mt-2 font-data-mono text-lg font-bold text-text-primary">{value}</div>
    </div>
  );
}

type RegimeInfo = {
  label: "Normal" | "Elevated" | "Panic" | "Unknown";
  penalty: number | null;
};

function deriveRegime(candidates: OptionsRadarCandidate[]): RegimeInfo {
  for (const candidate of candidates) {
    if (candidate.market_regime) {
      return {
        label: candidate.market_regime as RegimeInfo["label"],
        penalty: candidate.market_regime_penalty ?? null,
      };
    }
  }
  return { label: "Unknown", penalty: null };
}

function RegimeBanner({
  regime,
  text,
}: {
  regime: RegimeInfo;
  text: (typeof copy)["en"];
}) {
  const palette: Record<RegimeInfo["label"], string> = {
    Normal: "border-accent-success/40 bg-accent-success/10 text-accent-success",
    Elevated: "border-warning/40 bg-warning/10 text-warning",
    Panic: "border-accent-danger/40 bg-accent-danger/10 text-accent-danger",
    Unknown: "border-border-subtle bg-bg-surface text-text-secondary",
  };
  const detail =
    regime.label === "Normal"
      ? text.regimeNormal
      : regime.label === "Elevated"
        ? text.regimeElevated
        : regime.label === "Panic"
          ? text.regimePanic
          : text.regimeUnknown;
  return (
    <div className={`mb-4 rounded border p-3 font-body-sm ${palette[regime.label]}`}>
      <div className="flex items-center justify-between">
        <span className="font-label-caps">{text.regime}</span>
        <span className="font-data-mono text-sm font-bold">{regime.label}</span>
      </div>
      <p className="mt-1 leading-snug">{detail}</p>
    </div>
  );
}

function fmt(value?: number | null, digits = 2) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "--";
}

function pct(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : "--";
}

function buildCsv(candidates: OptionsRadarCandidate[]) {
  const headers = ["ticker", "sector", "strategy", "symbol", "expiry", "strike", "mid", "apr", "iv", "iv_rank", "delta", "oi", "spread", "earnings", "score", "rating"];
  const rows = candidates.map((item) =>
    [
      item.ticker,
      item.sector ?? "",
      item.strategy,
      item.symbol,
      item.expiry,
      item.strike,
      item.mid ?? "",
      item.annualized_yield ?? "",
      item.implied_volatility ?? "",
      item.iv_rank ?? "",
      item.delta ?? "",
      item.open_interest ?? "",
      item.spread_pct ?? "",
      item.earnings_in_window ? "yes" : "no",
      item.global_score,
      item.rating,
    ].join(","),
  );
  return [headers.join(","), ...rows].join("\n");
}
