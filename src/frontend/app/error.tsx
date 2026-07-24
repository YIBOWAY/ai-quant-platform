'use client';

import { TerminalToolbarButton } from "@/components/ui/primitives";

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
      <TerminalToolbarButton
        onClick={() => reset()}
        tone="info"
      >
        重试 / Retry
      </TerminalToolbarButton>
    </div>
  );
}
