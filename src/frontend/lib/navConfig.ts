import type { LucideIcon } from "lucide-react";
import {
  BadgeDollarSign,
  Beaker,
  BookOpen,
  BriefcaseBusiness,
  Database,
  FileText,
  FlaskConical,
  Globe2,
  HelpCircle,
  LayoutDashboard,
  LineChart,
  ListFilter,
  Map,
  Newspaper,
  Radar,
  ScrollText,
  Settings,
  Sparkles,
  Sunrise,
  Wrench,
  Zap,
} from "lucide-react";

export type NavSurface = "sidebar" | "mobile";

export type NavItemId =
  | "dashboard"
  | "hermes"
  | "brief"
  | "dataExplorer"
  | "factorLab"
  | "backtester"
  | "replications"
  | "experiments"
  | "paperTrading"
  | "positionMap"
  | "optionsScreener"
  | "optionsRadar"
  | "optionsTools"
  | "buySide"
  | "asiaRadar"
  | "aiNews"
  | "orderBook"
  | "agentStudio"
  | "settings"
  | "docs"
  | "support";

export type NavItem = {
  id: NavItemId;
  href: string;
  icon: LucideIcon;
  surfaces?: NavSurface[];
};

export type NavSection = {
  id: "research" | "paper" | "options" | "markets" | "system";
  items: NavItem[];
};

const dashboardItem: NavItem = {
  id: "dashboard",
  href: "/",
  icon: LayoutDashboard,
};

const hermesItem: NavItem = {
  id: "hermes",
  href: "/hermes",
  icon: Sparkles,
};

const briefItem: NavItem = {
  id: "brief",
  href: "/brief",
  icon: Sunrise,
};

const researchTail: NavItem[] = [
  { id: "dataExplorer", href: "/data-explorer", icon: Database },
  // Factor Lab / Backtester / Experiments: routes stay reachable for audit,
  // but the entries are hidden from every nav surface — Hermes drives the
  // research pipeline, so these expert pages no longer earn sidebar slots.
  { id: "factorLab", href: "/factor-lab", icon: FlaskConical, surfaces: [] },
  { id: "backtester", href: "/backtest", icon: LineChart, surfaces: [] },
  { id: "replications", href: "/strategies", icon: ScrollText },
  { id: "experiments", href: "/experiments", icon: Beaker, surfaces: [] },
];

const paperSection: NavSection = {
  id: "paper",
  items: [
    { id: "paperTrading", href: "/paper-trading", icon: BriefcaseBusiness },
    { id: "positionMap", href: "/position-map", icon: Map },
  ],
};

const optionsSection: NavSection = {
  id: "options",
  items: [
    { id: "optionsScreener", href: "/options-screener", icon: ListFilter },
    { id: "optionsRadar", href: "/options-radar", icon: Radar },
    { id: "optionsTools", href: "/options-tools", icon: Wrench },
    { id: "buySide", href: "/options-buyside", icon: BadgeDollarSign },
  ],
};

const marketsSection: NavSection = {
  id: "markets",
  items: [
    { id: "asiaRadar", href: "/asia-radar", icon: Globe2 },
    { id: "aiNews", href: "/ai-news", icon: Newspaper },
    { id: "orderBook", href: "/polymarket", icon: BookOpen },
    { id: "agentStudio", href: "/agent-studio", icon: Zap },
  ],
};

const systemSection: NavSection = {
  id: "system",
  items: [
    { id: "settings", href: "/settings", icon: Settings },
    { id: "docs", href: "/docs/reversal-momentum", icon: FileText, surfaces: ["mobile"] },
    { id: "support", href: "/settings", icon: HelpCircle, surfaces: ["mobile"] },
  ],
};

/**
 * Build mode-specific navigation.
 * shellEnabled: Hermes is the sole research home (Dashboard omitted).
 * shellEnabled false: Dashboard is home; Hermes remains a separate read-only entry.
 * Factor Lab / Backtester / Experiments are surface-hidden (routes kept for audit).
 */
export function buildNavSections({
  shellEnabled,
  agentStudioRedirect = false,
}: {
  shellEnabled: boolean;
  agentStudioRedirect?: boolean;
}): NavSection[] {
  const researchItems: NavItem[] = shellEnabled
    ? [hermesItem, briefItem, ...researchTail]
    : [dashboardItem, hermesItem, briefItem, ...researchTail];

  const visibleMarkets = agentStudioRedirect
    ? { ...marketsSection, items: marketsSection.items.filter((item) => item.id !== "agentStudio") }
    : marketsSection;

  return [
    { id: "research", items: researchItems },
    paperSection,
    optionsSection,
    visibleMarkets,
    systemSection,
  ];
}

/** Default product navigation (Hermes shell enabled). Prefer buildNavSections in callers that know the flag. */
export const navSections: NavSection[] = buildNavSections({ shellEnabled: true });

export function isVisibleOnSurface(item: NavItem, surface: NavSurface): boolean {
  return item.surfaces?.includes(surface) ?? true;
}
