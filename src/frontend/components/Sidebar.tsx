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
  FileText,
  HelpCircle,
  User,
  Plus,
  ListFilter,
  Wrench,
  ScrollText
} from "lucide-react";
import { useLocale } from "@/components/LocaleProvider";

const copy = {
  en: {
    tagline: "Local Instance v2.4",
    newStrategy: "New Strategy",
    docs: "Docs",
    support: "Support",
    role: "Quant Researcher",
    nav: {
      dashboard: "Dashboard",
      dataExplorer: "Data Explorer",
      optionsScreener: "Options Screener",
      optionsRadar: "Options Radar",
      optionsTools: "Options Tools",
      buySide: "Buy-side Options",
      factorLab: "Factor Lab",
      backtester: "Backtester",
      replications: "Paper Replication",
      experiments: "Experiments",
      paperTrading: "Paper Trading",
      agentStudio: "Agent Studio",
      orderBook: "Order Book",
      positionMap: "Position Map",
      settings: "Settings",
    },
  },
  zh: {
    tagline: "本地实例 v2.4",
    newStrategy: "新建策略",
    docs: "文档",
    support: "帮助",
    role: "量化研究员",
    nav: {
      dashboard: "仪表盘",
      dataExplorer: "行情浏览",
      optionsScreener: "期权筛选器",
      optionsRadar: "期权雷达",
      optionsTools: "期权工具",
      buySide: "买方期权",
      factorLab: "因子实验室",
      backtester: "回测器",
      replications: "策略复现",
      experiments: "实验管理",
      paperTrading: "模拟交易",
      agentStudio: "智能体工作室",
      orderBook: "预测市场盘口",
      positionMap: "持仓地图",
      settings: "设置",
    },
  },
};

export function Sidebar() {
  const pathname = usePathname();
  const locale = useLocale();
  const text = copy[locale];

  const navItems = [
    { name: text.nav.dashboard, href: "/", icon: LayoutDashboard },
    { name: text.nav.dataExplorer, href: "/data-explorer", icon: Database },
    { name: text.nav.optionsScreener, href: "/options-screener", icon: ListFilter },
    { name: text.nav.optionsRadar, href: "/options-radar", icon: ListFilter },
    { name: text.nav.optionsTools, href: "/options-tools", icon: Wrench },
    { name: text.nav.buySide, href: "/options-buyside", icon: BadgeDollarSign },
    { name: text.nav.factorLab, href: "/factor-lab", icon: FlaskConical },
    { name: text.nav.backtester, href: "/backtest", icon: LineChart },
    { name: text.nav.replications, href: "/replications", icon: ScrollText },
    { name: text.nav.experiments, href: "/experiments", icon: FlaskConical },
    { name: text.nav.paperTrading, href: "/paper-trading", icon: BriefcaseBusiness },
    { name: text.nav.agentStudio, href: "/agent-studio", icon: Zap },
    { name: text.nav.orderBook, href: "/order-book", icon: BookOpen },
    { name: text.nav.positionMap, href: "/position-map", icon: Map },
    { name: text.nav.settings, href: "/settings", icon: Settings },
  ];

  return (
    <nav className="fixed left-0 top-0 flex flex-col h-full w-[240px] border-r border-zinc-800 bg-zinc-950 z-50">
      <div className="p-6 border-b border-zinc-800">
        <div className="font-mono font-black text-lg tracking-tighter text-[#00C896] uppercase mb-1">
          QUANTUM_CORE
        </div>
        <div className="font-sans text-xs tracking-tight text-text-secondary">
          {text.tagline}
        </div>
      </div>

      <div className="p-4 border-b border-zinc-800">
        <Link
          className="w-full py-2 border border-[#00C896] text-[#00C896] rounded font-label-caps hover:bg-[#00C896]/10 transition-colors flex items-center justify-center gap-2"
          href="/backtest"
        >
          <Plus size={16} />
          <span>{text.newStrategy}</span>
        </Link>
      </div>

      <div className="flex-1 py-4 overflow-y-auto">
        <ul className="space-y-1 px-3">
          {navItems.map((item) => {
            const isActive = pathname === item.href;
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={`flex items-center gap-3 px-3 py-2 rounded font-sans text-xs tracking-tight transition-colors ${
                    isActive
                      ? "bg-zinc-900 text-[#00C896] border-l-2 border-[#00C896] font-semibold"
                      : "text-zinc-500 hover:bg-zinc-900 hover:text-zinc-200 border-l-2 border-transparent"
                  }`}
                >
                  <item.icon size={18} />
                  <span>{item.name}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </div>

      <div className="px-3 py-4 border-t border-zinc-800">
        <ul className="space-y-1">
          <li>
            <Link
              href="/docs/reversal-momentum"
              className="flex items-center gap-3 px-3 py-1.5 rounded text-zinc-500 hover:bg-zinc-900 hover:text-zinc-200 transition-colors font-sans text-xs tracking-tight"
            >
              <FileText size={16} />
              <span>{text.docs}</span>
            </Link>
          </li>
          <li>
            <Link
              href="/settings"
              className="flex items-center gap-3 px-3 py-1.5 rounded text-zinc-500 hover:bg-zinc-900 hover:text-zinc-200 transition-colors font-sans text-xs tracking-tight"
            >
              <HelpCircle size={16} />
              <span>{text.support}</span>
            </Link>
          </li>
        </ul>
      </div>

      <div className="p-4 border-t border-zinc-800 flex items-center gap-3">
        <div className="w-8 h-8 rounded-full bg-surface-muted border border-border-subtle overflow-hidden flex items-center justify-center">
          <User size={18} className="text-text-secondary" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-sans text-xs font-medium text-text-primary truncate">
            {text.role}
          </div>
          <div className="font-sans text-[10px] text-text-secondary truncate">
            ID: QR-9921
          </div>
        </div>
      </div>
    </nav>
  );
}
