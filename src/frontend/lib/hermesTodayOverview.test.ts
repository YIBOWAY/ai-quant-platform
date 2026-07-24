import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { HermesCapabilityNotice } from "@/components/hermes/shell/HermesCapabilityNotice";
import { TodayAttention } from "@/components/hermes/today/TodayAttention";
import { TodayRunning } from "@/components/hermes/today/TodayRunning";
import { TodayStatusLine } from "@/components/hermes/today/TodayStatusLine";
import { isInFlightCommandState } from "@/lib/hermes/commandActivity";
import { buildHermesTodayOverviewModel } from "@/lib/hermes/viewModel";
import {
  candidateFixture,
  gatewayFixture,
  healthyArtifacts,
  noArtifacts,
} from "@/lib/hermes/viewModelFixtures";

const now = new Date("2026-07-24T01:00:00Z");

describe("UI-1 Direction A client lanes", () => {
  it("isInFlightCommandState follows the contract terminal set (delivered stays in-flight)", () => {
    expect(isInFlightCommandState("queued")).toBe(true);
    expect(isInFlightCommandState("leased")).toBe(true);
    expect(isInFlightCommandState("delivered")).toBe(true);
    expect(isInFlightCommandState("succeeded")).toBe(false);
    expect(isInFlightCommandState("cancelled")).toBe(false);
    expect(isInFlightCommandState("failed")).toBe(false);
    expect(isInFlightCommandState("rejected")).toBe(false);
    expect(isInFlightCommandState("timed_out")).toBe(false);
    expect(isInFlightCommandState("outcome_unknown")).toBe(false);
    expect(isInFlightCommandState("")).toBe(false);
    expect(isInFlightCommandState(null)).toBe(false);
  });

  it("renders no running lane without a spine (chat off honest absence)", () => {
    const html = renderToStaticMarkup(createElement(TodayRunning, { locale: "zh" }));
    expect(html).toBe("");
  });

  it("renders no action lane when nothing needs attention", () => {
    const html = renderToStaticMarkup(
      createElement(TodayAttention, { items: [], locale: "zh" }),
    );
    expect(html).toBe("");
  });

  it("renders candidate and automation actions without mutation buttons", () => {
    const model = buildHermesTodayOverviewModel({
      artifacts: healthyArtifacts,
      candidates: { candidates: [candidateFixture()] },
      gateway: gatewayFixture(),
      now,
    });
    const html = renderToStaticMarkup(
      createElement(TodayAttention, { items: model.attention, locale: "zh" }),
    );

    expect(html).toContain("待我处理");
    expect(html).toContain('data-hermes-attention-count');
    expect(html).toContain("研究审批项");
    expect(html).toContain("去评审");
    // Mutation stays off in tests → no V7a decide controls.
    expect(html).not.toContain("data-hermes-approval-allow-once");
    expect(html).not.toContain("允许一次");
  });

  it("aggregates offline posture into one status line, never an error wall", () => {
    const model = buildHermesTodayOverviewModel({
      artifacts: noArtifacts("unavailable"),
      candidates: { candidates: [] },
      gateway: gatewayFixture({
        read_status: "unavailable",
        connected: false,
        blockers: ["api_unavailable"],
        upstream_blockers: [],
        platform_delivery_blockers: [],
      }),
      now,
    });
    expect(model.state).toBe("offline");
    const html = renderToStaticMarkup(
      createElement(TodayStatusLine, { model, locale: "zh" }),
    );

    expect(html).toContain("Hermes 离线");
    expect(html).toContain("不可用");
    expect(html).toContain('data-hermes-status-line');
    expect(html).toContain("系统状态");
  });

  it("folds the capability notice into one small line with delivery semantics", () => {
    const html = renderToStaticMarkup(
      createElement(HermesCapabilityNotice, {
        deliveryState: "blocked_in_this_slice",
        locale: "zh",
      }),
    );

    expect(html).toContain('data-testid="hermes-capability-notice"');
    expect(html).toContain('data-delivery-state="blocked_in_this_slice"');
    expect(html).toContain("本交付未连接 Hermes 写入能力");
    // Compact line: no bordered card surface.
    expect(html).not.toContain("rounded-lg border");
  });
});
