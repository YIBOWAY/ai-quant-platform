import { z } from "zod";

import { API_BASE_URL } from "./apiClient";
import type { BriefArchiveEntry, BriefArchiveGroup } from "./briefArchive";

export type BriefRollupKind = "weekly" | "monthly";

export type BriefRollupListItem = {
  public_id: string;
  kind: BriefRollupKind;
  period_key: string;
  period_start: string;
  period_end: string;
  locale: string;
  status: string;
  title: string;
  snippet: string;
};

export type BriefRollupListResponse = {
  items: BriefRollupListItem[];
  total: number;
  kind: BriefRollupKind;
  locale: string;
  apiError?: string;
};

export type BriefRollupIssue = {
  public_id: string;
  kind: BriefRollupKind;
  period_key: string;
  period_start: string;
  period_end: string;
  locale: string;
  status: string;
};

export type BriefRollupSnapshot = {
  snapshot_id: string;
  version: number;
  payload: Record<string, unknown>;
};

export type BriefRollupEnvelope = {
  issue: BriefRollupIssue;
  snapshot: BriefRollupSnapshot;
  warnings: string[];
  apiError?: string;
};

const briefRollupSourceItemSchema = z.object({
  id: z.string(),
  title: z.string(),
  url: z.string(),
  source: z.string(),
  published_at: z.string().nullable(),
  issue_date: z.string().nullable().optional(),
});

const briefRollupTopicSchema = z.object({
  index: z.number().int(),
  title: z.string().min(1),
  synthesis: z.string(),
  source_items: z.array(briefRollupSourceItemSchema),
});

const briefRollupStatsSchema = z
  .object({
    daily_count: z.number().finite(),
    event_count: z.number().finite(),
    equity_start: z.number().finite().nullable().optional(),
    equity_end: z.number().finite().nullable().optional(),
    period_change_pct: z.number().finite().nullable().optional(),
  })
  .passthrough();

const briefRollupProvenanceSchema = z.object({
  model: z.string(),
  critic_model: z.string().nullable().optional(),
  generated_at: z.string(),
  source_issue_public_ids: z.array(z.string()),
  facts_digest: z.string().optional(),
});

const briefRollupPayloadSchema = z.object({
  schema_version: z.literal("brief_rollup_v1"),
  kind: z.enum(["weekly", "monthly"]),
  period_key: z.string().min(1),
  locale: z.enum(["en", "zh"]),
  title: z.string().min(1),
  date_range: z.object({
    start: z.string().min(1),
    end: z.string().min(1),
  }),
  main_storyline: z.string(),
  stats: briefRollupStatsSchema,
  topics: z.array(briefRollupTopicSchema),
  account_summary: z.record(z.unknown()).optional(),
  provenance: briefRollupProvenanceSchema,
  warnings: z.array(z.string()).optional(),
});

export type BriefRollupPayload = z.infer<typeof briefRollupPayloadSchema>;
export type BriefRollupTopic = z.infer<typeof briefRollupTopicSchema>;
export type BriefRollupSourceItem = z.infer<typeof briefRollupSourceItemSchema>;

export type BriefRollupView = {
  publicId: string;
  kind: BriefRollupKind;
  periodKey: string;
  periodStart: string;
  periodEnd: string;
  locale: string;
  status: string;
  title: string;
  version: number;
  warnings: string[];
  payload: BriefRollupPayload | null;
  apiError?: string;
};

export function buildBriefRollupListPath(kind: BriefRollupKind, locale: string, limit = 30) {
  const params = new URLSearchParams();
  params.set("kind", kind);
  params.set("locale", locale || "zh");
  params.set("limit", String(limit));
  return `/api/brief/rollups?${params.toString()}`;
}

export function buildBriefRollupPath(publicId: string) {
  return `/api/brief/rollups/${encodeURIComponent(publicId)}`;
}

function briefRollupKindFromPublicId(publicId: string): BriefRollupKind {
  return publicId.startsWith("brm_") ? "monthly" : "weekly";
}

