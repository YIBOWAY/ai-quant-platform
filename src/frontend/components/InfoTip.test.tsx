import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { GLOSSARY, InfoTip, infoTipPosition } from "./InfoTip";

describe("InfoTip", () => {
  it("uses the browser top layer even inside a clipped table heading", () => {
    const html = renderToStaticMarkup(<div style={{ overflow: "hidden", height: 24 }}><table><thead><tr><th><InfoTip term="delta" locale="zh" /></th></tr></thead></table></div>);
    expect(html).toContain('popover="auto"');
    expect(html).toContain('role="tooltip"');
    expect(html).toContain('aria-label="查看说明"');
    expect(html).toContain(GLOSSARY.delta.zh);
    expect(html).not.toContain("absolute bottom-full");
  });

  it("positions above when possible, otherwise below, and clamps both viewport edges", () => {
    expect(infoTipPosition({ left: 250, right: 270, top: 200, bottom: 220 }, 288, 100, 800, 600)).toEqual({ left: 116, top: 94 });
    expect(infoTipPosition({ left: 1, right: 19, top: 2, bottom: 20 }, 288, 100, 390, 600)).toEqual({ left: 8, top: 26 });
    expect(infoTipPosition({ left: 375, right: 390, top: 590, bottom: 608 }, 288, 100, 390, 600)).toEqual({ left: 94, top: 484 });
  });
});
