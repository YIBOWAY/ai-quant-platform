"use client";

import { useEffect, useId, useState } from "react";
import { apiRequest } from "@/lib/apiClient";
import type { components } from "@/lib/api.generated";

type Catalog = components["schemas"]["SecuritySearchResponse"];
type Entry = Catalog["items"][number];

export function SecuritySearchInput({ value, onChange, onSelect, label, className = "", locale = "zh", id, name }: {
  value: string;
  onChange: (value: string) => void;
  onSelect?: (symbol: string) => void;
  label: string;
  className?: string;
  locale?: "en" | "zh";
  id?: string;
  name?: string;
}) {
  const uniqueId = useId();
  const listId = `${uniqueId}-securities`;
  const [result, setResult] = useState<Catalog | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [error, setError] = useState("");
  const [resolvedQuery, setResolvedQuery] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    if (value.trim().length < 2) return () => controller.abort();
    const timer = setTimeout(() => {
      void apiRequest<Catalog>(`/api/securities/search?query=${encodeURIComponent(value.trim())}`, { signal: controller.signal })
        .then(data => { if (!controller.signal.aborted) { setResult(data); setError(""); setResolvedQuery(value.trim()); setActive(data.items.length ? 0 : -1); } })
        .catch(() => { if (!controller.signal.aborted) { setResult(null); setResolvedQuery(value.trim()); setError(locale === "zh" ? "证券目录暂不可用；仍可输入代码查行情。" : "Directory unavailable; a ticker can still be used."); } });
    }, 220);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [value, locale]);
  const choose = (entry: Entry) => {
    onChange(entry.symbol);
    setOpen(false);
    onSelect?.(entry.symbol);
  };
  const currentResult = resolvedQuery === value.trim() ? result : null;
  const currentError = resolvedQuery === value.trim() ? error : "";
  const visible = open && value.trim().length >= 2 && (currentResult !== null || Boolean(currentError));
  return <div className="relative min-w-0 flex-1">
    <input
      id={id}
      name={name}
      aria-label={label}
      role="combobox"
      aria-autocomplete="list"
      aria-expanded={visible}
      aria-controls={visible ? listId : undefined}
      aria-activedescendant={visible && active >= 0 ? `${listId}-${active}` : undefined}
      autoComplete="off"
      className={className}
      value={value}
      placeholder={locale === "zh" ? "公司名或标的代码" : "Company or ticker"}
      onChange={event => { onChange(event.target.value); setOpen(true); }}
      onFocus={() => setOpen(true)}
      onBlur={event => { if (!event.currentTarget.parentElement?.contains(event.relatedTarget as Node | null)) setOpen(false); }}
      onKeyDown={event => {
        if (event.key === "Escape") { setOpen(false); return; }
        const items = currentResult?.items ?? [];
        if (items.length && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
          event.preventDefault(); setOpen(true);
          setActive(index => index < 0 ? (event.key === "ArrowDown" ? 0 : items.length - 1) : (index + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length);
        }
        if (event.key === "Enter" && visible && active >= 0 && items[active]) {
          event.preventDefault(); choose(items[active]);
        }
      }}
    />
    {visible ? <div className="absolute left-0 top-full z-50 mt-2 w-[min(360px,calc(100vw-32px))] overflow-hidden rounded-lg border border-border-subtle bg-bg-surface shadow-xl">
      <ul id={listId} role="listbox" aria-label={locale === "zh" ? "证券搜索结果" : "Security results"} className="max-h-80 overflow-y-auto py-1">
        {(currentResult?.items ?? []).map((entry, index) => <li key={`${entry.symbol}-${entry.asset_type}-${entry.exchange}`}>
          <button type="button" role="option" id={`${listId}-${index}`} aria-selected={index === active} className={`w-full px-4 py-2.5 text-left hover:bg-bg-surface-muted ${index === active ? "bg-bg-surface-muted" : ""}`} onMouseDown={event => event.preventDefault()} onClick={() => choose(entry)}>
            <span className="flex items-center gap-2"><span className="font-mono text-sm text-text-primary">{entry.symbol}</span><span className="text-[10px] text-text-secondary">{entry.exchange} · {entry.asset_type === "etf" ? "ETF" : locale === "zh" ? "股票" : "Equity"}</span></span>
            <span className="mt-1 block truncate text-xs text-text-secondary">{entry.name}</span>
            {entry.sector ? <span className="mt-1 block text-[10px] text-text-secondary">{entry.sector}</span> : null}
          </button>
        </li>)}
      </ul>
      {currentError ? <p role="status" className="px-4 py-2 text-xs text-warning">{currentError}</p> : currentResult?.items.length === 0 ? <p role="status" className="px-4 py-2 text-xs text-text-secondary">{locale === "zh" ? "未找到美股目录记录，可直接输入代码。" : "No US listing found. You can enter a ticker directly."}</p> : null}
      <p className="border-t border-border-subtle px-4 py-2 text-[10px] leading-5 text-text-secondary">FinanceDatabase · {locale === "zh" ? "美股证券目录，非行情或交易资格" : "US directory, not quotes or trading eligibility"}</p>
    </div> : null}
  </div>;
}
