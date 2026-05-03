import { DataPreviewTable } from "@/components/DataPreviewTable";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { FactorRunForm } from "@/components/forms/FactorRunForm";
import { getFactorRunDetail, getFactorRuns, getFactors } from "@/lib/api";

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };

export default async function FactorLab() {
  const [factors, factorRuns] = await Promise.all([getFactors(), getFactorRuns()]);
  const latestRun = factorRuns.runs[0];
  const latestDetail = latestRun ? await getFactorRunDetail(latestRun.id) : null;
  const firstFactor = factors.factors[0];

  return (
    <main className="h-full overflow-y-auto p-container-padding">
      <div className="mb-4">
        <ErrorBanner
          messages={[factors.apiError, factorRuns.apiError, latestDetail?.apiError]}
        />
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
              <div className="mt-2 flex flex-col gap-1">
                <label className="font-label-caps text-text-secondary">LATEST RUN</label>
                <div className="rounded border border-border-subtle bg-surface-muted p-3 font-data-mono text-xs text-text-primary">
                  <div className="truncate">{latestRun?.id ?? "No factor run yet"}</div>
                  {latestRun?.source ? (
                    <div className="mt-2">
                      <DataSourceBadge source={latestRun.source} />
                    </div>
                  ) : null}
                  <div className="mt-2 text-text-secondary">
                    rows={latestRun?.row_count ?? 0} signals={latestRun?.signal_count ?? 0}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="rounded border border-border-subtle bg-bg-surface p-4">
            <h2 className="mb-4 font-headline-lg text-text-primary">Analysis Config</h2>
            <FactorRunForm />
          </div>
        </aside>

        <div className="grid flex-1 grid-cols-1 gap-4 lg:grid-cols-2">
          <DataPreviewTable
            title="Factor Values"
            description="Latest factor result rows from the API run."
            rows={latestDetail?.factor_results ?? []}
            emptyTitle="Factor values not loaded"
            emptyDescription="Run factor analysis to create a real factor result file."
            columns={["factor_id", "symbol", "signal_ts", "tradeable_ts", "value"]}
          />
          <DataPreviewTable
            title="Signal Scores"
            description="Latest combined score rows prepared for later strategy use."
            rows={latestDetail?.signals ?? []}
            emptyTitle="Signals unavailable"
            emptyDescription="Signals appear after a factor run completes."
            columns={["symbol", "signal_ts", "tradeable_ts", "score"]}
          />
          <DataPreviewTable
            title="IC Report"
            description="Information coefficient rows from the latest run."
            rows={latestDetail?.information_coefficients ?? []}
            emptyTitle="IC report unavailable"
            emptyDescription="IC and Rank IC require a completed factor run."
          />
          <DataPreviewTable
            title="Quantile Returns"
            description="Grouped return rows from the latest run."
            rows={latestDetail?.quantile_returns ?? []}
            emptyTitle="Quantile returns unavailable"
            emptyDescription="Grouped returns are not shown until the backend produces them."
          />
          {!latestRun ? (
            <div className="lg:col-span-2">
              <EmptyState
                title="No factor runs yet"
                description="Use the form on the left to generate the first factor research result."
              />
            </div>
          ) : null}
        </div>
      </div>
    </main>
  );
}
