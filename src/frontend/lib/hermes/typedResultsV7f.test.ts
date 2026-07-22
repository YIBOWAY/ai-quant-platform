import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import {
  filterResultsForPanel,
  isReal,
  isSample,
  resultRowKey,
} from "@/components/hermes/results/WorkbenchTypedResultsPanel";
import type { WorkspaceResultProjection } from "./workspaceClient";
import {
  __followSpineTestUtils,
  createWorkspaceFollowSpine,
  resultIdsFromProjection,
} from "./workspaceFollowSpine";

const {
  emptyState,
  asResultList,
  EMPTY_AUTHORITY_HEALTH,
  normalizeSampleOrReal,
  normalizeReadStatus,
} = __followSpineTestUtils;

const fetchWorkspaceSnapshot = vi.fn();
const fetchWorkspaceFollow = vi.fn();

vi.mock("./workspaceClient", async () => {
  const actual = await vi.importActual<typeof import("./workspaceClient")>(
    "./workspaceClient",
  );
  return {
    ...actual,
    fetchWorkspaceSnapshot: (...args: unknown[]) =>
      fetchWorkspaceSnapshot(...args),
    fetchWorkspaceFollow: (...args: unknown[]) => fetchWorkspaceFollow(...args),
  };
});

function sampleOptions(): WorkspaceResultProjection {
  return {
    result_id: "res-opt-1",
    id: "res-opt-1",
    kind: "options_vertical_a",
    display_title: "AAPL 2026-08-21 200 C",
    status: "ready",
    sample_or_real: "sample",
    freshness: "fresh",
    read_status: "available",
    ticker: "AAPL",
    expiry: "2026-08-21",
    strike: 200,
    bid: 1.2,
    ask: 1.35,
    delta: 0.25,
    iv: 0.28,
    apr: 0.18,
    filters: ["delta_band"],
    exclusions: ["earnings_week"],
    limitations: ["hermetic_fixture", "not_live_futu_quote"],
    provider_evidence: ["hermetic_seed"],
    task_id: "task-1",
    run_id: "run-1",
    exact_links: {
      task_id: "task-1",
      task_ref: "task:task-1",
      run_id: "run-1",
      run_ref: "run:run-1",
    },
  };
}

