'use client';

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  FileText,
  HelpCircle,
} from "lucide-react";
import { useLocale } from "@/components/LocaleProvider";
import { localizePath, splitLocalePath } from "@/lib/locale";
import {
  buildNavSections,
  isVisibleOnSurface,
  type NavItemId,
} from "@/lib/navConfig";

const copy = {
  en: {
    tagline: "Local research workspace",
    docs: "Docs",
    support: "Help",
    groups: {
      research: "Research Pipeline",
      paper: "Paper Trading",
      options: "Options Research",
      markets: "Markets & AI",
      system: "System",
    },
    nav: {
      dashboard: "Dashboard",
      hermes: "Hermes",
      brief: "Morning Brief",
      dataExplorer: "Data Explorer",
      optionsScreener: "Options Screener",
      optionsRadar: "Options Radar",
      optionsTools: "Options Tools",
      buySide: "Buy-side Options",
      asiaRadar: "Asia Radar",
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
      docs: "Docs",
      support: "Help",
    },
  },
  zh: {
    tagline: "本地研究环境",
    docs: "文档",
    support: "帮助",
    groups: {
      research: "研究流水线",
      paper: "模拟交易",
      options: "期权研究",
      markets: "市场与 AI",
      system: "系统",
    },
    nav: {
      dashboard: "仪表盘",
      hermes: "Hermes 工作台",
      brief: "每日晨报",
      dataExplorer: "行情浏览",
      optionsScreener: "期权筛选器",
      optionsRadar: "期权雷达",
      optionsTools: "期权工具",
      buySide: "买方期权",
      asiaRadar: "亚洲雷达",
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
      docs: "文档",
      support: "帮助",
    },
  },
};

function labelFor(
  nav: (typeof copy)["en"]["nav"] | (typeof copy)["zh"]["nav"],
  id: NavItemId,
): string {
  const value = nav[id as keyof typeof nav];
  return typeof value === "string" ? value : id;
}

export function Sidebar({
  shellEnabled,
  agentStudioRedirect = false,
}: {
  shellEnabled: boolean;
  agentStudioRedirect?: boolean;
}) {
  const pathname = usePathname();
  const locale = useLocale();
  const text = copy[locale];
  const activePath = splitLocalePath(pathname).pathname;
  const disableNavigationPrefetch =
    activePath === "/hermes" || activePath.startsWith("/hermes/");

  const navSections = buildNavSections({ shellEnabled, agentStudioRedirect }).map((section) => ({
    name: text.groups[section.id],
    items: section.items
      .filter((item) => isVisibleOnSurface(item, "sidebar"))
      .map((item) => ({
        name: labelFor(text.nav, item.id),
        href: item.href,
        icon: item.icon,
      })),
  }));

  return (
    <nav
      className="fixed left-0 top-0 z-50 hidden h-full w-[220px] flex-col border-r border-border-subtle bg-bg-sidebar lg:flex"
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

      <div className="flex-1 overflow-y-auto px-3 py-4">
        <div className="space-y-5">
          {navSections.map((section) => (
            <section key={section.name}>
              <h2 className="px-3 pb-2 font-label-caps text-[10px] text-text-secondary opacity-60">
                {section.name}
              </h2>
              <ul className="space-y-1">
                {section.items.map((item) => {
                  const isActive =
                    activePath === item.href ||
                    (item.href !== "/" && activePath.startsWith(`${item.href}/`));
                  return (
                    <li key={item.href}>
                      <Link
                        aria-current={isActive ? "page" : undefined}
                        href={localizePath(item.href, locale)}
                        prefetch={disableNavigationPrefetch ? false : undefined}
                        className={`app-touch-target flex items-center gap-3 rounded-lg px-3 font-sans text-xs tracking-tight transition-colors ${
                          isActive
                            ? "border-l-2 border-[var(--color-hermes)] bg-transparent font-semibold text-text-primary"
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
              prefetch={disableNavigationPrefetch ? false : undefined}
              className="app-touch-target flex items-center gap-3 rounded-lg px-3 font-sans text-xs tracking-tight text-text-secondary transition-colors hover:bg-bg-sidebar-muted hover:text-text-primary"
            >
              <FileText size={16} />
              <span>{text.docs}</span>
            </Link>
          </li>
          <li>
            <Link
              href={localizePath("/settings", locale)}
              prefetch={disableNavigationPrefetch ? false : undefined}
              className="app-touch-target flex items-center gap-3 rounded-lg px-3 font-sans text-xs tracking-tight text-text-secondary transition-colors hover:bg-bg-sidebar-muted hover:text-text-primary"
            >
              <HelpCircle size={16} />
              <span>{text.support}</span>
            </Link>
          </li>
        </ul>
      </div>
    </nav>
  );
}
