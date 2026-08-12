import { readFileSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { BriefRollupDocument } from "./BriefRollupDocument";
import type {
  BriefRollupListItem,
  BriefRollupPayload,
  BriefRollupView,
} from "@/lib/briefRollup";

const rollupPagePath = path.join(process.cwd(), "app/brief/rollup/[publicId]/page.tsx");

const payload: BriefRollupPayload = {
  schema_version: "brief_rollup_v1",
  kind: "weekly",
  period_key: "2026-W33",
  locale: "zh",
  title: "第 33 周 AI 周报",
  date_range: { start: "2026-08-10", end: "2026-08-16" },
  main_storyline: "本周模拟盘围绕半导体与防御板块再平衡，波动放大。",
  stats: {
    daily_count: 5,
    event_count: 17,
    equity_start: 100_000,
    equity_end: 101_234.5,
    period_change_pct: 1.23,
  },
  topics: [
    {
      index: 1,
      title: "半导体领涨",
      synthesis: "SOXX 相对 IGV 偏强，AI 资本开支预期升温。",
      source_items: [
        {
          id: "news-1",
          title: "Chip demand rises",
          url: "https://example.com/chips",
          source: "example",
          published_at: "2026-08-12T01:00:00Z",
          issue_date: "2026-08-12",
        },
        {
          id: "news-2",
          title: "Unsafe protocol link",
          url: "javascript:alert(1)",
          source: "bad-feed",
          published_at: null,
          issue_date: null,
        },
      ],
    },
    {
      index: 2,
      title: "防御轮动",
      synthesis: "公用事业与必需消费相对走强。",
      source_items: [],
    },
  ],
  account_summary: { base_currency: "USD" },
  provenance: {
    model: "xai/grok-4",
    critic_model: "xai/grok-4-critic",
    generated_at: "2026-08-16T09:00:00Z",
    source_issue_public_ids: ["brf_20260810_aaa", "brf_20260811_bbb"],
    facts_digest: "sha256:deadbeef",
  },
  warnings: [],
};

const rollup: BriefRollupView = {
  publicId: "brw_20260810_x1y2z3",
  kind: "weekly",
  periodKey: "2026-W33",
  periodStart: "2026-08-10",
  periodEnd: "2026-08-16",
  locale: "zh",
  status: "published",
  title: "第 33 周 AI 周报",
  version: 1,
  warnings: [],
  payload,
};

const previousItem: BriefRollupListItem = {
  public_id: "brw_20260803_a1b2c3",
  kind: "weekly",
  period_key: "2026-W32",
  period_start: "2026-08-03",
  period_end: "2026-08-09",
  locale: "zh",
  status: "published",
  title: "第 32 周 AI 周报",
  snippet: "",
};

const nextItem: BriefRollupListItem = {
  public_id: "brw_20260817_m7n8o9",
  kind: "weekly",
  period_key: "2026-W34",
  period_start: "2026-08-17",
  period_end: "2026-08-23",
  locale: "zh",
  status: "published",
  title: "第 34 周 AI 周报",
  snippet: "",
};

function render(props: Partial<Parameters<typeof BriefRollupDocument>[0]>) {
  return renderToStaticMarkup(
    <BriefRollupDocument
      locale="zh"
      next={null}
      previous={null}
      rollup={rollup}
      {...props}
    />,
  );
}

describe("BriefRollupDocument", () => {
  it("renders the masthead with period range, title, and fact line", () => {
    const html = render({});
    expect(html).toContain("VOL.2026-W33 · 2026-08-10 ~ 2026-08-16 · AI 综合");
    expect(html).toContain("第 33 周 AI 周报");
    expect(html).toContain("基于 5 期日报快照 · 模型 xai/grok-4 · 模拟盘 · 非投资建议");
  });

  it("renders the main storyline as the centered lede", () => {
    const html = render({});
    expect(html).toContain("本期主线");
    expect(html).toContain("本周模拟盘围绕半导体与防御板块再平衡，波动放大。");
  });

  it("renders the stats strip with signed period change and equity range", () => {
    const html = render({});
    expect(html).toContain("日报期数");
    expect(html).toContain("独立事件数");
    expect(html).toContain("账户期间权益变化");
    expect(html).toContain(">5</p>");
    expect(html).toContain(">17</p>");
    expect(html).toContain("▲ +1.23%");
    expect(html).toContain("$100,000.00 → $101,234.50");
    expect(html).toContain("text-editorial-up");
  });

  it("marks a negative period change with a down arrow and tone", () => {
    const down: BriefRollupView = {
      ...rollup,
      payload: {
        ...payload,
        stats: { ...payload.stats, period_change_pct: -0.87 },
      },
    };
    const html = render({ rollup: down });
    expect(html).toContain("▼ -0.87%");
    expect(html).toContain("text-editorial-down");
  });

  it("renders numbered topics with synthesis and checked external source links", () => {
    const html = render({});
    expect(html).toContain("本期看点");
    expect(html).toContain(">01</span>");
    expect(html).toContain(">02</span>");
    expect(html).toContain("半导体领涨");
    expect(html).toContain("SOXX 相对 IGV 偏强，AI 资本开支预期升温。");
    expect(html).toContain('href="https://example.com/chips"');
    expect(html).toContain('rel="noreferrer noopener"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain("example · 2026-08-12T01:00:00Z · 2026-08-12");
    // Unsafe protocols are never turned into links.
    expect(html).toContain("Unsafe protocol link");
    expect(html).not.toContain('href="javascript:');
    expect(html).toContain("bad-feed · -- · --");
  });

  it("links previous and next rollups by period navigation", () => {
    const html = render({ next: nextItem, previous: previousItem });
    expect(html).toContain("← 上一期 · 2026-W32");
    expect(html).toContain('href="/zh/brief/rollup/brw_20260803_a1b2c3"');
    expect(html).toContain("下一期 → · 2026-W34");
    expect(html).toContain('href="/zh/brief/rollup/brw_20260817_m7n8o9"');
  });

  it("renders the provenance block with source daily issue links", () => {
    const html = render({});
    expect(html).toContain("生成来源");
    expect(html).toContain("xai/grok-4");
    expect(html).toContain("xai/grok-4-critic");
    expect(html).toContain("2026-08-16T09:00:00Z");
    expect(html).toContain("sha256:deadbeef");
    expect(html).toContain("来源日报");
    expect(html).toContain('href="/zh/brief/brf_20260810_aaa"');
    expect(html).toContain('href="/zh/brief/brf_20260811_bbb"');
  });

  it("renders the read-only safety footer", () => {
    const html = render({});
    expect(html).toContain("HERMES MORNING BRIEF · 只读历史快照 · 模拟盘 · 非投资建议");
  });

  it("renders the English copy", () => {
    const html = render({ locale: "en" });
    expect(html).toContain("AI SYNTHESIS");
    expect(html).toContain("Based on 5 daily snapshots · model xai/grok-4");
    expect(html).toContain("THE MAIN STORYLINE");
    expect(html).toContain("HIGHLIGHTS");
    expect(html).toContain("PROVENANCE");
    expect(html).toContain('href="/en/brief/brf_20260810_aaa"');
    expect(html).toContain(
      "HERMES MORNING BRIEF · READ-ONLY HISTORICAL SNAPSHOT · PAPER ONLY · NOT INVESTMENT ADVICE",
    );
  });

  it("shows an alert instead of a fabricated document on apiError", () => {
    const unavailable: BriefRollupView = {
      publicId: "brw_missing",
      kind: "weekly",
      periodKey: "",
      periodStart: "",
      periodEnd: "",
      locale: "",
      status: "unavailable",
      title: "brw_missing",
      version: 0,
      warnings: ["Brief rollup is unavailable."],
      payload: null,
      apiError: "[brief_rollup_not_found] Rollup was not found.",
    };
    const html = render({ rollup: unavailable });
    expect(html).toContain("周报/月报读取失败");
    expect(html).toContain("[brief_rollup_not_found]");
    expect(html).toContain("快照警告");
    expect(html).toContain("brw_missing");
    expect(html).not.toContain("本期看点");
  });

  it("refuses to display an invalid payload without substituting live data", () => {
    const invalid: BriefRollupView = { ...rollup, payload: null, apiError: undefined };
    const html = render({ rollup: invalid });
    expect(html).toContain("快照不可展示");
    expect(html).toContain("该记录没有保存有效的周报/月报事实内容");
    expect(html).not.toContain("本期看点");
  });
});

describe("/brief/rollup/[publicId] page contract", () => {
  it("is a read-only server page bound to the rollup getters and document", () => {
    const source = readFileSync(rollupPagePath, "utf8");

    expect(source).toContain("type Props = { params: Promise<{ publicId: string }> }");
    expect(source).toContain("getBriefRollup(publicId)");
    expect(source).toContain("normalizeBriefRollupEnvelope");
    expect(source).toContain("listBriefRollups(rollup.kind, locale");
    expect(source).toContain("BriefArchiveSidebar");
    expect(source).toContain("activePublicId={rollup.publicId || publicId}");
    expect(source).toContain("BriefRollupDocument");
    expect(source).toContain("bg-paper-ink");
    expect(source).toContain("text-ink");

    expect(source).not.toContain("apiPost");
    expect(source).not.toContain("POST");
    expect(source).not.toContain("fetch(");
  });
});
