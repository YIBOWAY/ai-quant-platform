'use client';

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BadgeDollarSign,
  BriefcaseBusiness,
  LayoutDashboard,
  Zap,
  LineChart,
  FlaskConical,
  Settings,
  Database,
  BookOpen,
  Map,
  Newspaper,
  FileText,
  HelpCircle,
  Plus,
  ListFilter,
  Radar,
  ShieldCheck,
  Wrench,
  ScrollText,
  Beaker
} from "lucide-react";
import { useLocale } from "@/components/LocaleProvider";
import { localizePath, splitLocalePath } from "@/lib/locale";

const copy = {
  en: {
    tagline: "Local research workspace",
    runBacktest: "Run Backtest",
    docs: "Docs",
    support: "Help",
    paperOnly: "Paper-only",
    paperOnlyHint: "Research & simulation. No live trading paths exist.",
    groups: {
      research: "Research Pipeline",
      paper: "Paper Trading",
      options: "Options Research",
      markets: "Markets & AI",
      system: "System",
    },
    nav: {
      dashboard: "Dashboard",
      dataExplorer: "Data Explorer",
      optionsScreener: "Options Screener",
      optionsRadar: "Options Radar",
      optionsTools: "Options Tools",
      buySide: "Buy-side Options",
      factorLab: "Factor Lab",
      backtester: "Backtester",
      replications: "Strategy Catalog",
      experiments: "Experiments",
      paperTrading: "Paper Trading",
      agentStudio: "Agent Studio",
      aiNews: "AI News",
      orderBook: "Polymarket Markets",
      positionMap: "Position Map",
      settings: "Settings",
    },
  },
  zh: {
    tagline: "本地研究环境",
    runBacktest: "运行回测",
    docs: "文档",
    support: "帮助",
    paperOnly: "仅模拟",
    paperOnlyHint: "研究与模拟用途，不存在任何实盘交易路径。",
    groups: {
      research: "研究流水线",
      paper: "模拟交易",
      options: "期权研究",
      markets: "市场与 AI",
      system: "系统",
    },
    nav: {
      dashboard: "仪表盘",
      dataExplorer: "行情浏览",
      optionsScreener: "期权筛选器",
      optionsRadar: "期权雷达",
      optionsTools: "期权工具",
      buySide: "买方期权",
      factorLab: "因子实验室",
      backtester: "回测器",
      replications: "策略目录",
      experiments: "实验管理",
      paperTrading: "模拟交易",
      agentStudio: "智能体工作室",
      aiNews: "AI 新闻",
      orderBook: "Polymarket 市场",
      positionMap: "持仓地图",
      settings: "设置",
    },
  },
};

export function Sidebar() {
  const pathname = usePathname();
  const locale = useLocale();
  const text = copy[locale];
  const activePath = splitLocalePath(pathname).pathname;

  const navSections = [
    {
      name: text.groups.research,
      items: [
        { name: text.nav.dashboard, href: "/", icon: LayoutDashboard },
        { name: text.nav.dataExplorer, href: "/data-explorer", icon: Database },
        { name: text.nav.factorLab, href: "/factor-lab", icon: FlaskConical },
        { name: text.nav.backtester, href: "/backtest", icon: LineChart },
        { name: text.nav.replications, href: "/strategies", icon: ScrollText },
        { name: text.nav.experiments, href: "/experiments", icon: Beaker },
      ],
    },
    {
      name: text.groups.paper,
      items: [
        { name: text.nav.paperTrading, href: "/paper-trading", icon: BriefcaseBusiness },
        { name: text.nav.positionMap, href: "/position-map", icon: Map },
      ],
    },
    {
      name: text.groups.options,
      items: [
        { name: text.nav.optionsScreener, href: "/options-screener", icon: ListFilter },
        { name: text.nav.optionsRadar, href: "/options-radar", icon: Radar },
        { name: text.nav.optionsTools, href: "/options-tools", icon: Wrench },
        { name: text.nav.buySide, href: "/options-buyside", icon: BadgeDollarSign },
      ],
    },
    {
      name: text.groups.markets,
      items: [
        { name: text.nav.aiNews, href: "/ai-news", icon: Newspaper },
        { name: text.nav.orderBook, href: "/polymarket", icon: BookOpen },
        { name: text.nav.agentStudio, href: "/agent-studio", icon: Zap },
      ],
    },
    {
      name: text.groups.system,
      items: [
        { name: text.nav.settings, href: "/settings", icon: Settings },
      ],
    },
  ];

  return (
    <nav
      className="fixed left-0 top-0 z-50 hidden h-full w-[240px] flex-col border-r border-border-subtle bg-bg-sidebar lg:flex"
      data-testid="desktop-sidebar"
    >
      <div className="border-b border-border-subtle p-6">
        <div className="mb-1 font-mono text-lg font-black uppercase tracking-tighter text-accent-success">
          QUANTUM_CORE
        </div>
        <div className="font-sans text-xs tracking-tight text-text-secondary">
          {text.tagline}
        </div>
      </div>

      <div className="border-b border-border-subtle p-4">
        <Link
          className="font-label-caps flex w-full items-center justify-center gap-2 rounded-lg border border-info/40 bg-info/5 py-2 text-info transition-colors hover:bg-bg-sidebar-muted"
          href={localizePath("/backtest", locale)}
        >
          <Plus size={16} />
          <span>{text.runBacktest}</span>
        </Link>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-4">
        <div className="space-y-5">
          {navSections.map((section) => (
            <section key={section.name}>
              <h2 className="px-3 pb-2 font-label-caps text-[10px] text-text-secondary/70">
                {section.name}
              </h2>
              <ul className="space-y-1">
                {section.items.map((item) => {
                  const isActive = activePath === item.href;
                  return (
                    <li key={item.href}>
                      <Link
                        href={localizePath(item.href, locale)}
                        className={`flex items-center gap-3 rounded-lg px-3 py-2 font-sans text-xs tracking-tight transition-colors ${
                          isActive
                            ? "border-l-2 border-text-primary bg-bg-sidebar-muted font-semibold text-text-primary"
                            : "border-l-2 border-transparent text-text-secondary hover:bg-bg-sidebar-muted hover:text-text-primary"
                        }`}
                      >
                        <item.icon size={18} />
                        <span>{item.name}</span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      </div>

      <div className="border-t border-border-subtle px-3 py-4">
        <ul className="space-y-1">
          <li>
            <Link
              href={localizePath("/docs/reversal-momentum", locale)}
              className="flex items-center gap-3 rounded-lg px-3 py-1.5 font-sans text-xs tracking-tight text-text-secondary transition-colors hover:bg-bg-sidebar-muted hover:text-text-primary"
            >
              <FileText size={16} />
              <span>{text.docs}</span>
            </Link>
          </li>
          <li>
            <Link
              href={localizePath("/settings", locale)}
              className="flex items-center gap-3 rounded-lg px-3 py-1.5 font-sans text-xs tracking-tight text-text-secondary transition-colors hover:bg-bg-sidebar-muted hover:text-text-primary"
            >
              <HelpCircle size={16} />
              <span>{text.support}</span>
            </Link>
          </li>
        </ul>
      </div>

      <div className="flex items-center gap-3 border-t border-border-subtle p-4" title={text.paperOnlyHint}>
        <div className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-full border border-info/30 bg-info/5">
          <ShieldCheck size={16} className="text-info" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate font-sans text-xs font-medium text-text-primary">
            {text.paperOnly}
          </div>
          <div className="truncate font-sans text-[10px] text-text-secondary">
            {text.paperOnlyHint}
          </div>
        </div>
      </div>
    </nav>
  );
}
