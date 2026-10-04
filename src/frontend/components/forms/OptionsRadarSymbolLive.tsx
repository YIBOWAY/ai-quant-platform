'use client';

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, AlertTriangle, Play } from "lucide-react";
import type {
  OptionsChainResponse,
  OptionsExpirationsResponse,
  OptionsSnapshotResponse,
} from "@/lib/api";
import { apiRequest } from "@/lib/apiClient";
import { useLocale } from "@/components/LocaleProvider";
import { TerminalToolbarButton } from "@/components/ui/primitives";

const copy = {
  en: {
    title: "Live Option Chain",
    intro: "Read-only Futu snapshot and option chain. This area never places orders.",
    load: "Load Live Chain",
    snapshotUnavailable: "Live snapshot unavailable. Check Futu OpenD before using the live chain.",
    expirationsUnavailable: "Expiration list unavailable. Check Futu OpenD, then load the live chain again.",
    chainUnavailable: "Live chain unavailable. Radar snapshot rows are still shown above.",
    loading: "Loading live chain...",
    idle: "Saved Radar rows are shown on the left. Load the live chain when Futu OpenD is ready.",
    noExpirations: "No live expirations were returned for this symbol, so the live chain cannot be loaded.",
    chainEmpty: "The live chain returned no contracts for this expiration.",
    metrics: {
      price: "Price",
      expiry: "Expiry",
      atmIv: "ATM IV",
      ivRank: "IV Rank",
      vrp: "VRP",
    },
    headings: ["Symbol", "Type", "Strike", "Bid", "Ask", "IV", "Delta", "OI", "Volume"],
  },
  zh: {
    title: "实时期权链",
    intro: "只读 Futu 快照与期权链。这里永远不会下单。",
    load: "加载实时链",
    snapshotUnavailable: "实时快照不可用。使用实时链前请检查 Futu OpenD。",
    expirationsUnavailable: "到期日列表不可用。请检查 Futu OpenD，然后重新加载实时链。",
    chainUnavailable: "实时链不可用。上方仍保留雷达快照行。",
    loading: "正在加载实时链...",
    idle: "左侧显示已保存的雷达行。Futu OpenD 就绪后可加载实时链。",
    noExpirations: "该标的没有返回可用的实时到期日，无法加载实时期权链。",
    chainEmpty: "该到期日的实时链没有返回合约。",
    metrics: {
      price: "现价",
      expiry: "到期日",
      atmIv: "平值 IV",
      ivRank: "IV Rank",
      vrp: "VRP",
    },
    headings: ["合约", "类型", "行权价", "买价", "卖价", "IV", "Delta", "未平仓", "成交量"],
  },
};

type OptionsRadarSymbolLiveProps = {
  symbol: string;
  expiry?: string;
  optionType?: string;
};

