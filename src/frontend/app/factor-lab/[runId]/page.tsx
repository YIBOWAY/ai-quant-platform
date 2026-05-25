import Link from "next/link";
import { DataPreviewTable } from "@/components/DataPreviewTable";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { ErrorBanner } from "@/components/ErrorBanner";
import { getFactorRunDetail } from "@/lib/api";

type FactorRunDetailPageProps = {
  params?: Promise<{ runId?: string }>;
};

export default async function FactorRunDetailPage({ params }: FactorRunDetailPageProps) {
  const runId = (await params)?.runId ?? "";
  const detail = await getFactorRunDetail(runId);
  const metadata = detail.metadata ?? {};
  const source = typeof metadata.source === "string" ? metadata.source : undefined;

  return (
    <main className="h-full overflow-y-auto bg-bg-base p-5">
      <ErrorBanner messages={[detail.apiError]} />
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4 border-b border-border-subtle pb-4">
        <div>
          <p className="font-label-caps uppercase text-text-secondary">Factor Lab</p>
          <h1 className="mt-1 font-headline-xl text-text-primary">Factor Run Detail</h1>
          <p className="mt-1 font-data-mono text-text-secondary">{runId}</p>
          {source ? (
            <div className="mt-3">
              <DataSourceBadge source={source} />
            </div>
          ) : null}
        </div>
        <Link className="rounded border border-border-subtle px-3 py-2 font-body-sm text-text-primary" href="/factor-lab">
          Back to Factor Lab
        </Link>
      </header>

      <section className="mb-4 grid gap-3 md:grid-cols-3">
        <Metric label="Rows" value={String(metadata.row_count ?? detail.factor_results.length)} />
        <Metric label="Signals" value={String(metadata.signal_count ?? detail.signals.length)} />
        <Metric label="IC Rows" value={String(detail.information_coefficients.length)} />
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <DataPreviewTable
          columns={["factor_id", "symbol", "signal_ts", "tradeable_ts", "value"]}
          description="Factor value rows saved by this run."
          emptyDescription="No factor result rows were saved for this run."
          emptyTitle="Factor Values"
          rows={detail.factor_results}
          title="Factor Values"
        />
        <DataPreviewTable
          columns={["symbol", "signal_ts", "tradeable_ts", "score"]}
          description="Signal score rows saved by this run."
          emptyDescription="No signal rows were saved for this run."
          emptyTitle="Signal Scores"
          rows={detail.signals}
          title="Signal Scores"
        />
        <DataPreviewTable
          description="Information coefficient rows saved by this run."
          emptyDescription="No IC rows were saved for this run."
          emptyTitle="IC Report"
          rows={detail.information_coefficients}
          title="IC Report"
        />
        <DataPreviewTable
          description="Quantile return rows saved by this run."
          emptyDescription="No quantile return rows were saved for this run."
          emptyTitle="Quantile Returns"
          rows={detail.quantile_returns}
          title="Quantile Returns"
        />
        <div className="lg:col-span-2">
          <DataPreviewTable
            description="Run request and saved output paths."
            emptyDescription="Metadata is empty for this run."
            emptyTitle="Metadata unavailable"
            rows={objectRows(metadata)}
            title="Metadata"
          />
        </div>
      </section>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border-subtle bg-bg-surface p-3">
      <div className="font-label-caps text-text-secondary">{label}</div>
      <div className="mt-2 font-data-mono text-lg font-bold text-text-primary">{value}</div>
    </div>
  );
}

function objectRows(value: unknown) {
  if (typeof value !== "object" || value === null) {
    return [];
  }
  return Object.entries(value as Record<string, unknown>).map(([key, item]) => ({
    key,
    value: typeof item === "object" && item !== null ? JSON.stringify(item) : item,
  }));
}
