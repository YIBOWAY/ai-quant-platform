import { describe, expect, it } from "vitest";

import type { RecentRun } from "./api";
import { dashboardRunHref, dashboardRunIconKind, dashboardRunKindLabel, dashboardRunSummary } from "./dashboardRuns";
import { isSampleSource } from "./runSource";

const replicationRun: RecentRun = {
  kind: "replication",
  run_id: "replication-20260624T010203Z-testjob",
  source: "sample",
  created_at: "2026-06-24T01:02:03Z",
  summary: {
    metrics: {
      total_return: 0.125,
      sharpe: 1.42,
      observation_months: 18,
    },
  },
};

describe("dashboard recent run helpers", () => {
  it("routes replication runs to strategy detail pages", () => {
    expect(dashboardRunHref(replicationRun)).toBe(
      "/strategies/replication-20260624T010203Z-testjob",
    );
  });

  it("labels and summarizes replication runs without using paper metrics", () => {
    expect(dashboardRunKindLabel(replicationRun, "en")).toBe("Replication");
    expect(dashboardRunKindLabel(replicationRun, "zh")).toBe("复现运行");
    expect(dashboardRunIconKind(replicationRun)).toBe("replication");
    expect(dashboardRunSummary(replicationRun)).toBe(
      "Sharpe 1.42 | Return 12.50% | Months 18",
    );
  });

  it("detects sample provenance for brief log labelling", () => {
    expect(isSampleSource(replicationRun.source)).toBe(true);
    expect(isSampleSource("futu")).toBe(false);
    expect(isSampleSource(undefined)).toBe(false);
    expect(isSampleSource(null)).toBe(false);
    expect(isSampleSource("SAMPLE_BACKTEST")).toBe(true);
  });
});
