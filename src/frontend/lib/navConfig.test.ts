import { describe, expect, it } from "vitest";

import { isVisibleOnSurface, navSections, type NavItem } from "./navConfig";

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

  it("starts research with dashboard and Hermes", () => {
    const research = navSections.find((section) => section.id === "research");

    expect(research?.items.slice(0, 2).map(({ id, href }) => ({ id, href }))).toEqual([
      { id: "dashboard", href: "/" },
      { id: "hermes", href: "/hermes" },
    ]);
  });

  it("keeps Factor Lab and Agent Studio until Hermes parity is reached", () => {
    const itemIds = navSections.flatMap((section) => section.items.map((item) => item.id));

    expect(itemIds).toContain("factorLab");
    expect(itemIds).toContain("agentStudio");
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
      id: "default",
      href: "/default",
      icon: navSections[0].items[0].icon,
    };

    expect(isVisibleOnSurface(item, "sidebar")).toBe(true);
    expect(isVisibleOnSurface(item, "mobile")).toBe(true);
  });
});
