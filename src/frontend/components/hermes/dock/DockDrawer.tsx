'use client';

import { X } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useId, type ReactNode } from "react";

import { useWorkspaceFollow } from "@/lib/hermes/workspaceFollowContext";
import type { Locale } from "@/lib/locale";

export type DockDrawerProps = {
  locale: Locale;
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
};

/**
 * Slide-over panel anchored to the left of the dock rail.
 *
 * Owns the single global `data-hermes-follow-transport` anchor (on the header
 * status line) so E2E has one place to read follow health from. Esc and the
 * scrim both close; body scroll is locked while open.
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
  const reduceMotion = useReducedMotion();
  const { state: follow } = useWorkspaceFollow();
  const cursor = follow.snapshotCursor ?? follow.cursor ?? 0;

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [open, onClose]);

  const duration = reduceMotion ? 0 : 0.18;

  return (
    <AnimatePresence>
      {open ? (
        <>
          <motion.div
            animate={{ opacity: 1 }}
            aria-hidden="true"
            className="fixed inset-0 z-30 bg-black/40"
            data-hermes-dock-scrim
            exit={{ opacity: 0 }}
            initial={{ opacity: 0 }}
            onClick={onClose}
            transition={{ duration }}
          />
          <motion.aside
            animate={{ x: 0 }}
            aria-labelledby={titleId}
            aria-modal="false"
            className="fixed bottom-0 right-[var(--spacing-dock-rail)] top-0 z-40 flex w-[var(--spacing-drawer)] max-w-[calc(100vw-var(--spacing-dock-rail))] flex-col rounded-l-[var(--radius-card)] bg-[var(--color-bg-overlay)] shadow-[var(--shadow-overlay)]"
            data-hermes-dock-drawer
            exit={{ x: "100%" }}
            initial={{ x: "100%" }}
            role="dialog"
            transition={{ duration, ease: "easeOut" }}
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
                type="button"
              >
                <X aria-hidden="true" size={18} />
              </button>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-3">
              {children}
            </div>
          </motion.aside>
        </>
      ) : null}
    </AnimatePresence>
  );
}
