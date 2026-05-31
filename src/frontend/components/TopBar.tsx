'use client';

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useState } from "react";
import { Bell, Terminal, Power, Search } from "lucide-react";
import { useLocale } from "@/components/LocaleProvider";
import { LocaleToggle } from "@/components/LocaleToggle";

const copy = {
  en: {
    search: "Search symbol...",
    runBacktest: "Run Backtest",
    marketData: "Market Data",
    options: "Options",
    replications: "Replications",
    orderBook: "Order Book",
    positionMap: "Position Map",
  },
  zh: {
    search: "搜索标的...",
    runBacktest: "运行回测",
    marketData: "行情数据",
    options: "期权",
    replications: "策略复现",
    orderBook: "预测市场盘口",
    positionMap: "持仓地图",
  },
};

export function TopBar() {
  const pathname = usePathname();
  const router = useRouter();
  const locale = useLocale();
  const text = copy[locale];
  const [query, setQuery] = useState("");

  const topNavItems = [
    { name: text.marketData, href: "/data-explorer" },
    { name: text.options, href: "/options-screener" },
    { name: text.replications, href: "/replications" },
    { name: text.orderBook, href: "/order-book" },
    { name: text.positionMap, href: "/position-map" },
  ];

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const symbol = query.trim().toUpperCase();
    if (!symbol) {
      return;
    }
    router.push(`/data-explorer?symbol=${encodeURIComponent(symbol)}&provider=futu`);
  };

  return (
    <header className="fixed top-0 left-[240px] right-0 z-40 px-6 flex items-center justify-between h-16 border-b border-zinc-800 bg-zinc-950/80 backdrop-blur-md">
      <div className="flex items-center gap-8 h-full w-full">
        <form className="relative hidden md:flex items-center" onSubmit={submitSearch}>
          <Search className="absolute left-3 text-zinc-500" size={16} />
          <input
            aria-label={text.search}
            className="bg-zinc-900 border border-zinc-800 text-text-primary rounded pl-9 pr-4 py-1.5 text-sm w-64 focus:outline-none focus:border-info focus:ring-1 focus:ring-info placeholder-zinc-500 font-sans"
            onChange={(event) => setQuery(event.target.value)}
            placeholder={text.search}
            type="text"
            value={query}
          />
        </form>
        <nav className="flex items-center gap-6 h-full flex-1">
          {topNavItems.map((item) => {
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`transition-colors font-sans text-sm cursor-pointer h-full flex items-center border-b-2 ${
                  isActive
                    ? "text-[#00C896] border-[#00C896]"
                    : "text-zinc-400 hover:text-zinc-100 border-transparent"
                }`}
              >
                {item.name}
              </Link>
            );
          })}
        </nav>
      </div>

      <div className="flex items-center gap-4">
        <LocaleToggle />
        <Link
          className="px-4 py-1.5 bg-[#00C896]/10 border border-[#00C896]/30 text-[#00C896] rounded hover:bg-[#00C896]/20 transition-colors font-label-caps uppercase text-xs font-bold whitespace-nowrap"
          href="/backtest"
        >
          {text.runBacktest}
        </Link>
        <div className="flex items-center gap-2 border-l border-zinc-800 pl-4 text-zinc-400">
          <Link
            aria-label="Open radar alerts"
            className="hover:text-[#00C896] transition-colors cursor-pointer w-8 h-8 flex items-center justify-center rounded hover:bg-zinc-900"
            href="/options-radar"
          >
            <Bell size={18} />
          </Link>
          <Link
            aria-label="Open agent console"
            className="hover:text-[#00C896] transition-colors cursor-pointer w-8 h-8 flex items-center justify-center rounded hover:bg-zinc-900"
            href="/agent-studio"
          >
            <Terminal size={18} />
          </Link>
          <Link
            aria-label="Open settings"
            className="hover:text-[#00C896] transition-colors cursor-pointer w-8 h-8 flex items-center justify-center rounded hover:bg-zinc-900"
            href="/settings"
          >
            <Power size={18} />
          </Link>
        </div>
      </div>
    </header>
  );
}
