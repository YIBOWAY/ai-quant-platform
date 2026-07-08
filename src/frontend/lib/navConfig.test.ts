import { describe, expect, it } from "vitest";

import {
  isVisibleOnSurface,
  navSections,
  type NavItem,
  type NavItemId,
  type NavSection,
  type NavSurface,
} from "./navConfig";

const expectedItemIds: NavItemId[] = [
  "dashboard",
  "hermes",
  "dataExplorer",
  "factorLab",
  "backtester",
  "replications",
  "experiments",
  "paperTrading",
  "positionMap",
  "optionsScreener",
  "optionsRadar",
  "optionsTools",
  "buySide",
  "aiNews",
  "orderBook",
  "agentStudio",
  "settings",
  "docs",
  "support",
];

function itemRoutesFor(sectionId: NavSection["id"]) {
  return navSections
    .find((section) => section.id === sectionId)
    ?.items.map(({ id, href }) => ({ id, href }));
}

function routesForSurface(surface: NavSurface) {
  return navSections
    .flatMap((section) => section.items)
    .filter((item) => isVisibleOnSurface(item, surface))
    .map((item) => item.href);
}

describe("navSections", () => {
  it("keeps the five top-level navigation groups in product order", () => {
    expect(navSections.map((section) => section.id)).toEqual([
      "research",
      "paper",
      "options",
      "markets",
      "system",
    ]);
  });

  it("keeps exact item routes for every navigation group", () => {
    expect(itemRoutesFor("research")).toEqual([
      { id: "dashboard", href: "/" },
      { id: "hermes", href: "/hermes" },
      { id: "dataExplorer", href: "/data-explorer" },
      { id: "factorLab", href: "/factor-lab" },
      { id: "backtester", href: "/backtest" },
      { id: "replications", href: "/strategies" },
      { id: "experiments", href: "/experiments" },
    ]);
    expect(itemRoutesFor("paper")).toEqual([
      { id: "paperTrading", href: "/paper-trading" },
      { id: "positionMap", href: "/position-map" },
    ]);
    expect(itemRoutesFor("options")).toEqual([
      { id: "optionsScreener", href: "/options-screener" },
      { id: "optionsRadar", href: "/options-radar" },
      { id: "optionsTools", href: "/options-tools" },
      { id: "buySide", href: "/options-buyside" },
    ]);
    expect(itemRoutesFor("markets")).toEqual([
      { id: "aiNews", href: "/ai-news" },
      { id: "orderBook", href: "/polymarket" },
      { id: "agentStudio", href: "/agent-studio" },
    ]);
    expect(itemRoutesFor("system")).toEqual([
      { id: "settings", href: "/settings" },
      { id: "docs", href: "/docs/reversal-momentum" },
      { id: "support", href: "/settings" },
    ]);
  });

  it("keeps Factor Lab and Agent Studio until Hermes parity is reached", () => {
    const itemIds = navSections.flatMap((section) => section.items.map((item) => item.id));

    expect(itemIds).toContain("factorLab");
    expect(itemIds).toContain("agentStudio");
  });

  it("keeps the item id set aligned with NavItemId", () => {
    const itemIds = navSections.flatMap((section) => section.items.map((item) => item.id));

    expect(itemIds).toEqual(expectedItemIds);
  });

  it("computes full route lists by navigation surface", () => {
    const sidebarRoutes = routesForSurface("sidebar");
    const mobileRoutes = routesForSurface("mobile");

    expect(sidebarRoutes).not.toContain("/docs/reversal-momentum");
    expect(sidebarRoutes.filter((href) => href === "/settings")).toHaveLength(1);
    expect(mobileRoutes).toContain("/docs/reversal-momentum");
    expect(mobileRoutes.filter((href) => href === "/settings")).toHaveLength(2);
  });

  it("marks docs and support as mobile-only", () => {
    const system = navSections.find((section) => section.id === "system");
    const docs = system?.items.find((item) => item.id === "docs");
    const support = system?.items.find((item) => item.id === "support");

    expect(docs?.surfaces).toEqual(["mobile"]);
    expect(support?.surfaces).toEqual(["mobile"]);
    expect(docs && isVisibleOnSurface(docs, "sidebar")).toBe(false);
    expect(support && isVisibleOnSurface(support, "sidebar")).toBe(false);
    expect(docs && isVisibleOnSurface(docs, "mobile")).toBe(true);
    expect(support && isVisibleOnSurface(support, "mobile")).toBe(true);
  });

  it("provides id, href, and icon for every navigation item", () => {
    for (const item of navSections.flatMap((section) => section.items)) {
      expect(item.id).toEqual(expect.any(String));
      expect(item.href).toMatch(/^\/.*/);
      expect(item.icon).toBeTruthy();
    }
  });
});

describe("isVisibleOnSurface", () => {
  it("defaults to visible on every surface when surfaces is omitted", () => {
    const item: NavItem = {
      id: "dashboard",
      href: "/default",
      icon: navSections[0].items[0].icon,
    };

    expect(isVisibleOnSurface(item, "sidebar")).toBe(true);
    expect(isVisibleOnSurface(item, "mobile")).toBe(true);
  });
});
