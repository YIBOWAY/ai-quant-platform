import { z } from "zod";

export type BriefSafetyFooter = {
  dry_run: boolean;
  paper_trading: boolean;
  live_trading_enabled: boolean;
  kill_switch: boolean;
  paper_observation_enabled: boolean;
  bind_address: string;
};

export type BriefIssue = {
  issue_id: string;
  public_id: string;
  issue_date: string;
  locale: string;
  status: string;
};

export type BriefSnapshot = {
  snapshot_id: string;
  version: number;
  payload: Record<string, unknown>;
  source_watermark: Record<string, unknown>;
};

export type BriefIssueEnvelope = {
  issue: BriefIssue;
  snapshot: BriefSnapshot;
  warnings: string[];
  safety?: BriefSafetyFooter;
  apiError?: string;
};

export type BriefIssueArchiveView = {
  publicId: string;
  issueDate: string;
  locale: string;
  status: string;
  title: string;
  version: number;
  warnings: string[];
  payload: BriefArchivePayload | null;
  sourceWatermark: BriefSourceWatermark | null;
  sourceWatermarkEntries: Array<[string, string]>;
  apiError?: string;
};

export function buildBriefIssuePath(publicId: string) {
  return `/api/brief/issues/${encodeURIComponent(publicId)}`;
}

export function buildLatestBriefIssuePath(locale: string) {
  const params = new URLSearchParams();
  params.set("locale", locale || "zh");
  return `/api/brief/issues/latest?${params.toString()}`;
}

export function buildBriefIssueListPath(locale: string, limit = 30, offset = 0) {
  const params = new URLSearchParams();
  params.set("locale", locale || "zh");
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  return `/api/brief/issues?${params.toString()}`;
}

export type BriefIssueListResponse = {
  items: BriefIssue[];
  total: number;
  limit: number;
  offset: number;
  apiError?: string;
};

export type BriefArchiveEntryKind = "daily" | "weekly" | "monthly";

export type BriefArchiveEntry = {
  public_id: string;
  issue_date: string;
  title: string;
  snippet: string;
  kind: BriefArchiveEntryKind;
  iso_week: string | null;
  month: string | null;
};

export type BriefArchiveGroup = {
  key: string;
  entries: BriefArchiveEntry[];
};

export type BriefArchiveViewResponse = {
  locale: string;
  months: number;
  daily: BriefArchiveGroup[];
  weekly: BriefArchiveGroup[];
  monthly: BriefArchiveGroup[];
};

export function buildBriefArchivePath(locale: string, months = 3) {
  const params = new URLSearchParams();
  params.set("locale", locale || "zh");
  params.set("months", String(months));
  return `/api/brief/archive?${params.toString()}`;
}

export function normalizeBriefIssueEnvelope(envelope: BriefIssueEnvelope): BriefIssueArchiveView {
  const payloadTitle = envelope.snapshot.payload.title;
  const payloadResult = briefArchivePayloadSchema.safeParse(envelope.snapshot.payload);
  const watermarkResult = briefSourceWatermarkSchema.safeParse(
    envelope.snapshot.source_watermark,
  );
  const warnings = [...envelope.warnings];
  if (!payloadResult.success && envelope.issue.status !== "unavailable") {
    warnings.push("Archived snapshot does not contain a valid factual payload.");
  }
  const title =
    typeof payloadTitle === "string" && payloadTitle.trim().length > 0
      ? payloadTitle
      : envelope.issue.public_id;

  return {
    publicId: envelope.issue.public_id,
    issueDate: envelope.issue.issue_date,
    locale: envelope.issue.locale,
    status: envelope.issue.status,
    title,
    version: envelope.snapshot.version,
    warnings,
    payload: payloadResult.success ? payloadResult.data : null,
    sourceWatermark: watermarkResult.success ? watermarkResult.data : null,
    sourceWatermarkEntries: Object.entries(envelope.snapshot.source_watermark).map(([key, value]) => [
      key,
      formatWatermarkValue(value),
    ]),
    apiError: envelope.apiError,
  };
}

export function buildBriefGenerateRequest(
  payload: BriefArchivePayload,
  sourceWatermark: BriefSourceWatermark,
) {
  return {
    issue_date: payload.issue_date,
    locale: payload.locale,
    payload,
    source_watermark: sourceWatermark,
  };
}

