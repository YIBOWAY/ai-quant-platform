import { LoadingSkeleton } from "@/components/LoadingSkeleton";

export default function Loading() {
  return (
    <div className="space-y-4 p-4" aria-busy="true" aria-live="polite">
      <LoadingSkeleton rows={2} />
      <LoadingSkeleton rows={6} />
    </div>
  );
}
