import { apiRequest } from "./apiClient";
import { ensureOwnerSession, ownerPostJson } from "./hermes/workspaceClient";
import type { CompanyResearchResponse, CompanyResearchCompareResponse } from "./api.generated";

export type CompanyResearch = CompanyResearchResponse;
export type ResearchSection = NonNullable<CompanyResearch["sections"]>[number];
export type ResearchObject = Record<string, unknown>;
export type DataSources = {
  status: string;
  checked_at?: string | null;
  symbol?: string | null;
  sources?: ResearchObject[];
  checks?: ResearchObject[];
  error?: string | null;
  [key: string]: unknown;
};

export function researchObject(value: unknown): ResearchObject {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as ResearchObject : {};
}
export function researchRows(value: unknown): ResearchObject[] {
  return Array.isArray(value) ? value.filter((row): row is ResearchObject =>
    row !== null && typeof row === "object" && !Array.isArray(row)) : [];
}
export function researchText(value: unknown, fallback = "—"): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}
export function researchNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string" || !value.trim() || value === "-") return null;
  const number = Number(value.replace(/,/g, ""));
  return Number.isFinite(number) ? number : null;
}
export function researchStrings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}
export function safeResearchUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch { return null; }
}
export function normalizeResearchSymbol(value: string): string {
  const symbol = value.trim().toUpperCase();
  if (!/^[A-Z0-9][A-Z0-9.^_-]{0,31}$/.test(symbol)) {
    throw new Error("请输入有效股票代码，例如 NVDA、AAPL.US 或 700.HK / Enter a valid symbol.");
  }
  return symbol;
}
export function getCompanyResearch(symbol: string, signal?: AbortSignal) {
  const path = `/api/company-research?symbol=${encodeURIComponent(normalizeResearchSymbol(symbol))}`;
  return signal ? apiRequest<CompanyResearch>(path, { signal }) : apiRequest<CompanyResearch>(path);
}
export async function refreshCompanyResearch(symbol: string, signal?: AbortSignal) {
  const normalized = normalizeResearchSymbol(symbol);
  await ensureOwnerSession(signal);
  signal?.throwIfAborted();
  return ownerPostJson<CompanyResearch>("/api/company-research/refresh", { symbol: normalized }, signal);
}
export function compareCompanyResearch(symbols: string[], signal?: AbortSignal) {
  const values = [...new Set(symbols.filter(value => value.trim()).map(normalizeResearchSymbol))];
  if (values.length < 1 || values.length > 4) throw new Error("请提供 1–4 个股票代码 / Use 1–4 symbols.");
  const path = `/api/company-research/compare?symbols=${encodeURIComponent(values.join(","))}`;
  return signal ? apiRequest<CompanyResearchCompareResponse>(path, { signal }) : apiRequest<CompanyResearchCompareResponse>(path);
}
export function getDataSources(signal?: AbortSignal) {
  return signal ? apiRequest<DataSources>("/api/data-sources", { signal }) : apiRequest<DataSources>("/api/data-sources");
}
export async function checkDataSources(symbol: string, signal?: AbortSignal) {
  const normalized = normalizeResearchSymbol(symbol);
  await ensureOwnerSession(signal);
  signal?.throwIfAborted();
  return ownerPostJson<DataSources>("/api/data-sources/check", { symbol: normalized }, signal);
}

function waitForNextRead(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    signal.throwIfAborted();
    const onAbort = () => { clearTimeout(timer); reject(signal.reason); };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

/** Observe saved state only while an explicit backend job is updating. Never starts a job. */
export async function observeResearchUpdate<T extends { status: string }>(
  initial: T,
  read: (signal: AbortSignal) => Promise<T>,
  publish: (value: T) => void,
  signal: AbortSignal,
  options: { intervalMs?: number; maxPolls?: number; timeoutMs?: number } = {},
): Promise<void> {
  const controller = new AbortController();
  const relayAbort = () => controller.abort(signal.reason);
  if (signal.aborted) relayAbort();
  else signal.addEventListener("abort", relayAbort, { once: true });
  const deadline = setTimeout(() => controller.abort(new Error("更新仍在后台进行；页面已停止等待，可稍后读取快照。 / Polling timed out; read the saved snapshot later.")), options.timeoutMs ?? 360_000);
  try {
    let current = initial;
    let polls = 0;
    while (true) {
      controller.signal.throwIfAborted();
      publish(current);
      if (current.status !== "updating") return;
      if (polls++ >= (options.maxPolls ?? 120)) throw new Error("更新仍在后台进行；页面已停止等待，可稍后读取快照。 / Polling limit reached.");
      await waitForNextRead(options.intervalMs ?? 3000, controller.signal);
      current = await read(controller.signal);
    }
  } finally {
    clearTimeout(deadline);
    signal.removeEventListener("abort", relayAbort);
  }
}

export function companyResearchQuestion(report: CompanyResearch, locale: "zh" | "en"): string {
  if (!report.snapshot_id) return "";
  return locale === "zh"
    ? `请基于公司研究快照分析 ${report.symbol}。snapshot_id=${report.snapshot_id}。核对主营业务、收入与现金流变化、估值和公告风险，注明报告期、来源和缺失项；区分事实与第三方观点。仅提出可检验的研究问题，说明尚缺哪些 PIT 数据，不创建或启用策略。`
    : `Research ${report.symbol} using company snapshot_id=${report.snapshot_id}. Review business segments, revenue, cash flow, valuation and filing risks, with reporting periods, sources and missing evidence. Separate facts from third-party views. Suggest testable research questions and identify missing PIT data; do not create or activate strategies.`;
}