function formatWatermarkValue(value: unknown) {
  if (value === null || value === undefined) {
    return "--";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

const nullableTimestamp = z.string().min(1).nullable();

const briefArchivePayloadSchema = z
  .object({
    schema_version: z.literal("brief_snapshot_v1"),
    title: z.string().min(1),
    issue_date: z.string().min(1),
    locale: z.enum(["en", "zh"]),
    generated_at: z.string().min(1),
    lede: z.string().min(1),
    account: z
      .object({
        account_id: z.string().min(1),
        base_currency: z.string().min(1),
        equity: z.number().finite(),
        cash: z.number().finite(),
        pnl_abs: z.number().finite(),
        pnl_pct: z.number().finite(),
        invested_pct: z.number().finite(),
        price_source: z
          .object({ kind: z.string().min(1), as_of: nullableTimestamp })
          .strict(),
        positions: z.array(
          z
            .object({
              symbol: z.string().min(1),
              quantity: z.number().finite(),
              avg_cost: z.number().finite(),
              last_price: z.number().finite(),
              market_value: z.number().finite(),
              weight: z.number().finite(),
              unrealized_pnl: z.number().finite(),
              price_kind: z.string().min(1),
              price_as_of: nullableTimestamp,
              previous_close: z.number().finite().nullable().optional(),
              day_change_ratio: z.number().finite().nullable().optional(),
              day_change_source: z.string().min(1).nullable().optional(),
              day_change_as_of: nullableTimestamp.optional(),
            })
            .strict(),
        ),
      })
      .strict(),
    paper_equity: z.array(
      z
        .object({
          timestamp: z.string().min(1),
          equity: z.number().finite(),
          cash: z.number().finite(),
          market_value: z.number().finite(),
          source: z.string().min(1),
        })
        .strict(),
    ),
    markets: z.array(
      z
        .object({
          symbol: z.string().min(1),
          last: z.number().finite().nullable(),
          change_pct: z.number().finite().nullable(),
          source: z.string().nullable(),
          as_of: nullableTimestamp,
        })
        .strict(),
    ),
    market_note: z.string().min(1),
    asia_radar_note: z.string().min(1).optional(),
    asia_radar: z
      .object({
        status: z.enum(["available", "unavailable"]),
        provider: z.literal("futu"),
        as_of: z.string().min(1).nullable(),
        timezone: z.string().min(1).nullable(),
        provenance: z.enum(["futu", "futu_cache"]).nullable(),
        market_count: z.number().int().nonnegative(),
        winner_symbols: z.array(z.string()),
        laggard_symbols: z.array(z.string()),
        spread_pct: z.number().finite().nullable(),
        top_ytd_symbol: z.string().nullable(),
        top_ytd_pct: z.number().finite().nullable(),
        bottom_ytd_symbol: z.string().nullable(),
        bottom_ytd_pct: z.number().finite().nullable(),
      })
      .strict()
      .nullable()
      .optional(),
    ai_news: z.array(
      z
        .object({
          id: z.string().min(1),
          title: z.string().min(1),
          url: z.string().min(1),
          source: z.string().min(1),
          published_at: nullableTimestamp,
          summary: z.string().nullable(),
          category: z.string().nullable(),
          score: z.number().finite().nullable(),
        })
        .strict(),
    ),
    hermes_log: z.array(
      z
        .object({
          timestamp: nullableTimestamp,
          status: z.enum(["ok", "warn"]),
          text: z.string().min(1),
          href: z.string().nullable(),
          summary: z.string().nullable(),
        })
        .strict(),
    ),
    warnings: z.array(z.string()),
    performance: z
      .object({
        selected_range: z.enum(["7d", "1m", "3m"]),
        master_range: z.literal("3m"),
        granularity: z.literal("1d"),
        benchmarks: z.array(z.enum(["SPY", "QQQ"])),
        requested_start: z.string().min(1),
        requested_end: z.string().min(1),
        actual_start: z.string().min(1).nullable(),
        actual_end: z.string().min(1).nullable(),
        coverage_complete: z.boolean(),
        series: z.array(
          z
            .object({
              id: z.string().min(1),
              kind: z.enum(["paper", "benchmark"]),
              label: z.string().min(1),
              symbol: z.string().min(1).nullable(),
              status: z.enum(["available", "partial", "unavailable"]),
              source: z.string().min(1).nullable(),
              as_of: nullableTimestamp,
              error_code: z.string().min(1).nullable(),
              points: z.array(
                z
                  .object({
                    date: z.string().min(1),
                    return_ratio: z.number().finite(),
                    equity: z.number().finite().nullable(),
                    close: z.number().finite().nullable(),
                  })
                  .strict(),
              ),
            })
            .strict(),
        ),
        warnings: z.array(z.string()),
      })
      .strict()
      .nullable()
      .optional(),
  })
  .strict();

const briefSourceWatermarkSchema = z
  .object({
    captured_at: z.string().min(1),
    sources: z.array(
      z
        .object({
          name: z.string().min(1),
          status: z.enum(["available", "stale", "unavailable"]),
          as_of: nullableTimestamp,
          detail: z.string().nullable(),
          /** News facade provider id (e.g. aihot / longbridge); optional for legacy rows. */
          provider: z.string().min(1).nullable().optional(),
          /** Where the facade served from (primary / failover / cache). */
          served_from: z.string().min(1).nullable().optional(),
        })
        .passthrough(),
    ),
  })
  .strict();

export type BriefArchivePayload = z.infer<typeof briefArchivePayloadSchema>;
export type BriefSourceWatermark = z.infer<typeof briefSourceWatermarkSchema>;
