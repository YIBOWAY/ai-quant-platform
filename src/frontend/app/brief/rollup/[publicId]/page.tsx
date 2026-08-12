import { BriefArchiveSidebar } from "@/components/brief/BriefArchiveSidebar";
import { BriefRollupDocument } from "@/components/brief/BriefRollupDocument";
import {
  getBriefRollup,
  listBriefRollups,
  normalizeBriefRollupEnvelope,
  type BriefRollupListItem,
} from "@/lib/briefRollup";

type Props = { params: Promise<{ publicId: string }> };

export default async function BriefRollupArchivePage({ params }: Props) {
  const { publicId } = await params;
  const envelope = await getBriefRollup(publicId);
  const rollup = normalizeBriefRollupEnvelope(envelope);
  const isZh = (rollup.payload?.locale ?? rollup.locale) === "zh";
  const locale = isZh ? "zh" : "en";

  // Previous/next come from the same-kind rollup list ordered by period_start;
  // when the detail read failed there is no honest neighbor set to compute.
  let previous: BriefRollupListItem | null = null;
  let next: BriefRollupListItem | null = null;
  if (!rollup.apiError) {
    const list = await listBriefRollups(rollup.kind, locale, 30);
    const siblings = [...list.items].sort((a, b) =>
      a.period_start.localeCompare(b.period_start),
    );
    const index = siblings.findIndex((item) => item.public_id === rollup.publicId);
    previous = index > 0 ? (siblings[index - 1] ?? null) : null;
    next = index >= 0 ? (siblings[index + 1] ?? null) : null;
  }

  return (
    <div className="flex h-full bg-paper-ink text-ink">
      <BriefArchiveSidebar
        activePublicId={rollup.publicId || publicId}
        locale={locale}
      />
      <main className="h-full min-w-0 flex-1 overflow-y-auto">
        <BriefRollupDocument
          locale={locale}
          next={next}
          previous={previous}
          rollup={rollup}
        />
      </main>
    </div>
  );
}
