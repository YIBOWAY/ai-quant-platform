'use client';

import type { ReactNode } from "react";

/**
 * Shared UI primitives for the quant platform frontend.
 *
 * Design system (anchor: Linear spacing/motion + Bloomberg Terminal density):
 * - Surfaces: hairline borders (border-border-subtle), no drop shadows.
 * - Radius: rounded-lg (8px) uniformly.
 * - Semantic color: success/danger are reserved for genuine financial or
 *   safety outcomes; info/neutral carry active navigation and generic actions.
 * - Data is monospace (font-data-mono); labels are uppercase caps (font-label-caps).
 * - Spacing rhythm: 4 / 8 / 12 / 16 / 24 (Tailwind 1/2/3/4/6).
 *
 * These primitives exist so every page composes the same vocabulary instead of
 * re-inventing card/metric/section markup (which drifts into inconsistency).
 */

type Tone = "neutral" | "success" | "warning" | "danger" | "info";

const toneText: Record<Tone, string> = {
  neutral: "text-text-primary",
  success: "text-accent-success",
  warning: "text-warning",
  danger: "text-danger",
  info: "text-info",
};

const toneBorder: Record<Tone, string> = {
  neutral: "border-border-subtle",
  success: "border-accent-success/30",
  warning: "border-warning/40",
  danger: "border-danger/40",
  info: "border-info/40",
};

const toneSurfaceTint: Record<Tone, string> = {
  neutral: "bg-bg-surface",
  success: "bg-accent-success/5",
  warning: "bg-warning/5",
  danger: "bg-danger/5",
  info: "bg-info/5",
};

export const terminalInputClass =
  "rounded-lg border border-border-subtle bg-bg-base px-3 py-2 font-data-mono text-text-primary outline-none transition-colors focus:border-info focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info disabled:cursor-not-allowed disabled:opacity-50";

export const terminalInputCompactClass =
  "rounded-lg border border-border-subtle bg-bg-base px-2 py-2 font-data-mono text-text-primary outline-none transition-colors focus:border-info focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info disabled:cursor-not-allowed disabled:opacity-50";

export const terminalFilterInputClass =
  "h-8 rounded-lg border border-border-subtle bg-bg-base px-2 font-data-mono text-text-primary outline-none transition-colors focus:border-info focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info disabled:cursor-not-allowed disabled:opacity-50";

/** A bordered surface. The base building block for every panel. */
export function Card({
  children,
  tone = "neutral",
  className = "",
  padded = true,
}: {
  children: ReactNode;
  tone?: Tone;
  className?: string;
  padded?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border ${toneBorder[tone]} ${toneSurfaceTint[tone]} ${
        padded ? "p-4" : ""
      } ${className}`}
    >
      {children}
    </div>
  );
}

/** Page-level header: small caps eyebrow, headline, optional subtitle + actions. */
export function PageHeader({
  eyebrow,
  title,
  subtitle,
  actions,
  icon,
}: {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-4 border-b border-border-subtle pb-4">
      <div className="min-w-0">
        {eyebrow ? (
          <p className="font-label-caps uppercase text-text-secondary">{eyebrow}</p>
        ) : null}
        <div className="mt-1 flex items-center gap-2">
          {icon}
          <h1 className="font-headline-xl text-text-primary">{title}</h1>
        </div>
        {subtitle ? (
          <p className="mt-2 max-w-3xl font-body-sm text-text-secondary">{subtitle}</p>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

/** Section heading inside a page. */
export function SectionTitle({
  title,
  hint,
  right,
}: {
  title: string;
  hint?: string;
  right?: ReactNode;
}) {
  return (
    <div className="mb-3 flex items-end justify-between gap-3">
      <div>
        <h2 className="font-label-caps text-text-primary">{title}</h2>
        {hint ? <p className="mt-1 font-body-sm text-text-secondary">{hint}</p> : null}
      </div>
      {right ? <div className="shrink-0">{right}</div> : null}
    </div>
  );
}

/**
 * A single metric. Two sizes:
 * - "card" (default): bordered box, big value — for KPI rows.
 * - "inline": compact label/value stack for dense status strips.
 */
export function MetricStat({
  label,
  value,
  tone = "neutral",
  hint,
  delta,
  size = "card",
}: {
  label: string;
  value: ReactNode;
  tone?: Tone;
  hint?: string;
  delta?: ReactNode;
  size?: "card" | "inline";
}) {
  if (size === "inline") {
    return (
      <div className="flex min-w-0 flex-col gap-0.5 px-3 py-2" title={hint}>
        <span className="truncate font-label-caps text-[10px] uppercase text-text-secondary">
          {label}
        </span>
        <span className={`truncate font-data-mono text-sm font-bold ${toneText[tone]}`}>
          {value}
        </span>
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-border-subtle bg-bg-surface p-3" title={hint}>
      <div className="font-label-caps text-text-secondary">{label}</div>
      <div className={`mt-2 font-data-mono text-lg font-bold ${toneText[tone]}`}>{value}</div>
      {delta ? <div className="mt-1 font-body-sm text-text-secondary">{delta}</div> : null}
    </div>
  );
}

/** A small status pill (label + value), divider-friendly for status bars. */
export function StatusPill({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  tone?: Tone;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 font-data-mono text-[10px] uppercase ${toneBorder[tone]} ${toneSurfaceTint[tone]} ${toneText[tone]}`}
    >
      <span className="opacity-70">{label}</span>
      <span className="font-bold">{value}</span>
    </span>
  );
}

