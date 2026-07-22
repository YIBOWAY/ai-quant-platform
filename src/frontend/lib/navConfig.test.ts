import { describe, expect, it } from "vitest";

import {
  buildNavSections,
  isVisibleOnSurface,
  navSections,
  type NavItem,
  type NavItemId,
  type NavSection,
  type NavSurface,
} from "./navConfig";

const expectedEnabledItemIds: NavItemId[] = [
  "hermes",
  "brief",
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

const expectedRolledBackItemIds: NavItemId[] = [
  "dashboard",
  "hermes",
  "brief",
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

function itemRoutesFor(
  sections: NavSection[],
  sectionId: NavSection["id"],
) {
  return sections
    .find((section) => section.id === sectionId)
    ?.items.map(({ id, href }) => ({ id, href }));
}

function routesForSurface(sections: NavSection[], surface: NavSurface) {
  return sections
    .flatMap((section) => section.items)
    .filter((item) => isVisibleOnSurface(item, surface))
    .map((item) => item.href);
}

describe("buildNavSections", () => {
  it("keeps the five top-level navigation groups in product order", () => {
    expect(
      buildNavSections({ shellEnabled: true }).map((section) => section.id),
    ).toEqual(["research", "paper", "options", "markets", "system"]);
    expect(
      buildNavSections({ shellEnabled: false }).map((section) => section.id),
    ).toEqual(["research", "paper", "options", "markets", "system"]);
  });

  it("switches only the home entry while retaining Hermes and legacy research", () => {
    const enabled = buildNavSections({ shellEnabled: true }).flatMap(
      (section) => section.items,
    );
    expect(enabled[0]).toMatchObject({ id: "hermes", href: "/hermes" });
    expect(enabled.some((item) => item.id === "dashboard")).toBe(false);

    const rolledBack = buildNavSections({ shellEnabled: false }).flatMap(
      (section) => section.items,
    );
    expect(rolledBack[0]).toMatchObject({ id: "dashboard", href: "/" });
    expect(rolledBack).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: "hermes", href: "/hermes" }),
      ]),
    );
    for (const items of [enabled, rolledBack]) {
      expect(items.map((item) => item.id)).toEqual(
        expect.arrayContaining([
          "factorLab",
          "backtester",
          "experiments",
          "agentStudio",
        ]),
      );
    }
  });

  it("keeps exact item routes for every navigation group in both modes", () => {
    const enabled = buildNavSections({ shellEnabled: true });
    expect(itemRoutesFor(enabled, "research")).toEqual([
      { id: "hermes", href: "/hermes" },
      { id: "brief", href: "/brief" },
      { id: "dataExplorer", href: "/data-explorer" },
      { id: "factorLab", href: "/factor-lab" },
      { id: "backtester", href: "/backtest" },
      { id: "replications", href: "/strategies" },
      { id: "experiments", href: "/experiments" },
    ]);

    const rolledBack = buildNavSections({ shellEnabled: false });
    expect(itemRoutesFor(rolledBack, "research")).toEqual([
      { id: "dashboard", href: "/" },
      { id: "hermes", href: "/hermes" },
      { id: "brief", href: "/brief" },
      { id: "dataExplorer", href: "/data-explorer" },
      { id: "factorLab", href: "/factor-lab" },
      { id: "backtester", href: "/backtest" },
      { id: "replications", href: "/strategies" },
      { id: "experiments", href: "/experiments" },
    ]);

    for (const sections of [enabled, rolledBack]) {
      expect(itemRoutesFor(sections, "paper")).toEqual([
        { id: "paperTrading", href: "/paper-trading" },
        { id: "positionMap", href: "/position-map" },
      ]);
      expect(itemRoutesFor(sections, "options")).toEqual([
        { id: "optionsScreener", href: "/options-screener" },
        { id: "optionsRadar", href: "/options-radar" },
        { id: "optionsTools", href: "/options-tools" },
        { id: "buySide", href: "/options-buyside" },
      ]);
      expect(itemRoutesFor(sections, "markets")).toEqual([
        { id: "aiNews", href: "/ai-news" },
        { id: "orderBook", href: "/polymarket" },
        { id: "agentStudio", href: "/agent-studio" },
      ]);
      expect(itemRoutesFor(sections, "system")).toEqual([
        { id: "settings", href: "/settings" },
        { id: "docs", href: "/docs/reversal-momentum" },
        { id: "support", href: "/settings" },
      ]);
    }
  });

  it("keeps Factor Lab and Agent Studio until Hermes parity is reached", () => {
    for (const shellEnabled of [true, false]) {
      const itemIds = buildNavSections({ shellEnabled }).flatMap((section) =>
        section.items.map((item) => item.id),
      );
      expect(itemIds).toContain("factorLab");
      expect(itemIds).toContain("agentStudio");
    }
  });

  it("removes only Agent Studio when its independent cutover is enabled", () => {
    for (const shellEnabled of [true, false]) {
      const itemIds = buildNavSections({
        shellEnabled,
        agentStudioRedirect: true,
      }).flatMap((section) => section.items.map((item) => item.id));
      expect(itemIds).not.toContain("agentStudio");
      expect(itemIds).toEqual(
        expect.arrayContaining(["factorLab", "backtester", "experiments"]),
      );
    }
  });

  it("keeps the item id set aligned with each shell mode", () => {
    expect(
      buildNavSections({ shellEnabled: true }).flatMap((section) =>
        section.items.map((item) => item.id),
      ),
    ).toEqual(expectedEnabledItemIds);
    expect(
      buildNavSections({ shellEnabled: false }).flatMap((section) =>
        section.items.map((item) => item.id),
      ),
    ).toEqual(expectedRolledBackItemIds);
  });

  it("computes full route lists by navigation surface", () => {
    const sections = buildNavSections({ shellEnabled: true });
    const sidebarRoutes = routesForSurface(sections, "sidebar");
    const mobileRoutes = routesForSurface(sections, "mobile");

    expect(sidebarRoutes).not.toContain("/docs/reversal-momentum");
    expect(sidebarRoutes.filter((href) => href === "/settings")).toHaveLength(1);
    expect(mobileRoutes).toContain("/docs/reversal-momentum");
    expect(mobileRoutes.filter((href) => href === "/settings")).toHaveLength(2);
  });

  it("marks docs and support as mobile-only", () => {
    const system = buildNavSections({ shellEnabled: true }).find(
      (section) => section.id === "system",
    );
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
    for (const shellEnabled of [true, false]) {
      for (const item of buildNavSections({ shellEnabled }).flatMap(
        (section) => section.items,
      )) {
        expect(item.id).toEqual(expect.any(String));
        expect(item.href).toMatch(/^\/.*/);
        expect(item.icon).toBeTruthy();
      }
    }
  });
});

describe("navSections default export", () => {
  it("matches shell-enabled product navigation", () => {
    expect(navSections).toEqual(buildNavSections({ shellEnabled: true }));
  });
});

describe("isVisibleOnSurface", () => {
  it("defaults to visible on every surface when surfaces is omitted", () => {
    const item: NavItem = {
      id: "dashboard",
      href: "/default",
      icon: buildNavSections({ shellEnabled: false })[0].items[0].icon,
    };

    expect(isVisibleOnSurface(item, "sidebar")).toBe(true);
    expect(isVisibleOnSurface(item, "mobile")).toBe(true);
  });
});
