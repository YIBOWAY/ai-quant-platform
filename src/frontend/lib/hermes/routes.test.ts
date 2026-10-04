import { describe, expect, it } from "vitest";
import { hermesHomeHref, hermesRouteHref, hermesRoutes } from "./routes";

describe("hermesRoutes", () => {
  it("exports the read-only session route without opening conversation write", () => {
    expect(hermesRoutes).toEqual({
      today: "/hermes",
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
    expect(hermesHomeHref("en", { focus: "results" })).toBe(
      "/en/hermes?focus=results",
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
    expect(hermesRouteHref("results", "zh", { b: "2", a: "1" })).toBe(
      "/zh/hermes/results?a=1&b=2",
    );
  });
});

describe("V8-M3 deep-link catalog (G3 observe-only)", () => {
  const OBSERVE_QUERY_KEYS = [
    "focus",
    "task_id",
    "result_id",
    "hermes_session_id",
    "command_id",
  ] as const;

  it("builds observe deep-links for results without write verbs", () => {
    expect(
      hermesRouteHref("results", "en", { result_id: "res-1" }),
    ).toBe("/en/hermes/results?result_id=res-1");
    expect(
      hermesHomeHref("en", { hermes_session_id: "run_deadbeef", command_id: "c1" }),
    ).toBe("/en/hermes?command_id=c1&hermes_session_id=run_deadbeef");
  });

  it("catalog keys stay observe-only (no write/mutate/conversation verbs)", () => {
    const blob = [
      ...Object.values(hermesRoutes),
      ...OBSERVE_QUERY_KEYS,
    ].join(" ");
    expect(blob).not.toMatch(/write|mutate|conversation\.turn|submit-turn/i);
  });

  it("deep-link hrefs do not encode mutation paths", () => {
    const href = hermesRouteHref("results", "en", {
      result_id: "result-1",
      mutation_enabled: "true",
    });
    expect(href.startsWith("/en/hermes/results")).toBe(true);
    expect(href).not.toContain("/act");
    expect(href).not.toContain("submit-turn");
  });
});
