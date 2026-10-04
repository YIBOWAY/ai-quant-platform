import { readFileSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { OptionsToolsWorkbench, ResearchResultStatus, MiniPnlChart } from "./OptionsToolsWorkbench";

describe("OptionsToolsWorkbench header", () => {
  it("describes the watchlist write scope honestly in zh", () => {
    const html = renderToStaticMarkup(<OptionsToolsWorkbench locale="zh" />);

    expect(html).toContain("期权研究工具");
    expect(html).toContain("唯一的写入是研究自选清单");
    expect(html).toContain("不写账户、不触发任何交易");
    expect(html).not.toContain("只读期权研究工具");
  });

  it("describes the watchlist write scope honestly in en", () => {
    const html = renderToStaticMarkup(<OptionsToolsWorkbench locale="en" />);

    expect(html).toContain("The only write here is the research watchlist");
    expect(html).toContain("never touches accounts or places trades");
    expect(html).not.toContain("Read-only option research tools.");
  });
});

describe("OptionsToolsWorkbench error presentation", () => {
  it("shows both hedge legs, excess put coverage and total cost above the raw data", () => {
    const html = renderToStaticMarkup(<ResearchResultStatus locale="zh" payload={{ situation: "normal", structures: [{
      structure: "collar", put_contracts: 3, call_contracts: 2, excess_put_coverage_shares: 50,
      call_covered_shares: 200, uncapped_shares: 50, estimated_debit_per_put: 110,
      estimated_credit_per_call: 60, estimated_net_debit: 210,
    }] }}/>);
    expect(html).toContain("买入 3 张看跌期权，卖出 2 张看涨期权");
    expect(html).toContain("看跌保护比原持股多 50 股");
    expect(html).toContain("只对应 200 股持仓");
    expect(html).toContain("整套预计支出");
    expect(html).toContain("210.00");
    expect(html).toContain("合计已乘各腿张数");
  });
  it("explains missing inputs before showing raw calculator output", () => {
    const html = renderToStaticMarkup(<ResearchResultStatus locale="zh" payload={{
      available_inputs: 1, total_inputs: 6, status: "partial", partial_score: 0, missing_inputs: ["vix", "rsi_14"],
    }} />);
    expect(html).toContain("1 / 6");
    expect(html).toContain("不代表完整评分");
    expect(html).toContain("VIX 恐慌指数");
    expect(html).not.toContain("calm");
  });

  it("states no saved profile and no paired earnings history as unassessed", () => {
    expect(renderToStaticMarkup(<ResearchResultStatus locale="zh" payload={{ status: "no_saved_profile" }} />))
      .toContain("未保存");
    expect(renderToStaticMarkup(<ResearchResultStatus locale="zh" payload={{ reason: "event_aligned_iv_history_missing" }} />))
      .toContain("不能估算财报后的 IV");
  });

  it("provides visible-height chart containers and a labeled chart for browser verification", () => {
    const html = renderToStaticMarkup(<MiniPnlChart label="到期盈亏" rows={[{price: 90, pnl: -100}, {price: 110, pnl: 200}]} />);
    expect(html).toContain('aria-label="到期盈亏"');
    expect(html).toContain('class="flex h-full flex-1 items-end"');
  });
  it("routes every panel error through the shared localized options message", () => {
    const source = readFileSync(
      path.join(process.cwd(), "components/forms/OptionsToolsWorkbench.tsx"),
      "utf8",
    );

    expect(source.match(/optionsErrorMessage\(err, locale\)/g)).toHaveLength(8);
    expect(source).not.toContain("function errorMessage(");
  });
});
