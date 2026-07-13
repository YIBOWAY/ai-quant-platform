import type { LucideIcon } from "lucide-react";
import {
  BadgeDollarSign,
  Beaker,
  BookOpen,
  BriefcaseBusiness,
  Database,
  FileText,
  FlaskConical,
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
  Wrench,
  Zap,
} from "lucide-react";

export type NavSurface = "sidebar" | "mobile";

export type NavItemId =
  | "dashboard"
  | "hermes"
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

const researchTail: NavItem[] = [
  { id: "dataExplorer", href: "/data-explorer", icon: Database },
  { id: "factorLab", href: "/factor-lab", icon: FlaskConical },
  { id: "backtester", href: "/backtest", icon: LineChart },
  { id: "replications", href: "/strategies", icon: ScrollText },
  { id: "experiments", href: "/experiments", icon: Beaker },
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
 * Factor Lab / Backtester / Experiments / Agent Studio stay in both modes.
 */
export function buildNavSections({
  shellEnabled,
}: {
  shellEnabled: boolean;
}): NavSection[] {
  const researchItems: NavItem[] = shellEnabled
    ? [hermesItem, ...researchTail]
    : [dashboardItem, hermesItem, ...researchTail];

  return [
    { id: "research", items: researchItems },
    paperSection,
    optionsSection,
    marketsSection,
    systemSection,
  ];
}

/** Default product navigation (Hermes shell enabled). Prefer buildNavSections in callers that know the flag. */
export const navSections: NavSection[] = buildNavSections({ shellEnabled: true });

export function isVisibleOnSurface(item: NavItem, surface: NavSurface): boolean {
  return item.surfaces?.includes(surface) ?? true;
}