export function OptionsRadarSymbolLive({
  symbol,
  expiry,
  optionType = "ALL",
}: OptionsRadarSymbolLiveProps) {
  const locale = useLocale();
  const text = copy[locale];
  const [loadLive, setLoadLive] = useState(false);
  const snapshotQuery = useQuery({
    queryKey: ["options-symbol-snapshot", symbol, expiry || null],
    enabled: loadLive,
    queryFn: () => apiRequest<OptionsSnapshotResponse>(`/api/options/snapshot/${encodeURIComponent(symbol)}${expiry ? `?expiration=${encodeURIComponent(expiry)}` : ""}`),
    retry: 0,
  });
  const expirationsQuery = useQuery({
    queryKey: ["options-symbol-expirations", symbol],
    enabled: loadLive,
    queryFn: () =>
      apiRequest<OptionsExpirationsResponse>(
        `/api/options/expirations?ticker=${encodeURIComponent(symbol)}`,
      ),
    retry: 0,
  });
  const selectedExpiry =
    expiry || snapshotQuery.data?.nearest_expiry || firstExpiration(expirationsQuery.data?.expirations ?? []);
  const chainQuery = useQuery({
    queryKey: ["options-symbol-chain", symbol, selectedExpiry, optionType],
    enabled: loadLive && Boolean(selectedExpiry),
    queryFn: () => {
      const params = new URLSearchParams({
        ticker: symbol,
        expiration: selectedExpiry ?? "",
        option_type: optionType,
      });
      return apiRequest<OptionsChainResponse>(`/api/options/chain?${params.toString()}`);
    },
    retry: 0,
  });
  const chainInitialLoading =
    loadLive &&
    ((expirationsQuery.isPending && !expirationsQuery.data) ||
      (Boolean(selectedExpiry) && chainQuery.isPending && !chainQuery.data));
  const chainRefetching =
    loadLive &&
    (expirationsQuery.isFetching || chainQuery.isFetching) &&
    Boolean(chainQuery.data || expirationsQuery.data);
  const chainEmptyLabel = !loadLive
    ? text.idle
    : chainInitialLoading
      ? text.loading
      : !selectedExpiry
        ? text.noExpirations
        : text.chainEmpty;

  return (
    <section className="min-w-0 rounded-lg border border-border-subtle bg-bg-surface p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h2 className="font-label-caps text-text-primary">{text.title}</h2>
          <p className="mt-1 font-body-sm text-text-secondary">{text.intro}</p>
        </div>
        <Activity size={18} className="text-info" />
      </div>
      {!loadLive ? (
        <TerminalToolbarButton
          className="mb-4"
          onClick={() => setLoadLive(true)}
          tone="info"
          type="button"
        >
          <Play size={14} />
          {text.load}
        </TerminalToolbarButton>
      ) : null}
      {snapshotQuery.error ? (
        <WarningLine message={text.snapshotUnavailable} />
      ) : loadLive ? (
        <LiveSnapshotMetrics locale={locale} selectedExpiry={selectedExpiry} snapshot={snapshotQuery.data} />
      ) : null}
      {expirationsQuery.error ? (
        <WarningLine message={text.expirationsUnavailable} />
      ) : chainQuery.error && !chainQuery.data ? (
        <WarningLine message={text.chainUnavailable} />
      ) : (
        <div
          aria-busy={chainRefetching || chainInitialLoading}
          className="motion-data-hold"
          data-fetching={chainRefetching ? "true" : "false"}
        >
          {chainQuery.data?.contracts?.length ? (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left font-body-sm">
                <thead>
                  <tr className="border-b border-border-subtle font-label-caps text-text-secondary">
                    {text.headings.map((heading) => (
                      <th className="pb-2 pr-3" key={heading}>{heading}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="font-data-mono text-xs text-text-primary">
                  {chainQuery.data.contracts.slice(0, 20).map((contract, index) => (
                    <tr className="border-b border-border-subtle/40" key={`${contract.symbol ?? "contract"}-${index}`}>
                      <td className="py-2 pr-3">{contract.symbol ?? "--"}</td>
                      <td className="py-2 pr-3">{contract.option_type ?? "--"}</td>
                      <td className="py-2 pr-3">{num(contract.strike, 2)}</td>
                      <td className="py-2 pr-3">{num(contract.bid, 2)}</td>
                      <td className="py-2 pr-3">{num(contract.ask, 2)}</td>
                      <td className="py-2 pr-3">{futuIvPercent(contract.implied_volatility)}</td>
                      <td className="py-2 pr-3">{num(contract.delta, 3)}</td>
                      <td className="py-2 pr-3">{num(contract.open_interest, 0)}</td>
                      <td className="py-2 pr-3">{num(contract.volume, 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-border-subtle p-4 font-body-sm text-text-secondary">
              {chainEmptyLabel}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export function LiveSnapshotMetrics({ locale, snapshot, selectedExpiry }: {
  locale: "zh" | "en"; snapshot?: OptionsSnapshotResponse; selectedExpiry: string | null;
}) {
  const text = copy[locale];
  const sameExpiry = snapshot?.iv_expiry === selectedExpiry;
  const hasRealRank = sameExpiry && snapshot?.iv_rank_source !== "local_hv_proxy" && snapshot?.iv_rank != null;
  return <div className="mb-4">
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
      <Metric label={text.metrics.price} value={money(snapshot?.price)} />
      <Metric label={text.metrics.expiry} value={selectedExpiry ?? "--"} />
      <Metric label={text.metrics.atmIv} value={pct(sameExpiry ? snapshot?.atm_iv : null)} />
      <Metric label={text.metrics.ivRank} value={hasRealRank ? num(snapshot?.iv_rank, 1) : "--"} />
      <Metric label={text.metrics.vrp} value={pct(sameExpiry ? snapshot?.vrp : null)} />
    </div>
    {!hasRealRank ? <p className="mt-2 font-body-sm text-text-secondary">{locale === "zh"
      ? "缺少同口径期权 IV 历史，IV Rank 留空；不会用股票价格波动代替。"
      : "Matching option-IV history is missing. IV Rank is unknown; equity-price volatility is not a substitute."}</p> : null}
  </div>;
}

export function futuIvPercent(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? `${value.toFixed(2)}%` : "--";
}

function WarningLine({ message }: { message: string }) {
  return (
    <div className="mb-4 flex items-center gap-2 rounded-lg border border-warning/40 bg-warning/10 p-3 font-body-sm text-warning">
      <AlertTriangle size={16} />
      {message}
    </div>
  );
}

function firstExpiration(rows: Array<Record<string, unknown>>) {
  for (const row of rows) {
    const value =
      row.strike_time ??
      row.expiration ??
      row.expiry ??
      row.date ??
      row.expiration_date;
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return null;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border-subtle bg-bg-surface-muted p-3">
      <div className="font-label-caps text-text-secondary">{label}</div>
      <div className="mt-2 font-data-mono text-text-primary">{value}</div>
    </div>
  );
}

function num(value?: number | null, digits = 2) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "--";
}

function pct(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : "--";
}

function money(value?: number | null) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "--";
  }
  return new Intl.NumberFormat("en-US", {
    currency: "USD",
    maximumFractionDigits: 2,
    style: "currency",
  }).format(value);
}
