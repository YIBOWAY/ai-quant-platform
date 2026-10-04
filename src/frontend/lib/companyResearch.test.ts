import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), owner: vi.fn(), order: [] as string[] }));
vi.mock("./apiClient", () => ({ apiRequest: calls.get }));
vi.mock("./hermes/workspaceClient", () => ({ ensureOwnerSession: calls.owner, ownerPostJson: calls.post }));

import {
  checkDataSources, companyResearchQuestion, compareCompanyResearch, getCompanyResearch, getDataSources,
  normalizeResearchSymbol, observeResearchUpdate, refreshCompanyResearch, researchNumber, researchRows,
  researchText, safeResearchUrl, type CompanyResearch,
} from "./companyResearch";

beforeEach(() => {
  vi.clearAllMocks(); calls.order.length = 0;
  calls.owner.mockImplementation(async () => { calls.order.push("owner"); });
  calls.post.mockImplementation(async () => { calls.order.push("post"); return { status: "updating" }; });
});
afterEach(() => vi.useRealTimers());

describe("company research API boundary", () => {
  it("uses only GET for initial reads, saved comparisons and capability status", async () => {
    await getCompanyResearch(" nvda ");
    expect(calls.get).toHaveBeenLastCalledWith("/api/company-research?symbol=NVDA");
    await compareCompanyResearch(["nvda", "AAPL.US", "nvda"]);
    expect(calls.get).toHaveBeenLastCalledWith("/api/company-research/compare?symbols=NVDA%2CAAPL.US");
    await getDataSources();
    expect(calls.get).toHaveBeenLastCalledWith("/api/data-sources");
    expect(calls.owner).not.toHaveBeenCalled();
    expect(calls.post).not.toHaveBeenCalled();
  });

  it("carries cancellation through saved reads and refresh uses owner/CSRF once", async () => {
    const signal = new AbortController().signal;
    await getCompanyResearch("700.HK", signal);
    expect(calls.get).toHaveBeenLastCalledWith("/api/company-research?symbol=700.HK", { signal });
    await refreshCompanyResearch("NVDA", signal);
    expect(calls.order).toEqual(["owner", "post"]);
    expect(calls.post).toHaveBeenLastCalledWith("/api/company-research/refresh", { symbol: "NVDA" }, signal);
    await checkDataSources("SPY", signal);
    expect(calls.post).toHaveBeenLastCalledWith("/api/data-sources/check", { symbol: "SPY" }, signal);
  });

  it("does not send a mutation after cancellation while acquiring owner state", async () => {
    const controller = new AbortController();
    calls.owner.mockImplementation(async () => controller.abort());
    await expect(refreshCompanyResearch("NVDA", controller.signal)).rejects.toThrow();
    expect(calls.post).not.toHaveBeenCalled();
  });

  it("rejects invalid codes and more than four comparisons before any I/O", async () => {
    expect(() => normalizeResearchSymbol("NVDA; rm")).toThrow();
    expect(() => compareCompanyResearch(["A", "B", "C", "D", "E"])).toThrow();
    await expect(refreshCompanyResearch("<script>")).rejects.toThrow();
    expect(calls.get).not.toHaveBeenCalled(); expect(calls.owner).not.toHaveBeenCalled();
  });
});

describe("bounded saved-state observation", () => {
  it("does not poll a terminal or not-loaded response", async () => {
    const read = vi.fn(), publish = vi.fn();
    for (const status of ["not_loaded", "available", "partial", "failed"]) {
      await observeResearchUpdate({ status }, read, publish, new AbortController().signal);
    }
    expect(read).not.toHaveBeenCalled(); expect(publish).toHaveBeenCalledTimes(4);
  });

  it("polls updating only and stops after the first terminal response", async () => {
    vi.useFakeTimers();
    const read = vi.fn().mockResolvedValueOnce({ status: "updating" }).mockResolvedValueOnce({ status: "partial" });
    const publish = vi.fn();
    const job = observeResearchUpdate({ status: "updating" }, read, publish, new AbortController().signal, { intervalMs: 10 });
    await vi.advanceTimersByTimeAsync(30); await job;
    expect(read).toHaveBeenCalledTimes(2);
    expect(publish.mock.calls.map(([value]) => value.status)).toEqual(["updating", "updating", "partial"]);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not publish a late result for the symbol that was cancelled", async () => {
    vi.useFakeTimers();
    let resolveRead!: (value: { status: string; symbol: string }) => void;
    const read = vi.fn(() => new Promise<{ status: string; symbol: string }>(resolve => { resolveRead = resolve; }));
    const controller = new AbortController(), publish = vi.fn();
    const job = observeResearchUpdate({ status: "updating", symbol: "NVDA" }, read, publish, controller.signal, { intervalMs: 10 });
    const stopped = expect(job).rejects.toThrow();
    await vi.advanceTimersByTimeAsync(10);
    controller.abort();
    resolveRead({ status: "available", symbol: "NVDA" });
    await stopped;
    expect(publish).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("stops at its polling bound and never restarts an update", async () => {
    vi.useFakeTimers();
    const read = vi.fn().mockResolvedValue({ status: "updating" });
    const job = observeResearchUpdate({ status: "updating" }, read, vi.fn(), new AbortController().signal, { intervalMs: 10, maxPolls: 2 });
    const ended = expect(job).rejects.toThrow("Polling limit reached");
    await vi.advanceTimersByTimeAsync(30); await ended;
    expect(read).toHaveBeenCalledTimes(2); expect(calls.post).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("cancels waiting when the observation deadline expires", async () => {
    vi.useFakeTimers();
    const read = vi.fn();
    const job = observeResearchUpdate({ status: "updating" }, read, vi.fn(), new AbortController().signal, { intervalMs: 100, timeoutMs: 20 });
    const ended = expect(job).rejects.toThrow("Polling timed out");
    await vi.advanceTimersByTimeAsync(30); await ended;
    expect(read).not.toHaveBeenCalled(); expect(vi.getTimerCount()).toBe(0);
  });
});

describe("untrusted source formatting", () => {
  it("keeps missing data distinct from zero and ignores unknown objects", () => {
    for (const value of [null, undefined, "", "-", " ", {}, false, Infinity, "NaN"]) expect(researchNumber(value)).toBeNull();
    expect(researchNumber(0)).toBe(0); expect(researchNumber("1,250.25")).toBe(1250.25);
    expect(researchText({ name: "unsafe object" })).toBe("—");
    expect(researchRows([null, "test", 0, { name: "record" }])).toEqual([{ name: "record" }]);
  });
  it("accepts only absolute HTTP(S) source links", () => {
    for (const value of ["javascript:alert(1)", "data:text/html,hi", "file:///etc/passwd", "/relative", {}, null]) expect(safeResearchUrl(value)).toBeNull();
    expect(safeResearchUrl("https://example.com/filing")).toBe("https://example.com/filing");
  });
  it("binds the copied question to the exact saved snapshot without sending it", () => {
    const report = { symbol: "NVDA", snapshot_id: "snapshot-123" } as CompanyResearch;
    expect(companyResearchQuestion(report, "zh")).toContain("NVDA。snapshot_id=snapshot-123");
    expect(companyResearchQuestion(report, "en")).toContain("snapshot_id=snapshot-123");
    expect(companyResearchQuestion({ ...report, snapshot_id: null }, "zh")).toBe("");
    expect(calls.post).not.toHaveBeenCalled();
  });
});
