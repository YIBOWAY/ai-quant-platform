'use client';

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { FormEvent, ReactNode } from "react";
import { Suspense, useEffect, useRef, useState } from "react";
import { Menu, Search, Settings, Terminal, X } from "lucide-react";
import { useLocale } from "@/components/LocaleProvider";
import { LocaleToggle, LocaleToggleFallback } from "@/components/LocaleToggle";
import { localizePath, splitLocalePath } from "@/lib/locale";
import {
  buildNavSections,
  isVisibleOnSurface,
  type NavItemId,
} from "@/lib/navConfig";

const copy = {
  en: {
    search: "Search symbol...",
    marketData: "Market Data",
    options: "Options",
    replications: "Strategy Catalog",
    orderBook: "Polymarket Markets",
    aiNews: "AI News",
    positionMap: "Position Map",
    dashboard: "Dashboard",
    hermes: "Hermes",
    brief: "Morning Brief",
    openHermes: "Open Hermes workbench",
    openSettings: "Open settings",
    dataExplorer: "Data Explorer",
    factorLab: "Factor Lab",
    backtester: "Backtester",
    experiments: "Experiments",
    paperTrading: "Paper Trading",
    optionsScreener: "Options Screener",
    optionsRadar: "Options Radar",
    optionsTools: "Options Tools",
    buySide: "Buy-side Options",
    asiaRadar: "Asia Radar",
    agentStudio: "Agent Studio",
    settings: "Settings",
    docs: "Docs",
    support: "Help",
    mobileMenu: "Open navigation",
    groups: {
      research: "Research Pipeline",
      paper: "Paper Trading",
      options: "Options Research",
      markets: "Markets & AI",
      system: "System",
    },
  },
  zh: {
    search: "搜索标的...",
    marketData: "行情数据",
    options: "期权",
    replications: "策略目录",
    orderBook: "Polymarket 市场",
    aiNews: "AI 新闻",
    positionMap: "持仓地图",
    dashboard: "仪表盘",
    hermes: "Hermes 工作台",
    brief: "每日晨报",
    openHermes: "打开 Hermes 工作台",
    openSettings: "打开设置",
    dataExplorer: "行情浏览",
    factorLab: "因子实验室",
    backtester: "回测器",
    experiments: "实验管理",
    paperTrading: "模拟交易",
    optionsScreener: "期权筛选器",
    optionsRadar: "期权雷达",
    optionsTools: "期权工具",
    buySide: "买方期权",
    asiaRadar: "亚洲雷达",
    agentStudio: "智能体工作室",
    settings: "设置",
    docs: "文档",
    support: "帮助",
    mobileMenu: "打开导航",
    groups: {
      research: "研究流水线",
      paper: "模拟交易",
      options: "期权研究",
      markets: "市场与 AI",
      system: "系统",
    },
  },
};

type FlatCopy = (typeof copy)["en"] | (typeof copy)["zh"];

function labelFor(text: FlatCopy, id: NavItemId): string {
  const value = text[id as keyof FlatCopy];
  return typeof value === "string" ? value : id;
}

