'use client';

import { useId, type JSX, type ReactNode } from "react";

/**
 * Shared panel chrome for the Hermes workbench.
 *
 * Panels only own their chrome — border, header, count badge, error line and
 * empty placeholder — so the six workbench panels stop re-implementing (and
 * drifting on) the same markup. There is deliberately no collapse toggle: in
 * the drawer layout the drawer carries the collapse semantics, and a second
 * collapse affordance inside it would be redundant.
 *
 * Copy is passed in via props, so the component stays language-neutral.
 */
export type PanelProps = {
  title: string;
  /** Header-right count badge. Hidden when null/undefined. */
  count?: number | null;
  /** Error line rendered above the body with role="alert". */
  error?: string | null;
  /** Placeholder copy shown instead of children when isEmpty is true. */
  empty?: string | null;
  isEmpty?: boolean;
  /** Trailing header slot (e.g. a receipt link). */
  headerExtra?: ReactNode;
  children: ReactNode;
  /** Pass-through test anchors, e.g. data-hermes-approvals-panel. */
  [dataAttr: `data-${string}`]: unknown;
};

export function Panel({
  title,
  count,
  error,
  empty,
  isEmpty,
  headerExtra,
  children,
  ...dataProps
}: PanelProps): JSX.Element {
  const showEmpty = Boolean(isEmpty) && Boolean(empty);
  // The section is a landmark, so it needs an accessible name; the panel title
  // is that name and never has to be repeated as a hand-written aria-label.
  const titleId = useId();

  return (
    <section
      {...(dataProps as Record<string, string>)}
      aria-labelledby={titleId}
      className="rounded-[var(--radius-card)] border border-border-subtle bg-bg-surface"
    >
      <header className="flex items-center gap-2 border-b border-border-subtle px-3 py-2">
        <h3 className="min-w-0 flex-1 truncate font-label-caps text-text-secondary" id={titleId}>
          {title}
        </h3>
        {typeof count === "number" ? (
          <span className="shrink-0 rounded-full bg-bg-surface-muted px-2 text-[11px] text-text-secondary">
            {count}
          </span>
        ) : null}
        {headerExtra ? <div className="shrink-0">{headerExtra}</div> : null}
      </header>
      <div className="px-3 py-2">
        {error ? (
          <p className="mb-2 font-body-sm text-danger" role="alert">
            {error}
          </p>
        ) : null}
        {showEmpty ? <p className="font-body-sm text-text-secondary">{empty}</p> : children}
      </div>
    </section>
  );
}
