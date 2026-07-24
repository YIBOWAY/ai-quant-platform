import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import type { Locale } from "@/lib/locale";

/**
 * UI-1 Direction A chunked skeletons for the two Suspense boundaries —
 * kills the "blank → full-page dump" load pattern. Route-level loading.tsx
 * stays as the outer fallback.
 */
export function TodayOverviewSkeleton({ locale }: { locale: Locale }) {
  const copy = hermesWorkbenchCopy(locale).today.skeleton;
  return (
    <div
      aria-label={copy.overview}
      className="flex animate-pulse flex-col gap-4"
      data-hermes-today-skeleton="overview"
      role="status"
    >
      <div className="h-7 w-40 rounded-lg bg-bg-surface-muted" />
      <div className="h-4 w-72 max-w-full rounded bg-bg-surface-muted" />
      <div className="h-4 w-full max-w-lg rounded bg-bg-surface-muted" />
      <div className="h-14 rounded-lg border border-border-subtle bg-bg-surface" />
      <div className="h-14 rounded-lg border border-border-subtle bg-bg-surface" />
      <span className="sr-only">{copy.overview}</span>
    </div>
  );
}

export function TodaySecondarySkeleton({ locale }: { locale: Locale }) {
  const copy = hermesWorkbenchCopy(locale).today.skeleton;
  return (
    <div
      aria-label={copy.secondary}
      className="flex animate-pulse flex-col gap-4"
      data-hermes-today-skeleton="secondary"
      role="status"
    >
      <div className="h-4 w-32 rounded bg-bg-surface-muted" />
      <div className="h-10 rounded-lg border border-border-subtle bg-bg-surface" />
      <div className="h-10 rounded-lg border border-border-subtle bg-bg-surface" />
      <div className="h-10 rounded-lg border border-border-subtle bg-bg-surface" />
      <span className="sr-only">{copy.secondary}</span>
    </div>
  );
}
