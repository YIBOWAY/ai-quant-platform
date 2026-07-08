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

export type NavItem = {
  id: string;
  href: string;
  icon: LucideIcon;
  surfaces?: NavSurface[];
};

export type NavSection = {
  id: "research" | "paper" | "options" | "markets" | "system";
  items: NavItem[];
};

export const navSections: NavSection[] = [
  {
    id: "research",
    items: [
      { id: "dashboard", href: "/", icon: LayoutDashboard },
      { id: "hermes", href: "/hermes", icon: Sparkles },
      { id: "dataExplorer", href: "/data-explorer", icon: Database },
      { id: "factorLab", href: "/factor-lab", icon: FlaskConical },
      { id: "backtester", href: "/backtest", icon: LineChart },
      { id: "replications", href: "/strategies", icon: ScrollText },
      { id: "experiments", href: "/experiments", icon: Beaker },
    ],
  },
  {
    id: "paper",
    items: [
      { id: "paperTrading", href: "/paper-trading", icon: BriefcaseBusiness },
      { id: "positionMap", href: "/position-map", icon: Map },
    ],
  },
  {
    id: "options",
    items: [
      { id: "optionsScreener", href: "/options-screener", icon: ListFilter },
      { id: "optionsRadar", href: "/options-radar", icon: Radar },
      { id: "optionsTools", href: "/options-tools", icon: Wrench },
      { id: "buySide", href: "/options-buyside", icon: BadgeDollarSign },
    ],
  },
  {
    id: "markets",
    items: [
      { id: "aiNews", href: "/ai-news", icon: Newspaper },
      { id: "orderBook", href: "/polymarket", icon: BookOpen },
      { id: "agentStudio", href: "/agent-studio", icon: Zap },
    ],
  },
  {
    id: "system",
    items: [
      { id: "settings", href: "/settings", icon: Settings },
      { id: "docs", href: "/docs/reversal-momentum", icon: FileText, surfaces: ["mobile"] },
      { id: "support", href: "/settings", icon: HelpCircle, surfaces: ["mobile"] },
    ],
  },
];

export function isVisibleOnSurface(item: NavItem, surface: NavSurface): boolean {
  return item.surfaces?.includes(surface) ?? true;
}
