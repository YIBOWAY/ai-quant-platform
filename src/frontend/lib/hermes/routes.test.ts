import { describe, expect, it } from "vitest";
import { hermesHomeHref, hermesRouteHref, hermesRoutes } from "./routes";

describe("hermesRoutes", () => {
  it("exports the four internal workbench paths without conversation", () => {
    expect(hermesRoutes).toEqual({
      today: "/hermes",
      tasks: "/hermes/tasks",
      approvals: "/hermes/approvals",
      results: "/hermes/results",
    });
    expect(Object.values(hermesRoutes).join(" ")).not.toContain("conversation");
  });
});

describe("hermesHomeHref", () => {
  it("localizes with no query string", () => {
    expect(hermesHomeHref("en", {})).toBe("/en/hermes");
    expect(hermesHomeHref("zh", {})).toBe("/zh/hermes");
  });

  it("preserves a single query parameter", () => {
    expect(hermesHomeHref("en", { focus: "approvals" })).toBe(
      "/en/hermes?focus=approvals",
    );
  });

  it("preserves repeated query parameters", () => {
    expect(hermesHomeHref("zh", { tag: ["a", "b"] })).toBe(
      "/zh/hermes?tag=a&tag=b",
    );
  });

  it("orders query keys deterministically", () => {
    expect(hermesHomeHref("en", { z: "1", a: "2", m: "3" })).toBe(
      "/en/hermes?a=2&m=3&z=1",
    );
  });

  it("skips undefined values", () => {
    expect(hermesHomeHref("en", { a: "1", b: undefined })).toBe(
      "/en/hermes?a=1",
    );
  });
});

describe("hermesRouteHref", () => {
  it("localizes nested routes with ordered query keys", () => {
    expect(hermesRouteHref("approvals", "zh", { b: "2", a: "1" })).toBe(
      "/zh/hermes/approvals?a=1&b=2",
    );
  });
});
