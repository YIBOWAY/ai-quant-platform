import { CircleDashed } from "lucide-react";

type EmptyStateProps = {
  title: string;
  description: string;
  action?: React.ReactNode;
};

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="flex min-h-32 flex-col items-center justify-center gap-3 rounded border border-dashed border-border-subtle bg-bg-surface/70 p-6 text-center">
      <CircleDashed size={22} className="text-text-secondary" />
      <div>
        <h3 className="font-body-sm font-semibold text-text-primary">{title}</h3>
        <p className="mt-1 max-w-md font-body-sm text-text-secondary">{description}</p>
      </div>
      {action}
    </div>
  );
}
