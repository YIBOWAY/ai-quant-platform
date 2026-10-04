import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { UnifiedResultDetail } from "@/components/hermes/results/UnifiedResultDetail";
import { normalizeHermesResultDetailResponse } from "./resultsReadModel";

const resourceId = "portfolio-risk:99801128b23c464d63b1ff2b";
const failedRisk = {
  read_status: "unavailable",
  item: {
    kind: "portfolio_risk", resource_id: resourceId,
    display_title: "default portfolio risk", summary: null, status: "unavailable",
    occurred_at: "2026-10-03T00:15:03Z", source: "hqa_artifact_feed",
    authority: "hqa_artifact_manifest", freshness: "fresh", read_status: "unavailable",
    detail_href: `/api/hermes/results/portfolio_risk/${resourceId}`,
    original_href: "/api/hermes/artifacts", run_links: [],
  },
  resource: { id: resourceId, kind: "portfolio_risk", quality: "unavailable", status: "unavailable", data: { reason_codes: ["paper_account_snapshot_http_503"], limitations: ["current_snapshot_unavailable"] } },
  warnings: [{ source: "hqa_artifact_feed", code: "artifact_quality_degraded", kind: "portfolio_risk", resource_id: resourceId }],
};
const expected = { kind: "portfolio_risk" as const, resourceId };

describe("unavailable result with preserved failure evidence", () => {
  it("preserves the historical failure and displays its actual reason", () => {
    const result = normalizeHermesResultDetailResponse(failedRisk, expected);
    expect(result.apiError).toBeUndefined();
    expect(result.read_status).toBe("unavailable");
    expect(result.resource).toEqual(failedRisk.resource);
    const html = renderToStaticMarkup(createElement(UnifiedResultDetail, { envelope: result, locale: "zh", backHref: "/zh/hermes/results" }));
    expect(html).toContain("paper_account_snapshot_http_503");
    expect(html).toContain("已保存的失败记录");
    expect(html).not.toContain("results_response_invalid");
  });

  it.each([
    { item: null },
    { item: { ...failedRisk.item, resource_id: "wrong-identity" } },
    { resource: { payload: "x".repeat(1_048_577) } },
    { read_status: "missing" },
  ])("still rejects inconsistent or unbounded evidence %#", (overrides) => {
    expect(normalizeHermesResultDetailResponse({ ...failedRisk, ...overrides }, expected).apiError).toBe("results_response_invalid");
  });

  it("never renders corrupt payloads", () => {
    const result = normalizeHermesResultDetailResponse({ ...failedRisk, read_status: "corrupt", item: { ...failedRisk.item, read_status: "corrupt" } }, expected);
    const html = renderToStaticMarkup(createElement(UnifiedResultDetail, { envelope: result, locale: "zh", backHref: "/zh/hermes/results" }));
    expect(html).not.toContain("paper_account_snapshot_http_503");
    expect(html).toContain("载荷已安全隐藏");
  });
});
