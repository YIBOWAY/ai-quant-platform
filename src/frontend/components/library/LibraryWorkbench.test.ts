import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const source = readFileSync(
  path.join(process.cwd(), "components/library/LibraryWorkbench.tsx"),
  "utf8",
);
const pageSource = readFileSync(
  path.join(process.cwd(), "app/library/page.tsx"),
  "utf8",
);

describe("candidate-only research library", () => {
  it("polls only the remote book and makes the digest-bound hang action explicit", () => {
    expect(source).toContain("loadVerifiedLibraryCandidates");
    expect(source).toContain("refetchInterval: 15_000");
    expect(source).toMatch(
      /const libraryQuery = useQuery\(\{[\s\S]*?refetchInterval: 15_000,[\s\S]*?retry: false,[\s\S]*?\}\);/,
    );
    expect(source).toContain("hangLibraryCandidate");
    expect(source).toContain("resolveLibraryHangOutcome");
    expect(source).toContain('"resolved_hung"');
    expect(source).toContain('"still_verified"');
    expect(source).toContain('"still_unknown"');
    expect(source).toContain("启用模拟运行");
    expect(source).toContain("将分配 10,000 美元模拟资金，并按每日信号自动运行");
    expect(source).toContain("模拟运行中");
    expect(source).toContain("恢复模拟运行");
    expect(source).toContain("不会重复分配资金");
    expect(source).toContain("Enable simulated running");
    expect(source).toContain("Allocates USD 10,000 in simulated funds");
    expect(source).toContain("Simulated run active");
    expect(source).toContain("candidate.activation_eligibility.eligible");
    expect(source).toContain("候选状态已经变化，请刷新候选库后再试");
    expect(source).toMatch(
      /resolution !== "still_unknown"[\s\S]*?invalidateQueries[\s\S]*?hangMutation\.reset\(\)/,
    );
    expect(source).toMatch(
      /\{activationEligible \? \(\s*<div className="mt-auto pt-5">[\s\S]*?<button/,
    );
    expect(source).toContain('data-hang-state="pending"');
    expect(source).toContain("aria-describedby={pending ? pendingStatusId : undefined}");
    expect(source).toContain("aria-busy={pending}");
    expect(source).toContain('role="status"');
    expect(source).toContain('className="sr-only"');
    expect(source).toContain('data-hang-state="already_hung"');
    expect(source).toContain('role="alert"');
    expect(source).toContain("hangMutation.isPending || hangOutcomeUnknown");
    expect(source).not.toContain("backtest");
    expect(source).not.toContain("report");
  });

  it("uses native controls without a nested interactive flip surface", () => {
    expect(source).toContain('type="search"');
    expect(source).toContain('type="button"');
    expect(source).not.toContain('role="button"');
    expect(source).not.toContain("onKeyDown");
    expect(source).not.toContain("FlipCard");
  });

  it("uses the shared 44px target contract for every primary control", () => {
    expect(source).toMatch(/<input[\s\S]*?className="app-touch-target/);
    expect(source).toMatch(/refreshBook[\s\S]*?className="app-touch-target/);
    expect(source).toMatch(/aria-busy=\{pending\}[\s\S]*?className="app-touch-target/);
  });

  it("shows a loading skeleton while the candidate book is loading", () => {
    expect(source).toContain("libraryQuery.isLoading");
    expect(source).toContain("<LoadingSkeleton");
    expect(source).toContain('role="status"');
    expect(source).toContain("Loading verified candidates…");
    expect(source).toContain("正在加载已验证候选…");
  });

  it("indexes the English display name so search matches the card title", () => {
    expect(source).toMatch(
      /function searchText[\s\S]*?candidate\.display_name \?\? ""[\s\S]*?candidate\.display_name_zh \?\? ""/,
    );
  });

  it("fits inside AppChrome without another main landmark or data fanout", () => {
    expect(pageSource).toContain("LibraryWorkbench");
    expect(pageSource).toContain("尚未启用模拟运行");
    expect(pageSource).toContain("Enabling simulated running");
    expect(pageSource).not.toContain("尚未进入模拟盘");
    expect(pageSource).not.toContain("Entering paper trading");
    expect(pageSource).not.toContain("<main");
    expect(pageSource).not.toContain("backtest");
    expect(pageSource).not.toContain("report");
  });

  it("uses readable candidate copy and keeps exact identities in collapsed technical details", () => {
    expect(source).toContain("candidatePresentation(candidate, locale)");
    expect(source).toContain("presentation.name");
    expect(source).toContain("presentation.summary");
    expect(source).toContain("标的范围");
    expect(source).toContain("技术信息");
    expect(source).toContain("<details");
    expect(source).toContain("candidate.source_digest");
    expect(source).not.toContain('digest: "来源 digest"');
    expect(source).not.toContain('universe: "研究宇宙"');
    expect(pageSource).not.toContain("digest 绑定命令");
  });
});
