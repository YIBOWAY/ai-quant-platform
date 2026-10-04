import type { LucideIcon } from "lucide-react";
import {
  BadgeDollarSign,
  Beaker,
  BookOpen,
  BriefcaseBusiness,
  Building2,
  Database,
  FileText,
  FlaskConical,
  Globe2,
  Grid3X3,
  HelpCircle,
  Layers,
  LayoutDashboard,
  LayoutGrid,
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
  | "collection"
  | "library"
  | "watch"
  | "companyResearch"
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
  | "marketCrossSection"
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
  aliases?: string[];
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

const collectionItem: NavItem = {
  id: "collection",
  href: "/collection",
  icon: LayoutGrid,
};

const libraryItem: NavItem = {
  id: "library",
  href: "/library",
  icon: Layers,
  surfaces: [],
};

const watchItem: NavItem = {
  id: "watch",
  href: "/watch",
  icon: LineChart,
  aliases: ["/data-explorer", "/asia-radar", "/market-cross-section"],
};

const companyResearchItem: NavItem = {
  id: "companyResearch",
  href: "/company-research",
  icon: Building2,
};

const researchTail: NavItem[] = [
  { id: "dataExplorer", href: "/data-explorer", icon: Database, surfaces: [] },
  { id: "factorLab", href: "/factor-lab", icon: FlaskConical, surfaces: [] },
  { id: "backtester", href: "/backtest", icon: LineChart, surfaces: [] },
  { id: "replications", href: "/strategies", icon: ScrollText, surfaces: [] },
  { id: "experiments", href: "/experiments", icon: Beaker, surfaces: [] },
];

const paperSection: NavSection = {
  id: "paper",
  items: [
    {
      id: "paperTrading",
      href: "/paper-trading",
      icon: BriefcaseBusiness,
      aliases: ["/position-map"],
    },
    { id: "positionMap", href: "/position-map", icon: Map, surfaces: [] },
  ],
};

const optionsSection: NavSection = {
  id: "options",
  items: [
    { id: "optionsScreener", href: "/options-screener", icon: ListFilter },
    { id: "optionsRadar", href: "/options-radar", icon: Radar },
    { id: "optionsTools", href: "/options-tools", icon: Wrench, surfaces: [] },
    { id: "buySide", href: "/options-buyside", icon: BadgeDollarSign },
  ],
};

const marketsSection: NavSection = {
  id: "markets",
  items: [
    { id: "asiaRadar", href: "/asia-radar", icon: Globe2, surfaces: [] },
    { id: "marketCrossSection", href: "/market-cross-section", icon: Grid3X3, surfaces: [] },
    { id: "aiNews", href: "/ai-news", icon: Newspaper },
    { id: "orderBook", href: "/polymarket", icon: BookOpen, surfaces: [] },
    { id: "agentStudio", href: "/agent-studio", icon: Zap, surfaces: [] },
  ],
};

const systemSection: NavSection = {
  id: "system",
  items: [
    { id: "settings", href: "/settings", icon: Settings },
    { id: "docs", href: "/docs/reversal-momentum", icon: FileText, surfaces: ["mobile"] },
    { id: "support", href: "/docs/reversal-momentum", icon: HelpCircle, surfaces: [] },
  ],
};

/**
 * Build mode-specific navigation catalog.
 * Default chrome is `sectionsForSurface(..., "sidebar")`: empty groups are dropped.
 * Lab and select options/markets routes stay in the catalog with surfaces: [].
 */
export function buildNavSections({
  shellEnabled,
  agentStudioRedirect = false,
}: {
  shellEnabled: boolean;
  agentStudioRedirect?: boolean;
}): NavSection[] {
  const researchItems: NavItem[] = shellEnabled
    ? [hermesItem, watchItem, companyResearchItem, briefItem, collectionItem, libraryItem, ...researchTail]
    : [dashboardItem, hermesItem, watchItem, companyResearchItem, briefItem, collectionItem, libraryItem, ...researchTail];

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

export function sectionsForSurface(
  sections: NavSection[],
  surface: NavSurface,
): NavSection[] {
  return sections
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => isVisibleOnSurface(item, surface)),
    }))
    .filter((section) => section.items.length > 0);
}
