'use client';

import { type ReactNode, useState } from "react";

export type TabItem = {
  id: string;
  label: ReactNode;
  content: ReactNode;
};

/**
 * Lightweight pill tabs. Keyboard-accessible, no external dependency.
 * Used to separate distinct workflows on one page (e.g. Live Account vs
 * Historical Replay) without splitting into separate routes.
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
  const [active, setActive] = useState(defaultId ?? items[0]?.id);
  const activeItem = items.find((item) => item.id === active) ?? items[0];

  return (
    <div className={className}>
      <div
        role="tablist"
        className="flex gap-1 rounded-lg border border-border-subtle bg-bg-surface p-1"
      >
        {items.map((item) => {
          const isActive = item.id === activeItem?.id;
          return (
            <button
              key={item.id}
              role="tab"
              aria-selected={isActive}
              type="button"
              onClick={() => setActive(item.id)}
              className={`flex flex-1 items-center justify-center gap-2 rounded-lg px-3 py-2 font-body-sm font-medium transition-colors ${
                isActive
                  ? "bg-accent-success/15 text-accent-success"
                  : "text-text-secondary hover:bg-bg-surface-muted hover:text-text-primary"
              }`}
            >
              {item.label}
            </button>
          );
        })}
      </div>
      <div role="tabpanel" className="mt-4">
        {activeItem?.content}
      </div>
    </div>
  );
}
