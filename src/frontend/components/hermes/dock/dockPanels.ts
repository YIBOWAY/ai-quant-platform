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

import {
  canDecideCommandApproval,
  filterApprovalsForPanel,
} from "@/lib/hermes/commandApprovalPredicates";
import type { WorkspaceApprovalProjection } from "@/lib/hermes/workspaceClient";

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
 * Badge count for the approvals rail icon: rows the approvals panel would
 * render as decidable. Uses the same two predicates the panel uses, so the
 * badge can never disagree with what the panel shows.
 *
 * `consumedIds` is the panel's optimistic-hide set; the dock has no decide
 * controls of its own, so callers normally omit it.
 */
export function pendingApprovalCount(
  approvals: unknown[],
  consumedIds: Record<string, true> = {},
): number {
  if (!Array.isArray(approvals)) return 0;
  const rows = approvals.filter(
    (row): row is WorkspaceApprovalProjection =>
      !!row &&
      typeof row === "object" &&
      typeof (row as { approval_id?: unknown }).approval_id === "string",
  );
  return filterApprovalsForPanel(rows, consumedIds).filter(
    canDecideCommandApproval,
  ).length;
}
