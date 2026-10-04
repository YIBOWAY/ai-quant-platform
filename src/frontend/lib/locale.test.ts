import { describe, expect, it } from "vitest";
import { localizePath, splitLocalePath } from "./locale";

describe("localized research links", () => {
  it("preserves both a query and the exact strategy anchor", () => {
    const path = "/strategy-library?strategy=strategy-abc#strategy-abc";
    expect(localizePath(path, "zh")).toBe(`/zh${path}`);
    expect(splitLocalePath(`/zh${path}`)).toEqual({ locale: "zh", pathname: path });
  });
  it("keeps query-like fragment text and does not rewrite external links", () => {
    expect(localizePath("/en/library#id?note=yes", "zh")).toBe("/zh/library#id?note=yes");
    expect(localizePath("https://example.com/a?b#c", "zh")).toBe("https://example.com/a?b#c");
  });
});
