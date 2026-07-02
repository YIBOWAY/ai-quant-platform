'use client';

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useState } from "react";
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
    paperTrading: "Paper Trading",
    settings: "Settings",
    mobileMenu: "Open navigation",
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
    paperTrading: "模拟交易",
    settings: "设置",
    mobileMenu: "打开导航",
  },
};

export function TopBar() {
  const pathname = usePathname();
  const router = useRouter();
  const locale = useLocale();
  const text = copy[locale];
  const [query, setQuery] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);

  const mobileNavItems = [
    { name: text.dashboard, href: "/" },
    { name: text.runBacktest, href: "/backtest" },
    { name: text.paperTrading, href: "/paper-trading" },
    { name: text.marketData, href: "/data-explorer" },
    { name: text.options, href: "/options-screener" },
    { name: text.replications, href: "/strategies" },
    { name: text.orderBook, href: "/polymarket" },
    { name: text.aiNews, href: "/ai-news" },
    { name: text.positionMap, href: "/position-map" },
    { name: text.settings, href: "/settings" },
  ];
  const activePath = splitLocalePath(pathname).pathname;

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
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border-subtle text-text-primary lg:hidden"
          onClick={() => setMenuOpen((value) => !value)}
          type="button"
        >
          {menuOpen ? <X size={18} /> : <Menu size={18} />}
        </button>
        <form className="relative hidden md:flex items-center" onSubmit={submitSearch}>
          <Search className="absolute left-3 text-text-secondary" size={16} />
          <input
            aria-label={text.search}
            className="w-64 rounded-lg border border-border-subtle bg-bg-surface py-1.5 pl-9 pr-4 font-sans text-sm text-text-primary placeholder-text-secondary focus:border-info focus:outline-none focus:ring-1 focus:ring-info"
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
            className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg transition-colors hover:bg-bg-surface hover:text-info"
            href={localizePath("/agent-studio", locale)}
          >
            <Terminal size={18} />
          </Link>
          <Link
            aria-label="Open settings"
            className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg transition-colors hover:bg-bg-surface hover:text-info"
            href={localizePath("/settings", locale)}
          >
            <Settings size={18} />
          </Link>
        </div>
      </div>
    </header>
    {menuOpen ? (
      <div className="fixed left-0 right-0 top-16 z-50 border-b border-border-subtle bg-bg-base p-3 shadow-xl lg:hidden">
        <nav aria-label={text.mobileMenu} className="grid grid-cols-2 gap-2" id="mobile-navigation">
          {mobileNavItems.map((item) => (
            <Link
              aria-current={activePath === item.href ? "page" : undefined}
              className={`rounded border px-3 py-2 font-body-sm ${
                activePath === item.href
                  ? "border-border-subtle bg-bg-surface-muted text-text-primary"
                  : "border-border-subtle text-text-primary hover:bg-bg-surface"
              }`}
              href={localizePath(item.href, locale)}
              key={item.href}
              onClick={() => setMenuOpen(false)}
            >
              {item.name}
            </Link>
          ))}
        </nav>
      </div>
    ) : null}
    </>
  );
}
