import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { FactorRunForm } from "@/components/forms/FactorRunForm";
import { getFactors } from "@/lib/api";

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };

export default async function FactorLab() {
  const factors = await getFactors();
  const firstFactor = factors.factors[0];

  return (
    <main className="h-full overflow-y-auto p-container-padding">
      <div className="mb-4">
        <ErrorBanner messages={[factors.apiError]} />
      </div>
      <div className="flex gap-6">
      <aside className="flex w-[300px] flex-shrink-0 flex-col gap-6">
        <div className="rounded border border-border-subtle bg-bg-surface p-4">
          <h2 className="mb-4 font-headline-lg text-text-primary">Factor Definition</h2>
          <div className="flex flex-col gap-stack-gap">
            <div className="flex flex-col gap-1">
              <label className="font-label-caps text-text-secondary">AVAILABLE FACTORS</label>
              <select className="w-full rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-mono focus:border-accent-success focus:outline-none">
                {factors.factors.map((factor) => (
                  <option key={factor.factor_id} style={optionStyle}>
                    {factor.factor_id}
                  </option>
                ))}
              </select>
            </div>
            <div className="mt-2 flex flex-col gap-1">
              <label className="font-label-caps text-text-secondary">CURRENT METADATA</label>
              <pre className="rounded border border-border-subtle bg-surface-muted p-3 font-code-sm text-text-mono">
                {firstFactor
                  ? JSON.stringify(
                      {
                        factor_id: firstFactor.factor_id,
                        lookback: firstFactor.lookback,
                        direction: firstFactor.direction,
                      },
                      null,
                      2,
                    )
                  : "No factor loaded"}
              </pre>
            </div>
          </div>
        </div>

        <div className="rounded border border-border-subtle bg-bg-surface p-4">
          <h2 className="mb-4 font-headline-lg text-text-primary">Analysis Config</h2>
          <FactorRunForm />
        </div>
      </aside>

      <div className="grid flex-1 grid-cols-1 gap-4 lg:grid-cols-2">
        <EmptyState
          title="Factor values not loaded"
          description="Run factor analysis to create a real factor result file."
        />
        <EmptyState
          title="IC report unavailable"
          description="IC and Rank IC require a completed factor run."
        />
        <EmptyState
          title="Quantile returns unavailable"
          description="Grouped returns are not shown until the backend produces them."
        />
        <EmptyState
          title="Distribution unavailable"
          description="No synthetic histogram is shown; this will use real factor values."
        />
      </div>
      </div>
    </main>
  );
}
