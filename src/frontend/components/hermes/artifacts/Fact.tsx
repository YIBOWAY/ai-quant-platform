export function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-border-subtle bg-bg-base p-3">
      <dt className="font-label-caps text-text-secondary">{label}</dt>
      <dd className="mt-1 break-words font-data-mono text-sm text-text-primary">{value}</dd>
    </div>
  );
}
