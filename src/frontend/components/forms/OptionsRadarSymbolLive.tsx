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
import { TerminalToolbarButton } from "@/components/ui/primitives";

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
  const [loadLive, setLoadLive] = useState(false);
  const snapshotQuery = useQuery({
    queryKey: ["options-symbol-snapshot", symbol],
    enabled: loadLive,
    queryFn: () => apiRequest<OptionsSnapshotResponse>(`/api/options/snapshot/${symbol}`),
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
    expiry ?? firstExpiration(expirationsQuery.data?.expirations ?? []);
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

  return (
    <section className="rounded-lg border border-border-subtle bg-bg-surface p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h2 className="font-label-caps text-text-primary">Live Option Chain</h2>
          <p className="mt-1 font-body-sm text-text-secondary">
            Read-only Futu snapshot and option chain. This area never places orders.
          </p>
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
          Load Live Chain
        </TerminalToolbarButton>
      ) : null}
      {snapshotQuery.error ? (
        <WarningLine message="Live snapshot unavailable. Check Futu OpenD before using the live chain." />
      ) : loadLive ? (
        <div className="mb-4 grid gap-3 md:grid-cols-4">
          <Metric label="Price" value={money(snapshotQuery.data?.price)} />
          <Metric label="Expiry" value={selectedExpiry ?? "--"} />
          <Metric label="ATM IV" value={pct(snapshotQuery.data?.atm_iv)} />
          <Metric label="IV Rank" value={num(snapshotQuery.data?.iv_rank, 1)} />
          <Metric label="VRP" value={pct(snapshotQuery.data?.vrp)} />
        </div>
      ) : null}
      {chainQuery.error ? (
        <WarningLine message="Live chain unavailable. Radar snapshot rows are still shown above." />
      ) : chainQuery.data?.contracts?.length ? (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left font-body-sm">
            <thead>
              <tr className="border-b border-border-subtle font-label-caps text-text-secondary">
                {["Symbol", "Type", "Strike", "Bid", "Ask", "IV", "Delta", "OI", "Volume"].map((heading) => (
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
                  <td className="py-2 pr-3">{pct(contract.implied_volatility)}</td>
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
          {loadLive
            ? "Loading live chain..."
            : "Saved Radar rows are shown on the left. Load the live chain when Futu OpenD is ready."}
        </div>
      )}
    </section>
  );
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
