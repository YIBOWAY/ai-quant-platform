import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { BriefArchiveControl } from "@/components/brief/BriefArchiveControl";
import type { BriefArchivePayload, BriefSourceWatermark } from "./briefArchive";

const payload = {
  schema_version: "brief_snapshot_v1",
  title: "每日晨报",
  issue_date: "2026-07-14",
  locale: "zh",
  generated_at: "2026-07-14T08:30:00Z",
  lede: "事实摘要",
  account: {
    account_id: "default",
    base_currency: "USD",
    equity: 1,
    cash: 1,
    pnl_abs: 0,
    pnl_pct: 0,
    invested_pct: 0,
    price_source: { kind: "file", as_of: null },
    positions: [],
  },
  paper_equity: [],
  markets: [],
  market_note: "无行情",
  ai_news: [],
  hermes_log: [],
  warnings: [],
} satisfies BriefArchivePayload;

const watermark = {
  captured_at: "2026-07-14T08:30:00Z",
  sources: [],
} satisfies BriefSourceWatermark;

describe("BriefArchiveControl", () => {
  it("disables persistence when a critical factual source is unavailable", () => {
    const html = renderToStaticMarkup(
      createElement(BriefArchiveControl, {
        initialPublicId: null,
        locale: "zh",
        payload,
        sourceWatermark: watermark,
        disabledReason: "模拟账户不可用，不能归档",
      }),
    );

    expect(html).toContain("disabled");
    expect(html).toContain("模拟账户不可用，不能归档");
  });
});
