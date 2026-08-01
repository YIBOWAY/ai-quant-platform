import { describe, expect, it } from "vitest";

import {
  canDecideCommandApproval,
  filterApprovalsForPanel,
} from "@/lib/hermes/commandApprovalPredicates";
import type { WorkspaceApprovalProjection } from "@/lib/hermes/workspaceClient";

import {
  DOCK_OPEN_STORAGE_KEY,
  DOCK_PANELS,
  dockPanelLabel,
  isDockPanelId,
  pendingApprovalCount,
  readStoredDockPanel,
  subscribeStoredDockPanel,
  writeStoredDockPanel,
  type DockPanelId,
} from "./dockPanels";

describe("DOCK_PANELS", () => {
  it("declares the six dock panels in rail order", () => {
    expect(DOCK_PANELS.map((panel) => panel.id)).toEqual([
      "approvals",
      "activity",
      "runs",
      "results",
      "gates",
      "authority",
    ]);
  });

  it("gives every panel an icon and both locale labels", () => {
    for (const panel of DOCK_PANELS) {
      expect(typeof panel.icon).not.toBe("undefined");
      expect(panel.labelEn.length).toBeGreaterThan(0);
      expect(panel.labelZh.length).toBeGreaterThan(0);
    }
  });

  it("has unique ids", () => {
    const ids = new Set(DOCK_PANELS.map((panel) => panel.id));
    expect(ids.size).toBe(DOCK_PANELS.length);
  });

  it("pins the localStorage key", () => {
    expect(DOCK_OPEN_STORAGE_KEY).toBe("hermes-dock-open");
  });
});

describe("dockPanelLabel", () => {
  it("selects by locale", () => {
    const approvals = DOCK_PANELS[0];
    expect(dockPanelLabel(approvals, "en")).toBe("Approvals");
    expect(dockPanelLabel(approvals, "zh")).toBe("审批");
  });
});

describe("isDockPanelId", () => {
  it("accepts known ids and rejects everything else", () => {
    expect(isDockPanelId("approvals")).toBe(true);
    expect(isDockPanelId("authority")).toBe(true);
    expect(isDockPanelId("transcript")).toBe(false);
    expect(isDockPanelId("")).toBe(false);
    expect(isDockPanelId(null)).toBe(false);
    expect(isDockPanelId(3)).toBe(false);
  });

  it("narrows to DockPanelId", () => {
    const raw: unknown = "runs";
    if (isDockPanelId(raw)) {
      const id: DockPanelId = raw;
      expect(id).toBe("runs");
    } else {
      throw new Error("expected narrowing");
    }
  });
});

describe("pendingApprovalCount", () => {
  const decidable = (id: string) => ({
    approval_id: id,
    run_id: "run.1",
    digest: "a".repeat(64),
    expires_at: "2099-01-01T00:00:00.000000Z",
    status: "pending",
    kind: "hermes.command_approval",
  });

  it("returns 0 for empty or non-array input", () => {
    expect(pendingApprovalCount([])).toBe(0);
    expect(pendingApprovalCount(undefined as unknown as unknown[])).toBe(0);
    expect(pendingApprovalCount(null as unknown as unknown[])).toBe(0);
  });

  it("counts fully CAS-bound pending rows", () => {
    expect(pendingApprovalCount([decidable("a1"), decidable("a2")])).toBe(2);
  });

  it("excludes non-pending rows", () => {
    expect(
      pendingApprovalCount([
        { ...decidable("a1"), status: "denied", decision: "deny" },
        { ...decidable("a2"), status: "expired" },
        decidable("a3"),
      ]),
    ).toBe(1);
  });

  it("excludes rows missing any CAS field the panel requires", () => {
    expect(
      pendingApprovalCount([
        { ...decidable("a1"), run_id: "" },
        { ...decidable("a2"), digest: "" },
        { ...decidable("a3"), digest: "not-a-sha256" },
        { ...decidable("a4"), digest: "A".repeat(64) },
        { ...decidable("a5"), expires_at: "" },
      ]),
    ).toBe(0);
  });

  it("falls back to expected_status then to pending", () => {
    const { status: _status, ...noStatus } = decidable("a1");
    expect(
      pendingApprovalCount([
        { ...noStatus, expected_status: "pending" },
        { ...decidable("a2"), status: "", expected_status: "decided" },
        noStatus,
      ]),
    ).toBe(2);
  });

  it("is case-insensitive on status", () => {
    expect(
      pendingApprovalCount([
        { ...decidable("a1"), status: "PENDING" },
        { ...decidable("a2"), status: "Pending" },
      ]),
    ).toBe(2);
  });

  it("ignores rows without a usable approval_id", () => {
    expect(
      pendingApprovalCount([
        { ...decidable("a1"), approval_id: "" },
        { ...decidable("a2"), approval_id: 7 },
        null,
        "pending",
        decidable("a3"),
      ]),
    ).toBe(1);
  });

  it("honors the panel's optimistic-hide set", () => {
    const rows = [decidable("a1"), decidable("a2")];
    expect(pendingApprovalCount(rows, { a1: true })).toBe(1);
  });

  it("agrees with the panel predicates it delegates to", () => {
    const rows = [
      decidable("a1"),
      { ...decidable("a2"), status: "denied" },
      { ...decidable("a3"), run_id: "" },
    ] as unknown as WorkspaceApprovalProjection[];
    const viaPanel = filterApprovalsForPanel(rows, {}).filter(
      canDecideCommandApproval,
    ).length;
    expect(pendingApprovalCount(rows)).toBe(viaPanel);
  });
});

describe("dock panel storage (no window: node/SSR path)", () => {
  it("reads null when there is no window", () => {
    expect(typeof window).toBe("undefined");
    expect(readStoredDockPanel()).toBeNull();
  });

  it("writing without a window does not throw and still notifies subscribers", () => {
    let calls = 0;
    const unsubscribe = subscribeStoredDockPanel(() => {
      calls += 1;
    });
    expect(() => writeStoredDockPanel("gates")).not.toThrow();
    expect(calls).toBe(1);
    writeStoredDockPanel(null);
    expect(calls).toBe(2);
    unsubscribe();
    writeStoredDockPanel("runs");
    expect(calls).toBe(2);
  });
});
