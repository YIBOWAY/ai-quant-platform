import { readFileSync } from "node:fs";
import path from "node:path";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { DataSourceBadge, isSampleSource } from "@/components/DataSourceBadge";

describe("options provenance badge (V1.6b)", () => {
  it("renders a loud 'sample / not real' badge for the sample provider", () => {
    const html = renderToStaticMarkup(
      createElement(DataSourceBadge, { source: "sample" }),
    );
    expect(isSampleSource("sample")).toBe(true);
    expect(html).toContain("sample / not real");
  });

  it("renders a success-state badge for the real futu provider", () => {
    const html = renderToStaticMarkup(
      createElement(DataSourceBadge, { source: "futu" }),
    );
    expect(isSampleSource("futu")).toBe(false);
    expect(html).toContain("futu");
    expect(html).not.toContain("not real");
  });

  it("OptionsScreenerResults wires DataSourceBadge to result.provider", () => {
    const src = readFileSync(
      path.join(process.cwd(), "components/forms/OptionsScreenerResults.tsx"),
      "utf8",
    );
    expect(src).toContain('from "@/components/DataSourceBadge"');
    expect(src).toMatch(/<DataSourceBadge\s+source=\{result\.provider\}\s*\/>/);
  });

  it("OptionsRadarView wires snapshot provenance to the scan response", () => {
    const src = readFileSync(
      path.join(process.cwd(), "components/forms/OptionsRadarView.tsx"),
      "utf8",
    );
    expect(src).toContain('from "@/components/DataSourceBadge"');
    expect(src).toMatch(/<DataSourceBadge\s+source=\{scanQuery\.data\.provider\}\s*\/>/);
  });

  it("labels the existing radar route as Options Recommendations in desktop and mobile navigation", () => {
    for (const sourcePath of ["components/Sidebar.tsx", "components/TopBar.tsx"]) {
      const src = readFileSync(path.join(process.cwd(), sourcePath), "utf8");
      expect(src).toContain('optionsRadar: "Options Recommendations"');
      expect(src).toContain('optionsRadar: "期权推荐"');
      expect(src).not.toContain('optionsRadar: "Options Radar"');
      expect(src).not.toContain('optionsRadar: "期权雷达"');
    }
  });
});
