/**
 * L5c-Workbench-A11y-M1 contracts for the local-dark Hermes workbench shell.
 * FE-only; no mutation routes. Breakpoints match hermes-workbench-visual matrix.
 */

export const WORKBENCH_A11Y_MARKER = "l5c-m1" as const;

/** Architect-named viewport matrix (width px). */
export const WORKBENCH_A11Y_BREAKPOINTS = [
  { name: "wide", width: 1440 },
  { name: "desktop", width: 1280 },
  { name: "tablet", width: 768 },
  { name: "mobile", width: 390 },
] as const;

export type WorkbenchA11yBreakpoint =
  (typeof WORKBENCH_A11Y_BREAKPOINTS)[number]["name"];

/** Shared class for long mono IDs: wrap, never force horizontal page scroll. */
export const LONG_ID_CLASS =
  "min-w-0 max-w-full break-all font-data-mono text-[11px] text-text-secondary";

/**
 * Middle-ellipsis for long authority/command ids while keeping head+tail.
 * Short values pass through unchanged.
 */
export function displayId(
  value: string | null | undefined,
  options: { head?: number; tail?: number; max?: number } = {},
): string {
  if (!value) return "";
  const s = value.trim();
  const head = options.head ?? 10;
  const tail = options.tail ?? 6;
  const max = Math.max(options.max ?? head + tail + 1, head + tail + 1);
  if (s.length <= max) return s;
  return `${s.slice(0, head)}…${s.slice(-tail)}`;
}

/** Collapsible panel toggle: 44px target + visible focus (globals also apply). */
export const COLLAPSE_TOGGLE_CLASS =
  "app-touch-target rounded border border-border-subtle px-2 py-0.5 font-body-sm text-text-primary hover:bg-bg-surface focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info";

/** Content column padding that stays usable at 390px and roomy at 1440. */
export const WORKBENCH_CONTENT_PAD_CLASS =
  "mx-auto flex w-full max-w-[var(--spacing-hermes-content-max)] flex-col gap-3 p-3 sm:gap-4 sm:p-4 lg:gap-4 lg:p-6";
