import { getBriefIssue } from "@/lib/api";
import { normalizeBriefIssueEnvelope } from "@/lib/briefArchive";

type Props = { params: Promise<{ publicId: string }> };

export default async function BriefIssueArchivePage({ params }: Props) {
  const { publicId } = await params;
  const envelope = await getBriefIssue(publicId);
  const { issue, snapshot } = envelope;
  const archive = normalizeBriefIssueEnvelope(envelope);
  const title =
    typeof snapshot.payload.title === "string" && snapshot.payload.title.trim().length > 0
      ? snapshot.payload.title
      : archive.title;

  return (
    <main className="h-full overflow-y-auto bg-paper-ink text-ink">
      <article className="mx-auto flex min-h-full max-w-editorial-column flex-col gap-8 px-5 py-8 md:px-10 lg:px-14">
        <header className="border-b border-editorial-rule pb-6">
          <p className="font-editorial-caps text-ink-secondary">Brief Archive</p>
          <h1 className="mt-3 max-w-4xl font-editorial-display text-ink">{title}</h1>
          <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <MetaItem label="Issue Date" value={issue.issue_date || "--"} />
            <MetaItem label="Version" value={`v${archive.version}`} />
            <MetaItem label="Status" value={archive.status || "--"} />
            <MetaItem label="Public ID" value={archive.publicId || publicId} />
          </div>
        </header>

        {archive.apiError ? (
          <section className="border border-danger/40 bg-danger/10 p-4 text-danger">
            <h2 className="font-label-caps uppercase">Archive Error</h2>
            <p className="mt-2 font-body-sm">{archive.apiError}</p>
          </section>
        ) : null}

        <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="border border-editorial-rule bg-paper-surface p-5">
            <h2 className="font-label-caps uppercase text-ink-secondary">Snapshot</h2>
            <dl className="mt-4 grid gap-3 sm:grid-cols-2">
              <MetaItem label="Snapshot ID" value={snapshot.snapshot_id || "--"} />
              <MetaItem label="Locale" value={archive.locale || "--"} />
            </dl>
          </div>

          <aside className="border border-editorial-rule bg-paper-surface p-5">
            <h2 className="font-label-caps uppercase text-ink-secondary">Warnings</h2>
            {archive.warnings.length ? (
              <ul className="mt-4 space-y-2 font-body-sm text-ink">
                {archive.warnings.map((warning) => (
                  <li key={warning} className="border-l border-warning pl-3">
                    {warning}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-4 font-body-sm text-ink-secondary">None</p>
            )}
          </aside>
        </section>

        <section className="border-t border-editorial-rule pt-5">
          <h2 className="font-label-caps uppercase text-ink-secondary">Source Watermark</h2>
          {archive.sourceWatermarkEntries.length ? (
            <dl className="mt-4 grid gap-3 md:grid-cols-2">
              {archive.sourceWatermarkEntries.map(([key, value]) => (
                <MetaItem key={key} label={key} value={value} />
              ))}
            </dl>
          ) : (
            <p className="mt-4 font-body-sm text-ink-secondary">None</p>
          )}
        </section>
      </article>
    </main>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 border border-editorial-rule bg-paper-surface-muted p-3">
      <p className="font-label-caps uppercase text-ink-secondary">{label}</p>
      <p className="mt-1 break-words font-data-mono text-ink">{value}</p>
    </div>
  );
}
