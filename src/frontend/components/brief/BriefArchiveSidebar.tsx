"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { API_BASE_URL } from "@/lib/apiClient";
import {
  buildBriefArchivePath,
  type BriefArchiveEntry,
  type BriefArchiveEntryKind,
  type BriefArchiveGroup,
  type BriefArchiveViewResponse,
} from "@/lib/briefArchive";
import {
  buildBriefRollupListPath,
  buildBriefRollupSidebarGroups,
  type BriefRollupKind,
  type BriefRollupListResponse,
} from "@/lib/briefRollup";
import { localizePath } from "@/lib/locale";

const ARCHIVE_MONTHS = 6;
const ROLLUP_LIMIT = 30;

const copy = {
  en: {
    heading: "History",
    tabs: { daily: "Daily", weekly: "Weekly", monthly: "Monthly" } as const,
    loading: "Loading archive…",
    unavailable:
      "Archive unavailable (database offline). The live brief is unaffected.",
    empty: {
      daily: "No archived issues yet.",
      weekly: "No AI weekly briefs yet.",
      monthly: "No AI monthly briefs yet.",
    } as const,
  },
  zh: {
    heading: "历史",
    tabs: { daily: "日报", weekly: "周报", monthly: "月报" } as const,
    loading: "归档加载中…",
    unavailable: "归档暂不可用（数据库未连接），当前晨报不受影响。",
    empty: {
      daily: "暂无归档期号。",
      weekly: "暂无 AI 周报。",
      monthly: "暂无 AI 月报。",
    } as const,
  },
} as const;

type SidebarLocale = keyof typeof copy;

export type BriefArchiveSidebarViewProps = {
  activeKind: BriefArchiveEntryKind;
  activePublicId?: string | null;
  error?: string | null;
  groups: BriefArchiveGroup[];
  locale: SidebarLocale;
  onSelectKind?: (kind: BriefArchiveEntryKind) => void;
  status: "loading" | "error" | "ready";
};

function groupLabel(key: string, kind: BriefArchiveEntryKind, locale: SidebarLocale) {
  if (kind === "monthly") {
    return locale === "zh" ? `${key} 年` : key;
  }
  const [year, month] = key.split("-").map(Number);
  if (!year || !month) {
    return key;
  }
  if (locale === "zh") {
    return `${year} 年 ${month} 月`;
  }
  const monthName = new Intl.DateTimeFormat("en-US", { month: "long" }).format(
    new Date(Date.UTC(year, month - 1, 1)),
  );
  return `${monthName} ${year}`;
}

function entryMarker(entry: BriefArchiveEntry, kind: BriefArchiveEntryKind, locale: SidebarLocale) {
  const day = Number(entry.issue_date.slice(8, 10));
  if (kind === "daily") {
    return Number.isFinite(day) ? String(day) : entry.issue_date;
  }
  if (kind === "weekly") {
    return entry.iso_week?.slice(5) ?? "W--";
  }
  const month = Number((entry.month ?? entry.issue_date.slice(0, 7)).slice(5, 7));
  if (!Number.isFinite(month)) {
    return "--";
  }
  if (locale === "zh") {
    return `${month} 月`;
  }
  return new Intl.DateTimeFormat("en-US", { month: "short" }).format(
    new Date(Date.UTC(2000, month - 1, 1)),
  );
}

function entryHref(entry: BriefArchiveEntry, kind: BriefArchiveEntryKind, locale: SidebarLocale) {
  const base = kind === "daily" ? "/brief" : "/brief/rollup";
  return localizePath(`${base}/${entry.public_id}`, locale);
}

