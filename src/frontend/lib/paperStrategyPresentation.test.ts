import { describe, expect, it } from "vitest";

import type { PaperStrategySleeveResponse } from "./api";
import {
  partitionStrategySleeves,
  strategyConfigDisplayName,
  strategySleeveModeLabel,
  strategySleeveDisplayName,
  strategyOpsNeedsAttention,
  strategySleeveStatusLabel,
} from "./paperStrategyPresentation";

function sleeve(
  id: string,
  overrides: Partial<PaperStrategySleeveResponse> = {},
): PaperStrategySleeveResponse {
  return {
    sleeve_id: id,
    account_id: "default",
    strategy_config_id: `config-${id}`,
    strategy_config_version: 1,
    mode: "allocated",
    status: "running",
    initial_allocated_cash: 10_000,
    cash: 94.06,
    created_at: "2026-08-20T00:00:00Z",
    updated_at: "2026-08-20T00:00:00Z",
    paused_at: null,
    stopped_at: null,
    stop_reason: null,
    metadata: {},
    ...overrides,
  };
}

describe("paper strategy presentation", () => {
  it("partitions official, pending, manual, and historical sleeves without mixing money", () => {
    const summary = partitionStrategySleeves([
      sleeve("official", {
        metadata: {
          mandate_id: "remote-hang",
          candidate_id: "artifact-official",
        },
      }),
      sleeve("pending-observation", {
        cash: 2_000,
        metadata: {
          mandate_id: "remote-hang",
          candidate_id: "artifact-pending-observation",
          official_observation: false,
        },
      }),
      sleeve("pending-activation", {
        cash: 3_000,
        metadata: {
          mandate_id: "remote-hang",
          candidate_id: "artifact-pending-activation",
          hang_activation_state: "book_binding_pending",
        },
      }),
      sleeve("manual", {
        cash: 4_000,
        metadata: { source: "paper-trading-ui" },
      }),
      sleeve("fossil-a", {
        status: "stopped",
        cash: 10_000,
        metadata: {
          fossil: true,
          mandate_id: "remote-hang",
          candidate_id: "artifact-fossil",
          official_observation: false,
        },
      }),
    ]);

    expect(summary.official.map((item) => item.sleeve_id)).toEqual(["official"]);
    expect(summary.pending.map((item) => item.sleeve_id)).toEqual([
      "pending-observation",
      "pending-activation",
    ]);
    expect(summary.manual.map((item) => item.sleeve_id)).toEqual(["manual"]);
    expect(summary.historical.map((item) => item.sleeve_id)).toEqual(["fossil-a"]);
    expect(summary.officialInitialCash).toBe(10_000);
    expect(summary.officialAvailableCash).toBe(94.06);
  });

  it("localizes sleeve status and mode without leaking raw tokens", () => {
    expect(strategySleeveStatusLabel("running", "zh")).toBe("运行中");
    expect(strategySleeveStatusLabel("stopped", "zh")).toBe("已停止");
    expect(strategySleeveModeLabel("allocated", "zh")).toBe("已划拨资金");
    expect(strategySleeveModeLabel("signal_only", "zh")).toBe("仅记录信号");
  });

  it("uses the digest-bound Chinese name stored by future hangs", () => {
    const future = sleeve("future", {
      metadata: {
        mandate_id: "remote-hang",
        candidate_id: "artifact-future",
        display_name_zh: "30 日成交量异动因子",
      },
    });

    expect(
      strategySleeveDisplayName(future, "d34_future_hash", "正式已挂策略", "zh"),
    ).toBe("30 日成交量异动因子");
  });

  it("relabels the visible legacy hang config without changing its identity", () => {
    expect(strategyConfigDisplayName("挂上 · d34_a729", "zh")).toBe(
      "模拟运行策略 · d34_a729",
    );
    expect(strategyConfigDisplayName("挂上 · d34_a729", "en")).toBe(
      "Simulation strategy · d34_a729",
    );
    expect(strategyConfigDisplayName("每日动量策略", "zh")).toBe("每日动量策略");
  });

  it("opens operational detail only for actionable execution or recovery states", () => {
    const clear = {
      target_date: "2026-08-25",
      sleeve_count: 1,
      pending_sleeve_count: 0,
      running_sleeve_count: 1,
      pending_execution_count: 0,
      pending_due_count: 0,
      filled_count: 0,
      blocked_count: 0,
      recovery_required_count: 0,
      pending_journal_count: 0,
      corrupt_journal_count: 0,
    };
    expect(strategyOpsNeedsAttention(clear)).toBe(false);
    expect(strategyOpsNeedsAttention({ ...clear, pending_due_count: 1 })).toBe(false);
    expect(strategyOpsNeedsAttention({ ...clear, recovery_required_count: 1 })).toBe(true);
  });
});
