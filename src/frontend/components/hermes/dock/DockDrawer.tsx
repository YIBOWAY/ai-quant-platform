'use client';

import { X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { useWorkspaceFollow } from "@/lib/hermes/workspaceFollowContext";
import type { Locale } from "@/lib/locale";

export type DockDrawerProps = {
  locale: Locale;
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
};

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

/**
 * Local reduced-motion probe. `useReducedMotion` from motion/react logs a dev
 * warning whenever the preference is on, which pollutes the E2E console gate
 * (Playwright forces reduced motion), so subscribe to the media query directly.
 */
function usePrefersReducedMotion(): boolean {
  const subscribe = useCallback((onChange: () => void) => {
    const query = window.matchMedia(REDUCED_MOTION_QUERY);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(REDUCED_MOTION_QUERY).matches,
    () => false,
  );
}

/**
 * Slide-over panel anchored to the left of the dock rail.
 *
 * Modal: scrim + scroll lock + `aria-modal`, focus moves to the close button on
 * open, Tab cycles within the drawer, and focus returns to the invoking element
 * on close. Owns the single global `data-hermes-follow-transport` anchor (on the
 * header status line) so E2E has one place to read follow health from.
 */
export function DockDrawer({
  locale,
  open,
  onClose,
  title,
  children,
}: DockDrawerProps) {
  const isZh = locale === "zh";
  const titleId = useId();
  const reduceMotion = usePrefersReducedMotion();
  const { state: follow } = useWorkspaceFollow();
  const cursor = follow.snapshotCursor ?? follow.cursor ?? 0;
  const drawerRef = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;

    restoreFocusRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    closeButtonRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const drawer = drawerRef.current;
      if (!drawer) return;
      const focusable = Array.from(
        drawer.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      ).filter((el) => el.offsetParent !== null || el === document.activeElement);
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (event.shiftKey) {
        if (active === first || !drawer.contains(active)) {
          event.preventDefault();
          last.focus();
        }
      } else if (active === last || !drawer.contains(active)) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      restoreFocusRef.current?.focus();
      restoreFocusRef.current = null;
    };
  }, [open, onClose]);

  // Under reduced motion the animated variants are all no-ops, and mounting
  // them makes the motion runtime log a reduced-motion warning on every open.
  // Render the plain elements instead so the console stays clean.
  const duration = 0.18;
  const Scrim = reduceMotion ? "div" : motion.div;
  const Panel = reduceMotion ? "aside" : motion.aside;
  const scrimMotion = reduceMotion
    ? {}
    : {
        animate: { opacity: 1 },
        exit: { opacity: 0 },
        initial: { opacity: 0 },
        transition: { duration },
      };
  const panelMotion = reduceMotion
    ? {}
    : {
        animate: { x: 0 },
        exit: { x: "100%" },
        initial: { x: "100%" },
        transition: { duration, ease: "easeOut" as const },
      };

  return (
    <AnimatePresence>
      {open ? (
        <>
          <Scrim
            aria-hidden="true"
            className="fixed inset-0 z-30 bg-black/40"
            data-hermes-dock-scrim
            onClick={onClose}
            {...scrimMotion}
          />
          <Panel
            aria-labelledby={titleId}
            aria-modal="true"
            className="fixed bottom-0 right-[var(--spacing-dock-rail)] top-0 z-40 flex w-[var(--spacing-drawer)] max-w-[calc(100vw-var(--spacing-dock-rail))] flex-col rounded-l-[var(--radius-card)] bg-[var(--color-bg-overlay)] shadow-[var(--shadow-overlay)]"
            data-hermes-dock-drawer
            ref={drawerRef}
            role="dialog"
            {...panelMotion}
          >
            <header className="flex items-center gap-2 border-b border-border-subtle px-3 py-2">
              <h2
                className="min-w-0 flex-1 truncate font-headline-sm text-text-primary"
                id={titleId}
              >
                {title}
              </h2>
              <p
                className="shrink-0 font-data-mono text-[11px] text-text-secondary"
                data-hermes-follow-transport={follow.transport}
                data-hermes-follow-cursor={cursor}
              >
                {follow.transport} · #{cursor}
              </p>
              <button
                aria-label={isZh ? "关闭面板" : "Close panel"}
                className="app-touch-target flex shrink-0 items-center justify-center rounded-[8px] text-text-secondary transition-colors hover:bg-bg-surface-muted hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info motion-reduce:transition-none"
                data-hermes-dock-close
                onClick={onClose}
                ref={closeButtonRef}
                type="button"
              >
                <X aria-hidden="true" size={18} />
              </button>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-3">
              {children}
            </div>
          </Panel>
        </>
      ) : null}
    </AnimatePresence>
  );
}
