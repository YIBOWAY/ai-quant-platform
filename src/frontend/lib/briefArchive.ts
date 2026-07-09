export type BriefSafetyFooter = {
  dry_run: boolean;
  paper_trading: boolean;
  live_trading_enabled: boolean;
  kill_switch: boolean;
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

export function normalizeBriefIssueEnvelope(envelope: BriefIssueEnvelope): BriefIssueArchiveView {
  const payloadTitle = envelope.snapshot.payload.title;
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
    warnings: envelope.warnings,
    sourceWatermarkEntries: Object.entries(envelope.snapshot.source_watermark).map(([key, value]) => [
      key,
      formatWatermarkValue(value),
    ]),
    apiError: envelope.apiError,
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
