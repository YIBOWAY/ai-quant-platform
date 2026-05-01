type LoadingSkeletonProps = {
  rows?: number;
};

export function LoadingSkeleton({ rows = 3 }: LoadingSkeletonProps) {
  return (
    <div className="space-y-3 rounded border border-border-subtle bg-bg-surface p-4">
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className="h-4 animate-pulse rounded bg-surface-muted"
          style={{ width: `${92 - index * 12}%` }}
        />
      ))}
    </div>
  );
}
