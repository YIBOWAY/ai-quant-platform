import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { components } from "@/lib/api.generated";
import { CollectionWorkbench } from "./CollectionWorkbench";

type Item = components["schemas"]["CollectionItem"];
const base: Item = {
  key: "research:test",
  kind: "research",
  id: "test",
  name: "测试研究",
  name_en: "Test research",
  description: "注册说明",
  implementation_status: "implemented",
  source_digest: "source-v1",
  intro: {
    status: "ready",
    summary: "依据源码生成的介绍",
    source_digest: "source-v1",
    model: "grok-4.6",
    reasoning_effort: "xhigh",
  },
};
const render = (item: Item) =>
  renderToStaticMarkup(
    <CollectionWorkbench
      locale="zh"
      initialKey={item.key}
      data={{
        generated_at: "2026-09-06",
        items: [item],
        excluded_sample_runs: 1,
      }}
    />,
  );

describe("CollectionWorkbench evidence presentation", () => {
  it("names the strategy research entry and explains what it contains", () => {
    const html = render(base);
    expect(html).toContain("策略研究与回测");
    expect(html).toContain("横向比较固定方案，查看每期选股、成交和收益依据");
    expect(html).toContain('href="/zh/research-evaluation"');
    expect(html).not.toContain("比较与验证");
  });
  it("keeps the engines' own results distinct and explains missing original metrics", () => {
    const html = render({
      ...base,
      evidence: [
        {
          kind: "dual_engine",
          engine: "Qlib",
          status: "verified",
          note: "Qlib原记录",
          metrics: { sharpe: 1.1234, max_drawdown: 0.2 },
        },
        {
          kind: "dual_engine",
          engine: "Platform",
          status: "verified",
          note: "Platform原记录",
          metrics: { sharpe: 1.2345, total_return: 0.4, max_drawdown: -0.21 },
        },
      ],
    });
    for (const value of [
      "1.1234",
      "1.2345",
      "40.00%",
      "20.00%",
      "21.00%",
      "没有借用另一引擎的数值",
      "grok-4.6",
      "xhigh",
      "排除 1 条示例回测",
    ])
      expect(html).toContain(value);
  });

  it("uses a factor's IC rather than presenting a portfolio Sharpe", () => {
    const html = render({
      ...base,
      key: "factor:test",
      kind: "factor",
      evidence: [
        {
          kind: "factor_lab",
          engine: "Factor Lab",
          status: "historical",
          note: "未绑定当前源码",
          metrics: {
            ic_mean: 0.0357,
            sample_count: 200,
            coverage: 0.9,
            sharpe: 19.01,
          },
        },
      ],
    });
    expect(html).toContain("0.0357");
    expect(html).toContain("200");
    expect(html).not.toContain("19.01");
    expect(html).toContain("不等于策略收益或夏普率");
  });

  it("labels the wide evidence table and adds a narrow-screen scroll cue", async () => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const source = readFileSync(
      join(process.cwd(), "components/collection/CollectionWorkbench.tsx"),
      "utf8",
    );
    expect(source).toMatch(/aria-label=\{zh \? "研究与回测证据"[\s\S]*?role="region"[\s\S]*?tabIndex=\{0\}/);
    expect(source).toContain("<TableScrollHint label={tableScrollHintText[locale]} />");

    const html = render({
      ...base,
      evidence: [
        {
          kind: "dual_engine",
          engine: "Qlib",
          status: "verified",
          note: "Qlib原记录",
          metrics: { sharpe: 1.1234, max_drawdown: 0.2 },
        },
      ],
    });
    expect(html).toContain("表格可左右滑动查看全部列");
  });

  it("does not show a stale code introduction as the current explanation", () => {
    const html = render({
      ...base,
      intro: { ...base.intro, status: "source_changed", summary: "过期说明" },
    });
    expect(html).toContain("注册说明");
    expect(html).not.toContain("过期说明");
    expect(html).not.toContain("结合实现代码生成");
  });
});
