/**
 * Dock panel registry + pure helpers shared by DockRail / DockDrawer.
 * No React, no DOM — safe to unit test in the node vitest environment.
 */

import {
  BadgeCheck,
  CirclePlay,
  Database,
  FileChartColumn,
  ListTree,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";

export type DockPanelId =
  | "approvals"
  | "activity"
  | "runs"
  | "results"
  | "gates"
  | "authority";

export type DockPanel = {
  id: DockPanelId;
  icon: LucideIcon;
  labelEn: string;
  labelZh: string;
};

export const DOCK_PANELS: ReadonlyArray<DockPanel> = [
  { id: "approvals", icon: BadgeCheck, labelEn: "Approvals", labelZh: "审批" },
  { id: "activity", icon: ListTree, labelEn: "Activity", labelZh: "活动" },
  { id: "runs", icon: CirclePlay, labelEn: "Runs", labelZh: "运行" },
  { id: "results", icon: FileChartColumn, labelEn: "Results", labelZh: "结果" },
  { id: "gates", icon: ShieldCheck, labelEn: "Gates", labelZh: "闸门" },
  { id: "authority", icon: Database, labelEn: "Authority", labelZh: "权威" },
] as const;

export const DOCK_OPEN_STORAGE_KEY = "hermes-dock-open";

export function isDockPanelId(value: unknown): value is DockPanelId {
  return (
    typeof value === "string" &&
    DOCK_PANELS.some((panel) => panel.id === value)
  );
}

export function dockPanelLabel(panel: DockPanel, locale: "en" | "zh"): string {
  return locale === "zh" ? panel.labelZh : panel.labelEn;
}

/** SSR-safe read of the persisted open panel. Returns null when absent/invalid. */
export function readStoredDockPanel(): DockPanelId | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(DOCK_OPEN_STORAGE_KEY);
    return isDockPanelId(raw) ? raw : null;
  } catch {
    return null;
  }
}

/** SSR-safe write; null clears the key. Storage failures are non-fatal. */
export function writeStoredDockPanel(id: DockPanelId | null): void {
  if (typeof window !== "undefined") {
    try {
      if (id === null) window.localStorage.removeItem(DOCK_OPEN_STORAGE_KEY);
      else window.localStorage.setItem(DOCK_OPEN_STORAGE_KEY, id);
    } catch {
      /* private mode / quota — the dock still works, it just forgets */
    }
  }
  notifyDockPanelListeners();
}

const dockPanelListeners = new Set<() => void>();

function notifyDockPanelListeners(): void {
  for (const listener of dockPanelListeners) listener();
}

/**
 * useSyncExternalStore subscribe: same-tab writes notify directly, other tabs
 * arrive via the storage event. Returns an unsubscribe.
 */
export function subscribeStoredDockPanel(onChange: () => void): () => void {
  dockPanelListeners.add(onChange);
  const onStorage = (event: StorageEvent) => {
    if (event.key === null || event.key === DOCK_OPEN_STORAGE_KEY) onChange();
  };
  if (typeof window !== "undefined") {
    window.addEventListener("storage", onStorage);
  }
  return () => {
    dockPanelListeners.delete(onChange);
    if (typeof window !== "undefined") {
      window.removeEventListener("storage", onStorage);
    }
  };
}

/**
 * Badge count for the approvals rail icon.
 *
 * Mirrors the pending predicate of canDecideCommandApproval in
 * WorkbenchCommandApprovalsPanel: effective status is `status`, falling back to
 * `expected_status`, falling back to "pending". Rows without an approval_id are
 * not real projection rows and never counted. Input is `unknown[]` because the
 * spine state is only structurally trusted at the panel boundary.
 */
export function pendingApprovalCount(approvals: unknown[]): number {
  if (!Array.isArray(approvals)) return 0;
  let count = 0;
  for (const row of approvals) {
    if (!row || typeof row !== "object") continue;
    const record = row as Record<string, unknown>;
    const approvalId = record.approval_id;
    if (typeof approvalId !== "string" || approvalId.length === 0) continue;
    const status =
      typeof record.status === "string" && record.status
        ? record.status
        : typeof record.expected_status === "string" && record.expected_status
          ? record.expected_status
          : "pending";
    if (status.toLowerCase() === "pending") count += 1;
  }
  return count;
}
