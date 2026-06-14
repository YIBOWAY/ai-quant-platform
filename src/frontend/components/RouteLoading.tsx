/**
 * Shared route-level loading fallback. Uses h-full (the layout's <main> is a
 * fixed-height box) — h-screen here would overflow the 100px chrome offset and
 * clip, off-centering the spinner.
 */
export function RouteLoading({ label }: { label?: string }) {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="text-center">
        <div
          aria-label={label ?? "Loading"}
          className="mb-4 inline-block h-10 w-10 animate-spin rounded-full border-4 border-accent-success border-t-transparent"
          role="status"
        />
        {label ? <div className="font-body-sm text-text-secondary">{label}</div> : null}
      </div>
    </div>
  );
}
