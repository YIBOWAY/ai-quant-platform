'use client';

import {
  type KeyboardEvent,
  type ReactNode,
  useId,
  useRef,
  useState,
} from "react";

export type TabItem = {
  id: string;
  label: ReactNode;
  content: ReactNode;
};

/**
 * Lightweight pill tabs. Keyboard-accessible, no external dependency.
 * Used to separate distinct workflows on one page (e.g. Live Account vs
 * Historical Replay) without splitting into separate routes.
 *
 * Interaction contract (aligned with Hermes ledger tabs):
 * - roving tabindex
 * - ArrowLeft / ArrowRight / Home / End
 * - aria-controls + labelled panel
 */
export function Tabs({
  items,
  defaultId,
  className = "",
}: {
  items: TabItem[];
  defaultId?: string;
  className?: string;
}) {
  const baseId = useId();
  const [active, setActive] = useState(defaultId ?? items[0]?.id);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const activeItem = items.find((item) => item.id === active) ?? items[0];
  function activate(id: string, focus = false) {
    setActive(id);
    if (!focus) return;
    const index = items.findIndex((item) => item.id === id);
    if (index >= 0) {
      tabRefs.current[index]?.focus();
    }
  }

  function onTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (!items.length) return;
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const last = items.length - 1;
    const nextIndex =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? last
          : event.key === "ArrowRight"
            ? (index + 1) % items.length
            : (index - 1 + items.length) % items.length;
    const next = items[nextIndex];
    if (next) activate(next.id, true);
  }

  if (!activeItem) {
    return null;
  }

  const panelId = `${baseId}-panel-${activeItem.id}`;
  const activeTabId = `${baseId}-tab-${activeItem.id}`;

  return (
    <div className={className}>
      <div
        role="tablist"
        aria-orientation="horizontal"
        className="flex gap-1 rounded-lg border border-border-subtle bg-bg-surface p-1"
      >
        {items.map((item, index) => {
          const isActive = item.id === activeItem.id;
          const tabId = `${baseId}-tab-${item.id}`;
          return (
            <button
              key={item.id}
              ref={(node) => {
                tabRefs.current[index] = node;
              }}
              id={tabId}
              role="tab"
              type="button"
              aria-selected={isActive}
              aria-controls={isActive ? panelId : undefined}
              tabIndex={isActive ? 0 : -1}
              onClick={() => activate(item.id)}
              onKeyDown={(event) => onTabKeyDown(event, index)}
              className={`relative flex flex-1 items-center justify-center gap-2 rounded-lg px-3 py-2 font-body-sm font-medium transition-colors ${
                isActive
                  ? "border border-border-subtle bg-bg-surface-muted text-text-primary"
                  : "border border-transparent text-text-secondary hover:bg-bg-surface-muted hover:text-text-primary"
              }`}
            >
              {item.label}
              {isActive ? (
                <span
                  aria-hidden
                  className="pointer-events-none absolute inset-x-2 bottom-1 h-0.5 rounded-full bg-info/80 motion-panel-enter"
                />
              ) : null}
            </button>
          );
        })}
      </div>
      <div
        key={activeItem.id}
        id={panelId}
        role="tabpanel"
        aria-labelledby={activeTabId}
        className="motion-panel-enter mt-4"
      >
        {activeItem.content}
      </div>
    </div>
  );
}
