import Link from "next/link";

export default function ReversalMomentumDocPage() {
  return (
    <div className="h-full overflow-y-auto bg-bg-base p-6">
      <div className="mx-auto max-w-5xl">
        <div className="mb-6 border-b border-border-subtle pb-4">
          <div className="font-label-caps text-text-secondary">Paper Replication</div>
          <h1 className="mt-2 font-headline-xl text-text-primary">
            Short-Term Reversals and Longer-Term Momentum
          </h1>
          <p className="mt-2 max-w-3xl font-body-sm text-text-secondary">
            Frontend-readable notes for the local reproduction of DOI 10.1093/rfs/hhaf057.
          </p>
        </div>

        <div className="grid gap-4">
          <section className="rounded border border-border-subtle bg-bg-surface p-4">
            <h2 className="font-label-caps text-text-primary">What The Platform Runs</h2>
            <ol className="mt-3 grid gap-2 font-body-sm text-text-secondary">
              <li>1. Pull read-only daily OHLCV data from Futu, Tiingo, or sample.</li>
              <li>2. Convert daily closes into month-end closes.</li>
              <li>3. Drop observations priced below US$1 at the prior month-end.</li>
              <li>4. Rank the prior 1-month return for short-term reversal.</li>
              <li>5. Rank the t-12 through t-2 return for longer-term momentum.</li>
              <li>6. Form default decile long-short portfolios and hold for one month.</li>
            </ol>
          </section>

          <section className="rounded border border-border-subtle bg-bg-surface p-4">
            <h2 className="font-label-caps text-text-primary">Current Scope</h2>
            <p className="mt-3 font-body-sm text-text-secondary">
              The workbench implements the core monthly portfolio construction. It does not yet reproduce the
              full global country tables, earnings-announcement tests, institutional ownership tests, or retail
              order-imbalance tests from the paper.
            </p>
          </section>

          <section className="rounded border border-border-subtle bg-bg-surface p-4">
            <h2 className="font-label-caps text-text-primary">Where To Run It</h2>
            <p className="mt-3 font-body-sm text-text-secondary">
              Use the workbench for interactive runs. Keep Futu selected for local real data; use sample only for
              stable smoke tests.
            </p>
            <Link
              className="mt-4 inline-flex rounded border border-[#00C896]/40 px-4 py-2 font-body-sm font-semibold text-[#00C896] hover:bg-[#00C896]/10"
              href="/replications"
            >
              Open workbench
            </Link>
          </section>

          <section className="rounded border border-border-subtle bg-bg-surface p-4">
            <h2 className="font-label-caps text-text-primary">Repository Doc</h2>
            <p className="mt-3 font-data-mono text-text-secondary">
              docs/replications/reversal_momentum_replication.md
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
