'use client';

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLocale } from "@/components/LocaleProvider";
import { localizePath, splitLocalePath } from "@/lib/locale";
import {
  buildNavSections,
  sectionsForSurface,
  type NavItemId,
} from "@/lib/navConfig";

const copy = {
  en: {
    tagline: "Personal quant workspace",
    docs: "Docs",
    support: "Help",
    groups: {
      research: "Workspace",
      paper: "Paper Trading",
      options: "Options Research",
      markets: "Markets & AI",
      system: "System",
    },
    nav: {
      dashboard: "Dashboard",
      hermes: "Hermes",
      brief: "Daily Brief",
      collection: "Strategies & Factors",
      library: "Candidate Library",
      watch: "Market Outlook",
      companyResearch: "Company Research",
      dataExplorer: "Symbol Charts",
      optionsScreener: "Options Screener",
      optionsRadar: "Options Recommendations",
      optionsTools: "Options Tools",
      buySide: "Buy-side Options",
      asiaRadar: "Asia Valuation",
      marketCrossSection: "US Risk",
      factorLab: "Factor Lab",
      backtester: "Backtester",
      replications: "Strategy Catalog",
      experiments: "Experiments",
      paperTrading: "Paper Account",
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
    tagline: "个人量化助手",
    docs: "文档",
    support: "帮助",
    groups: {
      research: "工作台",
      paper: "模拟交易",
      options: "期权研究",
      markets: "市场与 AI",
      system: "系统",
    },
    nav: {
      dashboard: "仪表盘",
      hermes: "Hermes 助手",
      brief: "日报",
      collection: "策略与因子",
      library: "候选库",
      watch: "市场研判",
      companyResearch: "公司研究",
      dataExplorer: "个股行情",
      optionsScreener: "期权筛选",
      optionsRadar: "期权推荐",
      optionsTools: "期权工具",
      buySide: "买方期权",
      asiaRadar: "亚洲泡沫",
      marketCrossSection: "美股风险",
      factorLab: "因子实验室",
      backtester: "回测器",
      replications: "策略目录",
      experiments: "实验管理",
      paperTrading: "模拟账户",
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

  const navSections = sectionsForSurface(
    buildNavSections({ shellEnabled, agentStudioRedirect }),
    "sidebar",
  ).map((section) => ({
    name: text.groups[section.id],
    items: section.items.map((item) => ({
      name: labelFor(text.nav, item.id),
      href: item.href,
      icon: item.icon,
      aliases: item.aliases ?? [],
    })),
  }));

  return (
    <nav
      className="fixed left-0 top-0 z-50 hidden h-full w-[220px] flex-col border-r border-border-subtle bg-bg-sidebar lg:flex"
      data-testid="desktop-sidebar"
    >
      <div className="px-6 pb-7 pt-8">
        <div className="mb-2 flex items-center gap-3 font-sans text-xl font-semibold tracking-tight text-text-primary">
          <span aria-hidden="true" className="grid size-8 place-items-center rounded-md border border-[var(--color-hermes)]/40 font-editorial-serif text-xl text-[var(--color-hermes)]">H</span>
          Hermes
        </div>
        <div className="font-sans text-[11px] tracking-wide text-text-secondary">
          {text.tagline}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-4">
        <div className="space-y-5">
          {navSections.map((section) => (
            <section key={section.name}>
              {section.items.length === 0 ? null : (
              <h2 className="px-3 pb-2 font-label-caps text-[10px] text-text-secondary">
                {section.name}
              </h2>
              )}
              <ul className="space-y-1">
                {section.items.map((item) => {
                  const targets = [item.href, ...item.aliases];
                  const isActive = targets.some(
                    (target) =>
                      activePath === target ||
                      (target !== "/" && activePath.startsWith(`${target}/`)),
                  );
                  return (
                    <li key={item.href}>
                      <Link
                        aria-current={isActive ? "page" : undefined}
                        href={localizePath(item.href, locale)}
                        prefetch={disableNavigationPrefetch ? false : undefined}
                        className={`app-touch-target flex items-center gap-3 rounded-md px-3 font-sans text-[13px] tracking-tight transition-colors ${
                          isActive
                            ? "border-l-2 border-[var(--color-hermes)] bg-bg-sidebar-muted font-medium text-text-primary"
                            : "border-l-2 border-transparent text-text-secondary hover:bg-bg-sidebar-muted hover:text-text-primary"
                        }`}
                      >
                        <item.icon size={17} strokeWidth={1.5} />
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

    </nav>
  );
}