async function rollupApiGet<T extends { apiError?: string }>(
  path: string,
  fallback: T,
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 60_000);
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      cache: "no-store",
      signal: controller.signal,
      headers: { accept: "application/json" },
    });
    if (!response.ok) {
      // Mirror lib/api.ts apiGet: surface the backend's structured detail
      // (e.g. {code, message}) instead of an opaque status line.
      let detailText = "";
      try {
        const payload = (await response.json()) as { detail?: unknown };
        if (typeof payload.detail === "string") {
          detailText = payload.detail;
        } else if (payload.detail && typeof payload.detail === "object") {
          const detail = payload.detail as { message?: unknown; code?: unknown };
          const message = typeof detail.message === "string" ? detail.message : "";
          const code = typeof detail.code === "string" ? `[${detail.code}] ` : "";
          detailText = message ? `${code}${message}` : JSON.stringify(payload.detail);
        }
      } catch {
        detailText = "";
      }
      if (!detailText) {
        detailText = response.statusText || `HTTP ${response.status}`;
      }
      return { ...fallback, apiError: detailText };
    }
    return (await response.json()) as T;
  } catch (error) {
    const message = error instanceof Error ? error.message : "API unavailable";
    return { ...fallback, apiError: message };
  } finally {
    clearTimeout(timeoutId);
  }
}

export function listBriefRollups(kind: BriefRollupKind, locale: string, limit = 30) {
  return rollupApiGet<BriefRollupListResponse>(buildBriefRollupListPath(kind, locale, limit), {
    items: [],
    total: 0,
    kind,
    locale: locale || "zh",
  });
}

export function getBriefRollup(publicId: string) {
  return rollupApiGet<BriefRollupEnvelope>(buildBriefRollupPath(publicId), {
    issue: {
      public_id: publicId,
      kind: briefRollupKindFromPublicId(publicId),
      period_key: "",
      period_start: "",
      period_end: "",
      locale: "",
      status: "unavailable",
    },
    snapshot: {
      snapshot_id: "",
      version: 0,
      payload: {},
    },
    warnings: ["Brief rollup is unavailable."],
  });
}

export function normalizeBriefRollupEnvelope(envelope: BriefRollupEnvelope): BriefRollupView {
  const { issue, snapshot } = envelope;
  const payloadResult = briefRollupPayloadSchema.safeParse(snapshot.payload);
  const warnings = [...envelope.warnings];
  if (!payloadResult.success && issue.status !== "unavailable") {
    warnings.push("Archived rollup snapshot does not contain a valid rollup payload.");
  }
  const payloadTitle = snapshot.payload.title;
  const title =
    typeof payloadTitle === "string" && payloadTitle.trim().length > 0
      ? payloadTitle
      : issue.public_id;
  return {
    publicId: issue.public_id,
    kind: issue.kind,
    periodKey: issue.period_key,
    periodStart: issue.period_start,
    periodEnd: issue.period_end,
    locale: issue.locale,
    status: issue.status,
    title,
    version: snapshot.version,
    warnings,
    payload: payloadResult.success ? payloadResult.data : null,
    apiError: envelope.apiError,
  };
}

/**
 * Maps rollup list items into the sidebar's archive-group shape so weekly and
 * monthly tabs reuse the same presentational view as the daily tab: weekly
 * groups by the month of period_start, monthly by year, both newest first.
 * `iso_week` / `month` carry the period keys the view's entry markers read.
 */
export function buildBriefRollupSidebarGroups(
  items: BriefRollupListItem[],
  kind: BriefRollupKind,
): BriefArchiveGroup[] {
  const sorted = [...items].sort((a, b) => b.period_start.localeCompare(a.period_start));
  const groups = new Map<string, BriefArchiveEntry[]>();
  for (const item of sorted) {
    const key = kind === "weekly" ? item.period_start.slice(0, 7) : item.period_start.slice(0, 4);
    const entry: BriefArchiveEntry = {
      public_id: item.public_id,
      issue_date: item.period_start,
      title: item.title,
      snippet: item.snippet,
      kind,
      iso_week: kind === "weekly" ? item.period_key : null,
      month: kind === "monthly" ? item.period_key : null,
    };
    const bucket = groups.get(key);
    if (bucket) {
      bucket.push(entry);
    } else {
      groups.set(key, [entry]);
    }
  }
  return Array.from(groups.entries()).map(([key, entries]) => ({ key, entries }));
}
