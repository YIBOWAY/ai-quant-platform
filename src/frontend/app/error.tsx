'use client';

/**
 * Global error boundary. Without this file, any client-side render error
 * (e.g. a charting library assertion) unmounts the entire app into a blank
 * page. Keep it dependency-free and bilingual.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex h-full min-h-[60vh] flex-col items-center justify-center gap-4 p-8 text-center">
      <p className="font-label-caps uppercase text-danger">Runtime error · 页面渲染出错</p>
      <p className="max-w-xl break-all font-data-mono text-xs text-text-secondary">
        {error.message || "Unknown error"}
      </p>
      <button
        className="rounded-lg border border-accent-success/40 bg-accent-success/10 px-4 py-2 font-body-sm text-accent-success transition-colors hover:bg-accent-success/20"
        onClick={() => reset()}
        type="button"
      >
        重试 / Retry
      </button>
    </div>
  );
}