describe("V7f typed results helpers", () => {
  it("filterResultsForPanel drops empty ids", () => {
    const rows = filterResultsForPanel([
      sampleOptions(),
      {
        result_id: "",
        kind: "generic",
        display_title: "x",
        sample_or_real: "sample",
      },
    ]);
    expect(rows).toHaveLength(1);
    expect(resultRowKey(rows[0])).toBe("res-opt-1");
  });

  it("asResultList coerces bare ids and typed objects", () => {
    const list = asResultList([
      "bare-1",
      sampleOptions(),
      { id: "from-id", kind: "backtest", display_title: "BT" },
      null,
      "",
    ]);
    expect(list.map((r: WorkspaceResultProjection) => r.result_id)).toEqual([
      "bare-1",
      "res-opt-1",
      "from-id",
    ]);
    expect(list[0].sample_or_real).toBe("sample");
    // Bare id has no proven payload — never claim available.
    expect(list[0].read_status).toBe("unavailable");
    expect(list[1].ticker).toBe("AAPL");
    // Missing mark/read_status on partial objects fail closed.
    expect(list[2].sample_or_real).toBe("sample");
    expect(list[2].read_status).toBe("unavailable");
  });

  it("sample/real and read_status fail closed", () => {
    expect(normalizeSampleOrReal("real")).toBe("real");
    expect(normalizeSampleOrReal("REAL")).toBe("real");
    expect(normalizeSampleOrReal("sample")).toBe("sample");
    expect(normalizeSampleOrReal("live")).toBe("sample");
    expect(normalizeSampleOrReal(undefined)).toBe("sample");
    expect(normalizeSampleOrReal("")).toBe("sample");

    expect(normalizeReadStatus("available")).toBe("available");
    expect(normalizeReadStatus("degraded")).toBe("degraded");
    expect(normalizeReadStatus("bogus")).toBe("unavailable");
    expect(normalizeReadStatus(undefined)).toBe("unavailable");

    const weird = asResultList([
      {
        result_id: "r-weird",
        kind: "generic",
        display_title: "w",
        sample_or_real: "live-quote",
        read_status: "ok",
      },
      {
        result_id: "r-real",
        kind: "generic",
        display_title: "r",
        sample_or_real: "real",
        read_status: "available",
      },
    ]);
    expect(weird[0].sample_or_real).toBe("sample");
    expect(weird[0].read_status).toBe("unavailable");
    expect(weird[1].sample_or_real).toBe("real");
    expect(weird[1].read_status).toBe("available");

    // Panel badge helpers: only exact "real" is REAL.
    expect(isSample({ result_id: "a", kind: "generic", display_title: "a", sample_or_real: "live" })).toBe(true);
    expect(isReal({ result_id: "a", kind: "generic", display_title: "a", sample_or_real: "live" })).toBe(false);
    expect(isSample({ result_id: "a", kind: "generic", display_title: "a", sample_or_real: "real" })).toBe(false);
    expect(isReal({ result_id: "a", kind: "generic", display_title: "a", sample_or_real: "real" })).toBe(true);
    expect(
      isSample({
        result_id: "a",
        kind: "generic",
        display_title: "a",
      } as WorkspaceResultProjection),
    ).toBe(true);
  });

  it("resultIdsFromProjection never invents task rows", () => {
    expect(resultIdsFromProjection([sampleOptions(), "x"])).toEqual([
      "res-opt-1",
      "x",
    ]);
    expect(resultIdsFromProjection(undefined)).toEqual([]);
  });

  it("emptyState results start empty with result health unavailable", () => {
    const s = emptyState();
    expect(s.results).toEqual([]);
    expect(s.authorityHealth.result).toBe("unavailable");
    expect(EMPTY_AUTHORITY_HEALTH.result).toBe("unavailable");
  });
});

describe("V7f typed results on spine", () => {
  beforeEach(() => {
    fetchWorkspaceSnapshot.mockReset();
    fetchWorkspaceFollow.mockReset();
    fetchWorkspaceFollow.mockResolvedValue({
      events: [],
      next_cursor: 0,
      resync_required: false,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("snapshot reconcile carries typed results separate from gates/approvals", async () => {
    fetchWorkspaceSnapshot.mockResolvedValue({
      workspace_id: "ws-local-main",
      observed_at: "2026-07-23T00:00:00Z",
      snapshot_workspace_cursor: 5,
      sessions: [],
      commands: [],
      approvals: [],
      gates: [],
      tasks: [],
      attempts: [],
      runs: [],
      results: [sampleOptions()],
      authority_health: {
        ...EMPTY_AUTHORITY_HEALTH,
        result: "ready",
        command_approval: "ready",
        gate_1: "ready",
        gate_2: "ready",
        gate_3: "ready",
      },
    });

    vi.stubGlobal(
      "EventSource",
      class {
        close() {}
        addEventListener() {}
        removeEventListener() {}
      },
    );

    const spine = createWorkspaceFollowSpine({
      preferSse: false,
      pollMs: 60_000,
      snapshotReconcileMs: 0,
    });
    try {
      await spine.resyncNow();
      const s = spine.getState();
      expect(s.results).toHaveLength(1);
      expect(s.results[0].result_id).toBe("res-opt-1");
      expect(s.results[0].kind).toBe("options_vertical_a");
      expect(s.results[0].sample_or_real).toBe("sample");
      expect(s.results[0].ticker).toBe("AAPL");
      expect(s.authorityHealth.result).toBe("ready");
      expect(s.approvals).toEqual([]);
      expect(s.gates).toEqual([]);
      expect(s.tasks).toEqual([]);
    } finally {
      spine.stop();
    }
  });
});
