import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { D34ResearchWorkbench } from "@/components/hermes/d34/D34ResearchWorkbench";

describe("D34ResearchWorkbench", () => {
  it("renders the paper-only research boundary in Chinese", () => {
    const html = renderToStaticMarkup(<D34ResearchWorkbench locale="zh" />);

    expect(html).toContain('id="d34-workbench-title"');
    expect(html).toContain("按需双引擎纸面研究");
    expect(html).toContain("纸面试运行仓");
    expect(html).toContain("你提出研究需求后才会入队");
    expect(html).toContain("live 始终关闭");
    expect(html).not.toContain("升级 live");
    expect(html).not.toContain("Promote to live");
  });

  it("renders the English paper-only research boundary", () => {
    const html = renderToStaticMarkup(<D34ResearchWorkbench locale="en" />);

    expect(html).toContain("On-demand dual-engine paper research");
    expect(html).toContain("on-demand paper research");
    expect(html).not.toContain("autonomous paper research");
    expect(html).toContain("low-allocation paper canaries only");
    expect(html).toContain("live stays off");
  });
});