/** Pure presentational sidebar: fully determined by props, SSR-renderable. */
export function BriefArchiveSidebarView({
  activeKind,
  activePublicId = null,
  error = null,
  groups,
  locale,
  onSelectKind,
  status,
}: BriefArchiveSidebarViewProps) {
  const text = copy[locale];
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const kinds: BriefArchiveEntryKind[] = ["daily", "weekly", "monthly"];

  function toggle(key: string) {
    setCollapsed((current) => ({ ...current, [key]: !current[key] }));
  }

  return (
    <aside
      aria-label={text.heading}
      className="hidden h-full w-64 shrink-0 flex-col border-r border-editorial-rule bg-paper-surface md:flex"
      data-testid="brief-archive-sidebar"
    >
      <div className="border-b border-editorial-rule px-4 pb-3 pt-4">
        <div className="font-editorial-caps text-[11px] tracking-[0.18em] text-ink-secondary">
          {text.heading}
        </div>
        <div className="mt-2 flex gap-1" role="tablist">
          {kinds.map((kind) => {
            const active = kind === activeKind;
            return (
              <button
                aria-selected={active}
                className={`flex-1 border px-2 py-1.5 font-data-mono text-xs transition-colors ${
                  active
                    ? "border-editorial-accent text-editorial-accent"
                    : "border-editorial-rule text-ink-secondary hover:text-ink"
                }`}
                key={kind}
                onClick={() => onSelectKind?.(kind)}
                role="tab"
                type="button"
              >
                {text.tabs[kind]}
              </button>
            );
          })}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-3">
        {status === "loading" ? (
          <p className="px-2 py-6 text-center font-data-mono text-xs text-ink-secondary">
            {text.loading}
          </p>
        ) : null}
        {status === "error" ? (
          <p
            className="px-2 py-6 text-center font-data-mono text-xs text-warning"
            role="alert"
          >
            {error || text.unavailable}
          </p>
        ) : null}
        {status === "ready" && groups.length === 0 ? (
          <p className="px-2 py-6 text-center font-data-mono text-xs text-ink-secondary">
            {text.empty[activeKind]}
          </p>
        ) : null}
        {status === "ready"
          ? groups.map((group, index) => {
              const expanded =
                collapsed[`${activeKind}:${group.key}`] === undefined
                  ? index === 0
                  : !collapsed[`${activeKind}:${group.key}`];
              return (
                <section className="mb-2" key={group.key}>
                  <button
                    aria-expanded={expanded}
                    className="flex w-full items-center gap-2 px-2 py-1.5 text-left font-data-mono text-xs text-ink-secondary transition-colors hover:text-ink"
                    onClick={() => toggle(`${activeKind}:${group.key}`)}
                    type="button"
                  >
                    <span aria-hidden="true">{expanded ? "▾" : "▸"}</span>
                    <span className="font-editorial-caps tracking-[0.12em]">
                      {groupLabel(group.key, activeKind, locale)}
                    </span>
                  </button>
                  {expanded ? (
                    <ul>
                      {group.entries.map((entry) => {
                        const active = entry.public_id === activePublicId;
                        return (
                          <li key={`${entry.kind}-${entry.public_id}`}>
                            <Link
                              className={`flex items-baseline gap-2 px-2 py-1.5 transition-colors hover:bg-paper-surface-muted ${
                                active ? "bg-paper-surface-muted" : ""
                              }`}
                              href={entryHref(entry, activeKind, locale)}
                            >
                              <span className="w-8 shrink-0 text-right font-data-mono text-xs text-editorial-accent">
                                {entryMarker(entry, activeKind, locale)}
                              </span>
                              <span className="min-w-0 flex-1">
                                <span
                                  className={`block truncate text-xs ${
                                    active ? "text-ink" : "text-ink-secondary"
                                  }`}
                                >
                                  {entry.title}
                                </span>
                                {entry.snippet ? (
                                  <span className="block truncate font-data-mono text-[11px] text-ink-secondary">
                                    {entry.snippet}
                                  </span>
                                ) : null}
                              </span>
                            </Link>
                          </li>
                        );
                      })}
                    </ul>
                  ) : null}
                </section>
              );
            })
          : null}
      </div>
    </aside>
  );
}

type SidebarProps = {
  activePublicId?: string | null;
  locale: SidebarLocale;
};

type FetchStatus = "loading" | "error" | "ready";

type RollupTabState = {
  groups: BriefArchiveGroup[];
  status: FetchStatus;
};

export function BriefArchiveSidebar({ activePublicId = null, locale }: SidebarProps) {
  const [activeKind, setActiveKind] = useState<BriefArchiveEntryKind>("daily");
  const [view, setView] = useState<BriefArchiveViewResponse | null>(null);
  const [status, setStatus] = useState<FetchStatus>("loading");
  // Rollup tabs are cached per `${locale}:${kind}` so switching locales never
  // shows the other locale's entries. Each key is fetched at most once per
  // mount; a failed tab shows the honest error state instead of retry-looping.
  const [rollups, setRollups] = useState<Record<string, RollupTabState>>({});
  const rollupAttemptsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    fetch(`${API_BASE_URL}${buildBriefArchivePath(locale, ARCHIVE_MONTHS)}`, {
      headers: { accept: "application/json" },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`archive HTTP ${response.status}`);
        }
        return (await response.json()) as BriefArchiveViewResponse;
      })
      .then((data) => {
        if (!cancelled) {
          setView(data);
          setStatus("ready");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setView(null);
          setStatus("error");
        }
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [locale]);

  useEffect(() => {
    if (activeKind === "daily") {
      return;
    }
    const kind: BriefRollupKind = activeKind;
    const tabKey = `${locale}:${kind}`;
    const attempts = rollupAttemptsRef.current;
    if (attempts.has(tabKey)) {
      return;
    }
    attempts.add(tabKey);
    let cancelled = false;
    const controller = new AbortController();
    setRollups((current) => ({ ...current, [tabKey]: { groups: [], status: "loading" } }));
    fetch(`${API_BASE_URL}${buildBriefRollupListPath(kind, locale, ROLLUP_LIMIT)}`, {
      headers: { accept: "application/json" },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`rollups HTTP ${response.status}`);
        }
        return (await response.json()) as BriefRollupListResponse;
      })
      .then((data) => {
        if (!cancelled) {
          setRollups((current) => ({
            ...current,
            [tabKey]: {
              groups: buildBriefRollupSidebarGroups(data.items ?? [], kind),
              status: "ready",
            },
          }));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setRollups((current) => ({ ...current, [tabKey]: { groups: [], status: "error" } }));
        }
      });
    return () => {
      cancelled = true;
      controller.abort();
      // An aborted fetch (tab/locale switch mid-flight) may be retried later.
      attempts.delete(tabKey);
    };
  }, [activeKind, locale]);

  const text = copy[locale];
  const dailyGroups = useMemo(() => view?.daily ?? [], [view]);
  const isRollupTab = activeKind !== "daily";
  const rollupState = isRollupTab ? rollups[`${locale}:${activeKind}`] : undefined;
  const viewStatus: FetchStatus = isRollupTab ? rollupState?.status ?? "loading" : status;
  const groups = isRollupTab ? rollupState?.groups ?? [] : dailyGroups;

  return (
    <BriefArchiveSidebarView
      activeKind={activeKind}
      activePublicId={activePublicId}
      error={viewStatus === "error" ? text.unavailable : null}
      groups={groups}
      locale={locale}
      onSelectKind={setActiveKind}
      status={viewStatus}
    />
  );
}
