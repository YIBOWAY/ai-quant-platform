import { renderToStaticMarkup } from "react-dom/server";
import { describe, it, expect } from "vitest";
import { DataPreviewTable } from "./DataPreviewTable";

describe("diagnostic metric units", () => {
  it("shows ratios as percentages, counts as integers, and missing values as unknown", () => {
    const rows = [{ max_drawdown: -0.0997, win_rate: 0.5652, coverage: 0.9177, trade_count: 34, sharpe: 0.8 },
      { max_drawdown: null, win_rate: 0, coverage: Number.NaN, trade_count: 0, sharpe: null }];
    const html = renderToStaticMarkup(<DataPreviewTable title="Timing" description="" emptyTitle="" emptyDescription="" rows={rows}
      columnFormats={{ max_drawdown: "percent", win_rate: "percent", coverage: "percent", trade_count: "integer" }}/>);
    for (const text of ["-9.97%", "56.52%", "91.77%", ">34<", "0.00%", "0.8000", "--"]) expect(html).toContain(text);
    expect(html).not.toContain("34.0000");
    expect(rows[0].coverage).toBe(0.9177);
  });
});
