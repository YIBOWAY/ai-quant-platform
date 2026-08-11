import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { D34ResearchWorkbench } from "@/components/hermes/d34/D34ResearchWorkbench";

describe("D34ResearchWorkbench", () => {
  it("renders the paper-only research boundary in Chinese", () => {
    const html = renderToStaticMarkup(<D34ResearchWorkbench locale="zh" />);

    expect(html).toContain('id="d34-workbench-title"');
    expect(html).toContain("Mandate 驱动的双引擎研究");
    expect(html).toContain("只进入低额度 paper canary");
    expect(html).toContain("live 始终关闭");
    expect(html).not.toContain("升级 live");
    expect(html).not.toContain("Promote to live");
  });

  it("renders the English paper-only research boundary", () => {
    const html = renderToStaticMarkup(<D34ResearchWorkbench locale="en" />);

    expect(html).toContain("Mandate-driven dual-engine research");
    expect(html).toContain("low-allocation paper canaries only");
    expect(html).toContain("live stays off");
  });
});
