'use client';

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useEffect, useRef, useState } from "react";
import { Menu, Search, Settings, Terminal, X } from "lucide-react";
import { useLocale } from "@/components/LocaleProvider";
import { LocaleToggle } from "@/components/LocaleToggle";
import { localizePath, splitLocalePath } from "@/lib/locale";

const copy = {
  en: {
    search: "Search symbol...",
    runBacktest: "Run Backtest",
    marketData: "Market Data",
    options: "Options",
    replications: "Strategy Catalog",
    orderBook: "Polymarket Markets",
    aiNews: "AI News",
    positionMap: "Position Map",
    dashboard: "Dashboard",
    dataExplorer: "Data Explorer",
    factorLab: "Factor Lab",
    backtester: "Backtester",
    experiments: "Experiments",
    paperTrading: "Paper Trading",
    optionsScreener: "Options Screener",
    optionsRadar: "Options Radar",
    optionsTools: "Options Tools",
    buySide: "Buy-side Options",
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
    runBacktest: "运行回测",
    marketData: "行情数据",
    options: "期权",
    replications: "策略目录",
    orderBook: "Polymarket 市场",
    aiNews: "AI 新闻",
    positionMap: "持仓地图",
    dashboard: "仪表盘",
    dataExplorer: "行情浏览",
    factorLab: "因子实验室",
    backtester: "回测器",
    experiments: "实验管理",
    paperTrading: "模拟交易",
    optionsScreener: "期权筛选器",
    optionsRadar: "期权雷达",
    optionsTools: "期权工具",
    buySide: "买方期权",
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

export function TopBar() {
  const pathname = usePathname();
  const router = useRouter();
  const locale = useLocale();
  const text = copy[locale];
  const [query, setQuery] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  const mobileNavSections = [
    {
      name: text.groups.research,
      items: [
        { name: text.dashboard, href: "/" },
        { name: text.dataExplorer, href: "/data-explorer" },
        { name: text.factorLab, href: "/factor-lab" },
        { name: text.backtester, href: "/backtest" },
        { name: text.replications, href: "/strategies" },
        { name: text.experiments, href: "/experiments" },
      ],
    },
    {
      name: text.groups.paper,
      items: [
        { name: text.paperTrading, href: "/paper-trading" },
        { name: text.positionMap, href: "/position-map" },
      ],
    },
    {
      name: text.groups.options,
      items: [
        { name: text.optionsScreener, href: "/options-screener" },
        { name: text.optionsRadar, href: "/options-radar" },
        { name: text.optionsTools, href: "/options-tools" },
        { name: text.buySide, href: "/options-buyside" },
      ],
    },
    {
      name: text.groups.markets,
      items: [
        { name: text.aiNews, href: "/ai-news" },
        { name: text.orderBook, href: "/polymarket" },
        { name: text.agentStudio, href: "/agent-studio" },
      ],
    },
    {
      name: text.groups.system,
      items: [
        { name: text.settings, href: "/settings" },
        { name: text.docs, href: "/docs/reversal-momentum" },
        { name: text.support, href: "/settings" },
      ],
    },
  ];
  const activePath = splitLocalePath(pathname).pathname;

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
    <header className="fixed top-0 left-0 right-0 z-40 flex h-16 items-center justify-between border-b border-border-subtle bg-bg-base/80 px-3 backdrop-blur-md lg:left-[240px] lg:px-6">
      <div className="flex h-full min-w-0 w-full items-center gap-3 lg:gap-8">
        <button
          aria-controls="mobile-navigation"
          aria-expanded={menuOpen}
          aria-label={text.mobileMenu}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border-subtle text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info lg:hidden"
          onClick={() => setMenuOpen((value) => !value)}
          ref={menuButtonRef}
          type="button"
        >
          {menuOpen ? <X size={18} /> : <Menu size={18} />}
        </button>
        <form className="relative hidden md:flex items-center" onSubmit={submitSearch}>
          <Search className="absolute left-3 text-text-secondary" size={16} />
          <input
            aria-label={text.search}
            className="w-64 rounded-lg border border-border-subtle bg-bg-surface py-1.5 pl-9 pr-4 font-sans text-sm text-text-primary placeholder-text-secondary focus:border-info focus:outline-none focus:ring-1 focus:ring-info focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
            onChange={(event) => setQuery(event.target.value)}
            placeholder={text.search}
            type="text"
            value={query}
          />
        </form>
      </div>

      <div className="flex shrink-0 items-center gap-2 lg:gap-4">
        <LocaleToggle />
        <div className="hidden items-center gap-2 border-l border-border-subtle pl-4 text-text-secondary lg:flex">
          <Link
            aria-label="Open agent console"
            className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg transition-colors hover:bg-bg-surface hover:text-info focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
            href={localizePath("/agent-studio", locale)}
          >
            <Terminal size={18} />
          </Link>
          <Link
            aria-label="Open settings"
            className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg transition-colors hover:bg-bg-surface hover:text-info focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
            href={localizePath("/settings", locale)}
          >
            <Settings size={18} />
          </Link>
        </div>
      </div>
    </header>
    {menuOpen ? (
      <div className="fixed left-0 right-0 top-16 z-50 max-h-[calc(100dvh-4rem)] overflow-y-auto border-b border-border-subtle bg-bg-sidebar p-3 shadow-xl lg:hidden">
        <nav aria-label={text.mobileMenu} className="space-y-4" id="mobile-navigation">
          {mobileNavSections.map((section) => (
            <section key={section.name}>
              <h2 className="px-1 pb-2 font-label-caps text-[10px] text-text-secondary/70">
                {section.name}
              </h2>
              <div className="grid grid-cols-2 gap-2">
                {section.items.map((item) => (
                  <Link
                    aria-current={activePath === item.href ? "page" : undefined}
                    className={`rounded-lg border px-3 py-2 font-body-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info ${
                      activePath === item.href
                        ? "border-border-subtle bg-bg-sidebar-muted text-text-primary"
                        : "border-border-subtle text-text-primary hover:bg-bg-sidebar-muted"
                    }`}
                    href={localizePath(item.href, locale)}
                    key={`${section.name}-${item.href}-${item.name}`}
                    onClick={() => setMenuOpen(false)}
                  >
                    {item.name}
                  </Link>
                ))}
              </div>
            </section>
          ))}
        </nav>
      </div>
    ) : null}
    </>
  );
}