export type TerminalTableColumn = {
  label: ReactNode;
  align?: "left" | "right" | "center";
  className?: string;
  title?: string;
};

const alignClass: Record<NonNullable<TerminalTableColumn["align"]>, string> = {
  left: "text-left",
  right: "text-right",
  center: "text-center",
};

/** Dense, internally scrolling data table for terminal-style operational pages. */
export function TerminalTable({
  columns,
  children,
  minWidth = "880px",
  className = "",
}: {
  columns: TerminalTableColumn[];
  children: ReactNode;
  minWidth?: string;
  className?: string;
}) {
  return (
    <div className={`overflow-hidden rounded-lg border border-border-subtle bg-bg-surface ${className}`}>
      <div
        aria-label="Scrollable data table"
        className="overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
        data-terminal-table-scroll="true"
        tabIndex={0}
      >
        <table className="w-full border-collapse text-left" style={{ minWidth }}>
          <thead>
            <tr className="border-b border-border-subtle bg-bg-surface text-text-secondary">
              {columns.map((column, index) => (
                <th
                  className={`px-3 py-2.5 font-label-caps ${alignClass[column.align ?? "left"]} ${column.className ?? ""}`}
                  key={`${String(column.label)}-${index}`}
                  title={column.title}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="font-data-mono text-sm text-text-primary">{children}</tbody>
        </table>
      </div>
    </div>
  );
}

/** Compact semantic badge shared by terminal tables, feeds, and status strips. */
export function ToneBadge({
  children,
  tone = "neutral",
  title,
}: {
  children: ReactNode;
  tone?: Tone;
  title?: string;
}) {
  return (
    <span
      className={`inline-flex max-w-full items-center rounded-md border px-2 py-1 font-data-mono text-[10px] uppercase leading-none ${toneBorder[tone]} ${toneSurfaceTint[tone]} ${toneText[tone]}`}
      title={title}
    >
      <span className="truncate">{children}</span>
    </span>
  );
}

/** Responsive workbench shell: stacked and page-scrollable on mobile, split on desktop. */
export function TerminalSplitShell({
  sidebar,
  children,
  className = "",
  sidebarClassName = "",
  mainClassName = "",
}: {
  sidebar: ReactNode;
  children: ReactNode;
  className?: string;
  sidebarClassName?: string;
  mainClassName?: string;
}) {
  return (
    <div
      className={`flex h-full min-h-0 flex-col overflow-y-auto bg-bg-base text-text-primary lg:flex-row lg:overflow-hidden ${className}`}
      data-terminal-split-shell="true"
    >
      <aside
        className={`flex shrink-0 flex-col border-b border-border-subtle bg-bg-surface lg:h-full lg:overflow-y-auto lg:border-b-0 lg:border-r ${sidebarClassName}`}
      >
        {sidebar}
      </aside>
      <section className={`flex min-w-0 flex-1 flex-col gap-4 p-5 lg:overflow-y-auto ${mainClassName}`}>
        {children}
      </section>
    </div>
  );
}

/** Small toolbar action matching the terminal surface contract. */
export function TerminalToolbarButton({
  children,
  className = "",
  disabled,
  onClick,
  tone = "neutral",
  title,
  type = "button",
}: {
  children: ReactNode;
  className?: string;
  disabled?: boolean;
  onClick?: () => void;
  tone?: Tone;
  title?: string;
  type?: "button" | "submit";
}) {
  return (
    <button
      className={`inline-flex min-h-8 items-center justify-center gap-2 rounded-lg border px-3 font-body-sm transition-colors hover:bg-bg-surface focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info disabled:cursor-not-allowed disabled:opacity-50 ${toneBorder[tone]} ${toneSurfaceTint[tone]} ${toneText[tone]} ${className}`}
      disabled={disabled}
      onClick={onClick}
      title={title}
      type={type}
    >
      {children}
    </button>
  );
}
