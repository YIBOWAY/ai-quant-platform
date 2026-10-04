'use client';

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { FormEvent, ReactNode } from "react";
import { Suspense, useEffect, useRef, useState } from "react";
import { Menu, Search, Settings, Terminal, X } from "lucide-react";
import { useLocale } from "@/components/LocaleProvider";
import { LocaleToggle, LocaleToggleFallback } from "@/components/LocaleToggle";
import { SecuritySearchInput } from "@/components/SecuritySearchInput";
import { localizePath, splitLocalePath } from "@/lib/locale";
import {
  buildNavSections,
  sectionsForSurface,
  type NavItemId,
} from "@/lib/navConfig";

const copy = {
  en: {
    search: "Find a symbol",
    workspace: "Quant workspace",
    marketData: "Market Data",
    options: "Options",
    replications: "Strategy Catalog",
    orderBook: "Polymarket Markets",
    aiNews: "AI News",
    positionMap: "Position Map",
    dashboard: "Dashboard",
    hermes: "Hermes",
    brief: "Daily Brief",
    collection: "Strategies & Factors",
    library: "Candidate Library",
    openHermes: "Open Hermes Assistant",
    openSettings: "Open settings",
    watch: "Market Outlook",
    companyResearch: "Company Research",
    dataExplorer: "Symbol Charts",
    factorLab: "Factor Lab",
    backtester: "Backtester",
    experiments: "Experiments",
    paperTrading: "Paper Account",
    optionsScreener: "Options Screener",
    optionsRadar: "Options Recommendations",
    optionsTools: "Options Tools",
    buySide: "Buy-side Options",
    asiaRadar: "Asia Valuation",
    marketCrossSection: "US Risk",
    agentStudio: "Agent Studio",
    settings: "Settings",
    docs: "Docs",
    support: "Help",
    mobileMenu: "Open navigation",
    groups: {
      research: "Workspace",
      paper: "Paper Trading",
      options: "Options Research",
      markets: "Markets & AI",
      system: "System",
    },
  },
  zh: {
    search: "搜索标的代码",
    workspace: "量化工作台",
    marketData: "行情数据",
    options: "期权",
    replications: "策略目录",
    orderBook: "Polymarket 市场",
    aiNews: "AI 新闻",
    positionMap: "持仓地图",
    dashboard: "仪表盘",
    hermes: "Hermes 助手",
    brief: "日报",
    collection: "策略与因子",
    library: "候选库",
    openHermes: "打开 Hermes 助手",
    openSettings: "打开设置",
    watch: "市场研判",
    companyResearch: "公司研究",
    dataExplorer: "个股行情",
    factorLab: "因子实验室",
    backtester: "回测器",
    experiments: "实验管理",
    paperTrading: "模拟账户",
    optionsScreener: "期权筛选",
    optionsRadar: "期权推荐",
    optionsTools: "期权工具",
    buySide: "买方期权",
    asiaRadar: "亚洲泡沫",
    marketCrossSection: "美股风险",
    agentStudio: "智能体工作室",
    settings: "设置",
    docs: "文档",
    support: "帮助",
    mobileMenu: "打开导航",
    groups: {
      research: "工作台",
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

  const navSections = buildNavSections({ shellEnabled, agentStudioRedirect });
  const mobileNavSections = sectionsForSurface(
    navSections,
    "mobile",
  ).map((section) => ({
    name: text.groups[section.id],
    items: section.items.map((item) => ({
      name: labelFor(text, item.id),
      href: item.href,
    })),
  }));
  const activePath = splitLocalePath(pathname).pathname;
  const activeItem = navSections.flatMap((section) => section.items)
    .filter((item) => [item.href, ...(item.aliases ?? [])].some((href) => {
      const path = href.split("?")[0];
      return activePath === path || (path !== "/" && activePath.startsWith(`${path}/`));
    }))
    .sort((left, right) => right.href.length - left.href.length)[0];
  const pageTitle = activePath === "/research-evaluation"
    ? (locale === "zh" ? "策略研究与回测" : "Strategy research")
    : activePath === "/strategy-library"
    ? (locale === "zh" ? "我的策略" : "My strategies")
    : activeItem ? labelFor(text, activeItem.id) : text.workspace;
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

  const openSymbol = (value: string) => {
    const symbol = value.trim().toUpperCase();
    if (!symbol) {
      return;
    }
    router.push(
      localizePath(`/watch?pane=quotes&symbol=${encodeURIComponent(symbol)}&provider=futu`, locale),
    );
    setMenuOpen(false);
  };
  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    openSymbol(query);
  };

  return (
    <>
    <header className="fixed top-0 left-0 right-0 z-40 flex h-[var(--spacing-topbar-height)] items-center justify-between gap-3 border-b border-border-subtle bg-bg-base px-3 lg:left-[220px] lg:px-6" data-topbar>
      <div className="flex min-w-0 flex-1 items-center gap-2 lg:gap-3">
        <button
          aria-controls="mobile-navigation"
          aria-expanded={menuOpen}
          aria-label={text.mobileMenu}
          className="app-touch-target flex shrink-0 items-center justify-center rounded-md text-text-secondary hover:bg-bg-surface hover:text-text-primary lg:hidden"
          onClick={() => setMenuOpen((value) => !value)}
          ref={menuButtonRef}
          type="button"
        >
          {menuOpen ? <X size={18} /> : <Menu size={18} />}
        </button>
        <span className="truncate font-sans text-sm font-semibold tracking-tight text-text-primary" data-topbar-page-title>{pageTitle}</span>
      </div>

      <div className="flex shrink-0 items-center gap-1 sm:gap-2">
        <form className="mr-2 hidden w-[180px] items-center gap-2 border-b border-transparent px-1 transition-colors focus-within:border-[var(--color-hermes)] lg:flex" onSubmit={submitSearch} role="search">
          <Search aria-hidden className="shrink-0 text-text-secondary" size={15} />
          <SecuritySearchInput
            label={text.search}
            className="h-11 min-w-0 w-full bg-transparent font-sans text-xs text-text-primary placeholder-text-secondary focus:outline-none"
            onChange={setQuery}
            onSelect={openSymbol}
            locale={locale}
            value={query}
          />
        </form>
        <Link
          aria-label={text.openHermes}
          className="app-touch-target inline-flex shrink-0 items-center justify-center gap-2 rounded-md px-2 text-[var(--color-hermes)] transition-colors hover:bg-bg-surface"
          href={localizePath("/hermes", locale)}
          prefetch={disableNavigationPrefetch ? false : undefined}
        >
          <Terminal aria-hidden size={16} />
          <span className="hidden text-xs font-medium sm:inline">Hermes</span>
        </Link>
        <span aria-hidden className="mx-1 h-4 w-px bg-border-subtle" />
        {safetySlot}
        <Suspense fallback={<LocaleToggleFallback />}>
          <LocaleToggle />
        </Suspense>
          <Link
            aria-label={text.openSettings}
            className="app-touch-target hidden items-center justify-center rounded-md text-text-secondary transition-colors hover:bg-bg-surface hover:text-text-primary lg:flex"
            href={localizePath("/settings", locale)}
            prefetch={disableNavigationPrefetch ? false : undefined}
          >
            <Settings aria-hidden size={16} />
          </Link>
      </div>
    </header>
    {menuOpen ? (
      <div className="fixed left-0 right-0 top-[var(--spacing-topbar-height)] z-50 max-h-[calc(100dvh-var(--spacing-topbar-height))] overflow-y-auto border-b border-border-subtle bg-bg-sidebar p-3 shadow-xl lg:hidden">
        <form className="mb-5 flex items-center gap-3 border-b border-border-subtle px-2 pb-2" onSubmit={(event) => { submitSearch(event); if (query.trim()) setMenuOpen(false); }} role="search">
          <Search aria-hidden className="text-text-secondary" size={16} />
          <SecuritySearchInput label={text.search} className="h-11 w-full min-w-0 bg-transparent text-sm text-text-primary placeholder-text-secondary focus:outline-none" onChange={setQuery} onSelect={openSymbol} locale={locale} value={query} />
          <button aria-label={text.search} className="app-touch-target rounded-md px-3 text-[var(--color-hermes)] hover:bg-bg-surface" type="submit">→</button>
        </form>
        <nav aria-label={text.mobileMenu} className="space-y-4" id="mobile-navigation">
          {mobileNavSections.map((section) => (
            <section key={section.name}>
              {section.items.length === 0 ? null : (
              <h2 className="px-1 pb-2 font-label-caps text-[10px] text-text-secondary/70">
                {section.name}
              </h2>
              )}
              <div className="grid grid-cols-2 gap-1">
                {section.items.map((item) => {
                  const isActive =
                    activePath === item.href ||
                    (item.href !== "/" && activePath.startsWith(`${item.href}/`));
                  return (
                  <Link
                    aria-current={activePath === item.href ? "page" : undefined}
                    className={`app-touch-target flex items-center rounded-md px-3 font-body-sm ${
                      isActive
                        ? "bg-bg-sidebar-muted text-[var(--color-hermes)]"
                        : "text-text-secondary hover:bg-bg-sidebar-muted hover:text-text-primary"
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
