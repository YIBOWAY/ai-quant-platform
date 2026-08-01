import { describe, expect, it } from "vitest";

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
  it("returns 0 for empty or non-array input", () => {
    expect(pendingApprovalCount([])).toBe(0);
    expect(pendingApprovalCount(undefined as unknown as unknown[])).toBe(0);
    expect(pendingApprovalCount(null as unknown as unknown[])).toBe(0);
  });

  it("counts only pending rows", () => {
    expect(
      pendingApprovalCount([
        { approval_id: "a1", status: "pending" },
        { approval_id: "a2", status: "decided" },
        { approval_id: "a3", status: "expired" },
        { approval_id: "a4", status: "pending" },
      ]),
    ).toBe(2);
  });

  it("is case-insensitive on status", () => {
    expect(
      pendingApprovalCount([
        { approval_id: "a1", status: "PENDING" },
        { approval_id: "a2", status: "Pending" },
      ]),
    ).toBe(2);
  });

  it("falls back to expected_status then to pending", () => {
    expect(
      pendingApprovalCount([
        { approval_id: "a1", expected_status: "pending" },
        { approval_id: "a2", expected_status: "decided" },
        { approval_id: "a3" },
      ]),
    ).toBe(2);
  });

  it("prefers status over expected_status", () => {
    expect(
      pendingApprovalCount([
        { approval_id: "a1", status: "decided", expected_status: "pending" },
      ]),
    ).toBe(0);
  });

  it("ignores rows without a usable approval_id", () => {
    expect(
      pendingApprovalCount([
        { status: "pending" },
        { approval_id: "", status: "pending" },
        { approval_id: 7, status: "pending" },
        null,
        "pending",
        { approval_id: "a1", status: "pending" },
      ]),
    ).toBe(1);
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