export function TopBar({
  shellEnabled,
  agentStudioRedirect = false,
  safetySlot,
}: {
  shellEnabled: boolean;
  agentStudioRedirect?: boolean;
  /** Server-rendered <SafetyBadge />: this component is a client boundary, so
      the async badge is passed in as a child instead of imported here. */
  safetySlot?: ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const locale = useLocale();
  const text = copy[locale];
  const [query, setQuery] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  const mobileNavSections = buildNavSections({ shellEnabled, agentStudioRedirect }).map((section) => ({
    name: text.groups[section.id],
    items: section.items
      .filter((item) => isVisibleOnSurface(item, "mobile"))
      .map((item) => ({
        name: labelFor(text, item.id),
        href: item.href,
      })),
  }));
  const activePath = splitLocalePath(pathname).pathname;
  const disableNavigationPrefetch =
    activePath === "/hermes" || activePath.startsWith("/hermes/");

  useEffect(() => {
    if (!menuOpen) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuOpen(false);
        menuButtonRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [menuOpen]);

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const symbol = query.trim().toUpperCase();
    if (!symbol) {
      return;
    }
    router.push(localizePath(`/data-explorer?symbol=${encodeURIComponent(symbol)}&provider=futu`, locale));
  };

  return (
    <>
    <header className="fixed top-0 left-0 right-0 z-40 flex h-[var(--spacing-topbar-height)] items-center justify-between border-b border-border-subtle bg-bg-base/80 px-3 backdrop-blur-md lg:left-[220px] lg:px-6">
      <div className="flex h-full min-w-0 w-full items-center gap-3 lg:gap-8">
        <button
          aria-controls="mobile-navigation"
          aria-expanded={menuOpen}
          aria-label={text.mobileMenu}
          className="app-touch-target flex shrink-0 items-center justify-center rounded-lg border border-border-subtle text-text-primary lg:hidden"
          onClick={() => setMenuOpen((value) => !value)}
          ref={menuButtonRef}
          type="button"
        >
          {menuOpen ? <X size={18} /> : <Menu size={18} />}
        </button>
        <form className="relative hidden md:flex w-full max-w-[260px] items-center" onSubmit={submitSearch}>
          <Search className="absolute left-2.5 text-text-secondary" size={14} />
          <input
            aria-label={text.search}
            className="app-touch-target w-full max-w-[260px] rounded-lg border border-border-subtle bg-bg-surface py-1.5 pl-8 pr-3 font-sans text-[13px] text-text-primary placeholder-text-secondary focus:border-info focus:outline-none focus:ring-1 focus:ring-info"
            onChange={(event) => setQuery(event.target.value)}
            placeholder={text.search}
            type="text"
            value={query}
          />
        </form>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {safetySlot}
        <Suspense fallback={<LocaleToggleFallback />}>
          <LocaleToggle />
        </Suspense>
        <div className="hidden items-center gap-1 border-l border-border-subtle pl-3 text-text-secondary lg:flex">
          <Link
            aria-label={text.openHermes}
            className="app-touch-target flex cursor-pointer items-center justify-center rounded-lg transition-colors hover:bg-bg-surface hover:text-info"
            href={localizePath("/hermes", locale)}
            prefetch={disableNavigationPrefetch ? false : undefined}
          >
            <Terminal size={18} />
          </Link>
          <Link
            aria-label={text.openSettings}
            className="app-touch-target flex cursor-pointer items-center justify-center rounded-lg transition-colors hover:bg-bg-surface hover:text-info"
            href={localizePath("/settings", locale)}
            prefetch={disableNavigationPrefetch ? false : undefined}
          >
            <Settings size={18} />
          </Link>
        </div>
      </div>
    </header>
    {menuOpen ? (
      <div className="fixed left-0 right-0 top-[var(--spacing-topbar-height)] z-50 max-h-[calc(100dvh-var(--spacing-topbar-height))] overflow-y-auto border-b border-border-subtle bg-bg-sidebar p-3 shadow-xl lg:hidden">
        <nav aria-label={text.mobileMenu} className="space-y-4" id="mobile-navigation">
          {mobileNavSections.map((section) => (
            <section key={section.name}>
              <h2 className="px-1 pb-2 font-label-caps text-[10px] text-text-secondary/70">
                {section.name}
              </h2>
              <div className="grid grid-cols-2 gap-2">
                {section.items.map((item) => {
                  const isActive =
                    activePath === item.href ||
                    (item.href !== "/" && activePath.startsWith(`${item.href}/`));
                  return (
                  <Link
                    aria-current={activePath === item.href ? "page" : undefined}
                    className={`app-touch-target flex items-center rounded-lg border px-3 font-body-sm ${
                      isActive
                        ? "border-border-subtle bg-bg-sidebar-muted text-text-primary"
                        : "border-border-subtle text-text-primary hover:bg-bg-sidebar-muted"
                    }`}
                    href={localizePath(item.href, locale)}
                    key={`${section.name}-${item.href}-${item.name}`}
                    prefetch={disableNavigationPrefetch ? false : undefined}
                    onClick={() => setMenuOpen(false)}
                  >
                    {item.name}
                  </Link>
                  );
                })}
              </div>
            </section>
          ))}
        </nav>
      </div>
    ) : null}
    </>
  );
}
