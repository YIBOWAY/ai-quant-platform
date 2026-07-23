import type { BriefArchivePayload, BriefSourceWatermark } from "./briefArchive";

export type BriefAiNewsDigestItem = {
  id: string;
  title: string;
  url: string;
  source: string;
  published_at?: string | null;
  summary?: string | null;
  category?: string | null;
  score?: number | null;
};

export type BriefAiNewsDigestInput = {
  apiError?: string;
  provider?: string;
  served_from?: string | null;
  fetched_at?: string | null;
  warnings?: string[];
  items: BriefAiNewsDigestItem[];
};

export type BriefAiNewsSourceEntry = BriefSourceWatermark["sources"][number];

function isoTimestamp(value: string | null | undefined): string | null {
  if (!value?.trim()) {
    return null;
  }
  const ms = Date.parse(value);
  if (!Number.isFinite(ms)) {
    return null;
  }
  return new Date(ms).toISOString();
}

function nullableNumber(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function sourceStatus(
  apiError: string | undefined,
  stale = false,
): BriefAiNewsSourceEntry["status"] {
  if (apiError) {
    return "unavailable";
  }
  return stale ? "stale" : "available";
}

/** Map news facade digest into brief archive ai_news rows. Empty on error. */
export function mapDigestToBriefAiNews(
  digest: BriefAiNewsDigestInput,
): BriefArchivePayload["ai_news"] {
  if (digest.apiError || digest.items.length === 0) {
    return [];
  }

  return digest.items
    .filter(
      (item) =>
        item.id.trim().length > 0 &&
        item.title.trim().length > 0 &&
        item.url.trim().length > 0 &&
        item.source.trim().length > 0,
    )
    .slice(0, 6)
    .map((item) => ({
      id: item.id,
      title: item.title,
      url: item.url,
      source: item.source,
      published_at: isoTimestamp(item.published_at),
      summary: item.summary ?? null,
      category: item.category ?? null,
      score: nullableNumber(item.score ?? undefined),
    }));
}

/** Build ai_news source watermark with auto-facade provider / served_from metadata. */
export function mapDigestToAiNewsSourceEntry(
  digest: BriefAiNewsDigestInput,
): BriefAiNewsSourceEntry {
  const warnings = digest.warnings ?? [];
  const shortWarnings = warnings
    .map((warning) => warning.trim())
    .filter(Boolean)
    .slice(0, 2)
    .join("; ");
  const provider = digest.provider?.trim() || "unknown";
  const servedFrom = digest.served_from?.trim() || "primary";
  const baseDetail = digest.apiError ?? `${provider}/${servedFrom}`;
  const detail =
    !digest.apiError && shortWarnings ? `${baseDetail}; ${shortWarnings}` : baseDetail;

  return {
    name: "ai_news",
    status: sourceStatus(
      digest.apiError,
      warnings.some((warning) => /cache|stale/i.test(warning)),
    ),
    as_of: isoTimestamp(digest.fetched_at),
    provider,
    served_from: digest.served_from?.trim() || servedFrom,
    detail,
  };
}

export function buildBriefAiNewsDigest(digest: BriefAiNewsDigestInput) {
  return {
    items: mapDigestToBriefAiNews(digest),
    source: mapDigestToAiNewsSourceEntry(digest),
  };
}
