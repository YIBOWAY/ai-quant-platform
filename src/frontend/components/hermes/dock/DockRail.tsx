'use client';

import { useCallback, useSyncExternalStore } from "react";

import type { Locale } from "@/lib/locale";

import {
  DOCK_PANELS,
  dockPanelLabel,
  readStoredDockPanel,
  subscribeStoredDockPanel,
  writeStoredDockPanel,
  type DockPanelId,
} from "./dockPanels";

export type DockRailProps = {
  locale: Locale;
  /** Currently open panel, or null when the drawer is closed. */
  open: DockPanelId | null;
  /** Toggle semantics: clicking the open panel's icon closes the drawer. */
  onToggle: (id: DockPanelId) => void;
  /** Badge count rendered over the approvals icon; 0 hides the badge. */
  pendingApprovals?: number;
};

const RAIL_BUTTON_CLASS =
  "app-touch-target relative flex items-center justify-center rounded-[8px] text-text-secondary transition-colors hover:bg-bg-surface-muted hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info motion-reduce:transition-none";

const RAIL_BUTTON_OPEN_CLASS = "bg-bg-surface-muted text-text-primary";

/**
 * Open-panel state backed by localStorage as the external store, so the server
 * snapshot is `null` (matching SSR) and the client hydrates to the persisted id
 * without a setState-in-effect cascade.
 */
export function useDockPanelState(): {
  open: DockPanelId | null;
  toggle: (id: DockPanelId) => void;
  close: () => void;
} {
  const open = useSyncExternalStore(
    subscribeStoredDockPanel,
    readStoredDockPanel,
    () => null,
  );

  const toggle = useCallback(
    (id: DockPanelId) => {
      writeStoredDockPanel(open === id ? null : id);
    },
    [open],
  );

  const close = useCallback(() => {
    writeStoredDockPanel(null);
  }, []);

  return { open, toggle, close };
}

/**
 * Fixed right-edge icon rail. One button per dock panel; the open one is
 * `aria-pressed`. Approvals carries an amber badge while approvals are pending.
 */
export function DockRail({
  locale,
  open,
  onToggle,
  pendingApprovals = 0,
}: DockRailProps) {
  const isZh = locale === "zh";
  return (
    <nav
      aria-label={isZh ? "工作台面板" : "Workbench panels"}
      className="fixed inset-y-0 right-0 z-30 flex w-[var(--spacing-dock-rail)] flex-col items-center gap-1 border-l border-border-subtle bg-bg-surface py-2"
      data-hermes-dock-rail
    >
      {DOCK_PANELS.map((panel) => {
        const Icon = panel.icon;
        const label = dockPanelLabel(panel, locale);
        const isOpen = open === panel.id;
        const badge = panel.id === "approvals" ? pendingApprovals : 0;
        return (
          <button
            aria-label={label}
            aria-pressed={isOpen}
            className={`${RAIL_BUTTON_CLASS} ${isOpen ? RAIL_BUTTON_OPEN_CLASS : ""}`}
            data-hermes-dock-rail-button={panel.id}
            key={panel.id}
            onClick={() => onToggle(panel.id)}
            title={label}
            type="button"
          >
            <Icon aria-hidden="true" size={20} />
            {badge > 0 ? (
              <span
                className="absolute right-1 top-1 min-w-[16px] rounded-full bg-warning px-1 text-center font-data-mono text-[10px] leading-4 text-bg-base"
                data-hermes-dock-badge={panel.id}
              >
                {badge > 99 ? "99+" : badge}
              </span>
            ) : null}
            <span className="sr-only">
              {badge > 0
                ? isZh
                  ? `，${badge} 条待审批`
                  : `, ${badge} pending`
                : ""}
            </span>
          </button>
        );
      })}
    </nav>
  );
}
