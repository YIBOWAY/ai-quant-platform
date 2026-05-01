import { Layers } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { getSymbols } from "@/lib/api";

export default async function PositionMapPage() {
  const symbols = await getSymbols();

  return (
    <div className="flex h-full flex-1 flex-col gap-4 overflow-y-auto p-container-padding">
      <ErrorBanner messages={[symbols.apiError]} />
      <header className="rounded border border-border-subtle bg-bg-surface p-4">
        <div className="flex items-center gap-2">
          <Layers size={18} className="text-primary" />
          <h1 className="font-headline-lg text-text-primary">Position Map</h1>
        </div>
        <p className="mt-2 font-body-sm text-text-secondary">
          Available local symbols from the API: {symbols.symbols.join(", ")}.
        </p>
      </header>
      <EmptyState
        title="Portfolio map not implemented"
        description="No position-map metric is shown until a real portfolio time series is selected."
      />
    </div>
  );
}
