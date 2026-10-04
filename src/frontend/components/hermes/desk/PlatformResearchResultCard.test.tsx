import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  PlatformResearchResultCard,
  selectPlatformResearchResult,
} from "./PlatformResearchResultCard";

const source = readFileSync(
  path.join(process.cwd(), "components/hermes/desk/PlatformResearchResultCard.tsx"),
  "utf8",
);

function evidence(operationId: string, sourceDigest: string) {
  const manifestDigest = "f".repeat(64);
  const href = `/api/assistant/remote/evidence/${operationId}/${manifestDigest}`;
  return {
    value: {
      manifest_digest: manifestDigest,
      href,
      candidate_code_digest: sourceDigest,
      candidate_code: "factor_id = 'verified_factor'",
      candidate_code_href: `${href}#candidate-code`,
      qlib_receipt_digest: "b".repeat(64),
      qlib_receipt_href: `${href}#qlib-receipt`,
      platform_receipt_digest: "c".repeat(64),
      platform_receipt_href: `${href}#platform-receipt`,
      comparison_digest: "d".repeat(64),
      comparison_href: `${href}#comparison`,
      comparison: {
        accepted: true,
        daily_return_correlation: 1,
        terminal_nav_difference_bps: 0,
        max_symbol_weight_difference_bps: 0,
      },
      cost_model: { commission_bps: 1, slippage_bps: 5 },
      dsr: { value: 1.2, passed: true },
      verification_gates: {
        dsr: { value: 1.2, passed: true },
        max_hung_correlation: null,
        cost_sensitivity: { passed: true },
      },
      performance: {
        total_return: 0.12,
        sharpe_annual: 1.4,
        max_drawdown: 0.08,
        turnover_period: 0.2,
        n_periods: 240,
        window_start: "2025-01-02",
        window_end: "2025-12-16",
      },
      failed_phase: null,
      failure_code: null,
    },
    provenance: {
      evidence_manifest_digest: manifestDigest,
      evidence_href: href,
    },
  };
}

describe("Platform research result projection", () => {
  it("uses 44px targets for evidence controls and the candidate-library link", () => {
    expect(source).toMatch(/<a[\s\S]*?className="app-touch-target/);
    expect(source).toMatch(/aria-controls=\{panelId\}[\s\S]*?className="app-touch-target/);
    expect(source).toMatch(/className="app-touch-target[\s\S]*?href=\{localizePath\(result.code/);
  });
  it("distinguishes automatic paper activation from a verified candidate that could not activate", () => {
    const render = (code: string) => renderToStaticMarkup(createElement(PlatformResearchResultCard, {
      locale: "zh",
      result: {
        code, message: "Activation result", outcome: "verified_candidate", status: "candidate_ready", terminal: true,
        candidate_id: "candidate-test", source_digest: "a".repeat(64),
        provenance: { operation_id: "b".repeat(64), material_digest: "c".repeat(64), job_id: "job-test", job_key: "job-key-test" },
      },
    }));
    const running = render("paper_running");
    expect(running).toContain("模拟运行已启用");
    expect(running).toContain("10,000 美元模拟资金");
    expect(running).toContain('href="/zh/paper-trading"');
    expect(running).not.toContain("当前尚未启用模拟运行");
    const blocked = render("paper_activation_failed:insufficient_cash");
    expect(blocked).toContain("候选已保留");
    expect(blocked).toContain("insufficient_cash");
    expect(blocked).toContain('href="/zh/library"');
    expect(blocked).not.toContain("10,000 美元模拟资金");
  });
  it("selects only a valid request bound to the active Hermes session", () => {
    const digest = "a".repeat(64);
    const selected = selectPlatformResearchResult(
      [
        {
          hermes_session_id: "run_other",
          operation_id: "b".repeat(64),
          material_digest: "c".repeat(64),
          job_id: "job-other",
          job_key: "job-key-other",
          outcome: "verified_candidate",
          status: "candidate_ready",
          terminal: true,
          candidate_id: "candidate-other",
          source_digest: digest,
          evidence: evidence("d".repeat(64), digest).value,
          result_reply: {
            status: "candidate_ready",
            code: "candidate_verified",
            message: "wrong session",
            provenance: {
              operation_id: "b".repeat(64),
              material_digest: "c".repeat(64),
              job_id: "job-other",
              job_key: "job-key-other",
              candidate_id: "candidate-other",
              source_digest: digest,
              ...evidence("d".repeat(64), digest).provenance,
            },
          },
        },
        {
          hermes_session_id: "run_active",
          operation_id: "d".repeat(64),
          material_digest: "e".repeat(64),
          job_id: "job-active",
          job_key: "job-key-active",
          outcome: "verified_candidate",
          status: "candidate_ready",
          terminal: true,
          candidate_id: "candidate-active",
          source_digest: digest,
          evidence: evidence("d".repeat(64), digest).value,
          result_reply: {
            status: "candidate_ready",
            code: "candidate_verified",
            message: "Candidate verified.",
            display_name_zh: "21 日横截面动量策略",
            summary_zh: "研究已完成验证，当前尚未启用模拟运行。",
            provenance: {
              operation_id: "d".repeat(64),
              material_digest: "e".repeat(64),
              job_id: "job-active",
              job_key: "job-key-active",
              candidate_id: "candidate-active",
              source_digest: digest,
              ...evidence("d".repeat(64), digest).provenance,
            },
          },
        },
      ],
      "run_active",
    );

    expect(selected).toMatchObject({
      message: "Candidate verified.",
      display_name_zh: "21 日横截面动量策略",
      summary_zh: "研究已完成验证，当前尚未启用模拟运行。",
      candidate_id: "candidate-active",
      source_digest: digest,
    });
  });

  it("fails closed for malformed replies and renders a labelled Platform card", () => {
    expect(
      selectPlatformResearchResult(
        [
          {
            hermes_session_id: "run_active",
            outcome: "verified_candidate",
            status: "succeeded",
            terminal: true,
            result_reply: "Candidate verified.",
          },
        ],
        "run_active",
      ),
    ).toBeNull();

    expect(
      selectPlatformResearchResult(
        [
          {
            hermes_session_id: "run_active",
            status: "queued",
            terminal: false,
            outcome: "queued",
            result_reply: { message: "newer but malformed" },
          },
          {
            hermes_session_id: "run_active",
            operation_id: "d".repeat(64),
            material_digest: "e".repeat(64),
            job_id: "job-old",
            job_key: "job-key-old",
            status: "queued",
            terminal: false,
            outcome: "queued",
            result_reply: {
              status: "queued",
              code: "research_queued",
              message: "older valid result",
              provenance: {
                operation_id: "d".repeat(64),
                material_digest: "e".repeat(64),
                job_id: "job-old",
                job_key: "job-key-old",
              },
            },
          },
        ],
        "run_active",
      ),
    ).toBeNull();

    const html = renderToStaticMarkup(
      createElement(PlatformResearchResultCard, {
        locale: "en",
        result: {
          code: "research_queued",
          message: "Research job queued.",
          outcome: "queued",
          status: "queued",
          terminal: false,
          provenance: {
            operation_id: "d".repeat(64),
            material_digest: "e".repeat(64),
            job_id: "job-active",
            job_key: "job-key-active",
          },
        },
      }),
    );
    expect(html).toContain("Platform research result");
    expect(html).toContain("Research job queued.");
    expect(html).not.toContain("data-role=\"hermes\"");
  });

  it("locks every outcome to its status and terminal combination", () => {
    const operationId = "d".repeat(64);
    const materialDigest = "e".repeat(64);
    const digest = "a".repeat(64);
    const request = (
      outcome: string,
      status: string,
      terminal: boolean,
      candidate = false,
    ) => ({
      hermes_session_id: "run_active",
      operation_id: operationId,
      material_digest: materialDigest,
      job_id: "job-active",
      job_key: "job-key-active",
      outcome,
      status,
      terminal,
      evidence: null,
      ...(candidate
        ? { candidate_id: "candidate-active", source_digest: digest }
        : {}),
      result_reply: {
        status,
        code: "research_state",
        message: "Research state.",
        provenance: {
          operation_id: operationId,
          material_digest: materialDigest,
          job_id: "job-active",
          job_key: "job-key-active",
          ...(candidate
            ? { candidate_id: "candidate-active", source_digest: digest }
            : {}),
        },
      },
    });

    for (const invalid of [
      request("queued", "queued", true),
      request("pending", "pending", true),
      request("verified_candidate", "succeeded", true, true),
      request("verified_candidate", "candidate_ready", false, true),
      request("failed", "failed", false),
      request("outcome_unknown", "outcome_unknown", false),
    ]) {
      expect(selectPlatformResearchResult([invalid], "run_active")).toBeNull();
    }
    expect(
      selectPlatformResearchResult(
        [request("pending", "pending", false)],
        "run_active",
      ),
    ).not.toBeNull();
    expect(
      selectPlatformResearchResult(
        [request("running", "running", false)],
        "run_active",
      ),
    ).not.toBeNull();
  });

  it("requires verified candidate provenance to match the request exactly", () => {
    const operationId = "d".repeat(64);
    const materialDigest = "e".repeat(64);
    const digest = "a".repeat(64);
    const verified = {
      hermes_session_id: "run_active",
      operation_id: operationId,
      material_digest: materialDigest,
      job_id: "job-active",
      job_key: "job-key-active",
      outcome: "verified_candidate",
      status: "candidate_ready",
      terminal: true,
      candidate_id: "candidate-active",
      source_digest: digest,
      result_reply: {
        status: "candidate_ready",
        code: "candidate_verified",
        message: "Candidate verified.",
        provenance: {
          operation_id: operationId,
          material_digest: materialDigest,
          job_id: "job-active",
          job_key: "job-key-active",
          candidate_id: "candidate-other",
          source_digest: digest,
        },
      },
    };

    expect(selectPlatformResearchResult([verified], "run_active")).toBeNull();
    expect(
      selectPlatformResearchResult(
        [
          {
            ...verified,
            result_reply: {
              ...verified.result_reply,
              provenance: {
                ...verified.result_reply.provenance,
                candidate_id: "candidate-active",
                source_digest: "b".repeat(64),
              },
            },
          },
        ],
        "run_active",
      ),
    ).toBeNull();
  });

  it("rejects candidate data on non-verified outcomes and renders no candidate link", () => {
    const operationId = "d".repeat(64);
    const materialDigest = "e".repeat(64);
    const digest = "a".repeat(64);
    const queuedWithCandidate = {
      hermes_session_id: "run_active",
      operation_id: operationId,
      material_digest: materialDigest,
      job_id: "job-active",
      job_key: "job-key-active",
      outcome: "queued",
      status: "queued",
      terminal: false,
      candidate_id: "candidate-forbidden",
      source_digest: digest,
      result_reply: {
        status: "queued",
        code: "research_queued",
        message: "Research queued.",
        provenance: {
          operation_id: operationId,
          material_digest: materialDigest,
          job_id: "job-active",
          job_key: "job-key-active",
          candidate_id: "candidate-forbidden",
          source_digest: digest,
        },
      },
    };

    expect(
      selectPlatformResearchResult([queuedWithCandidate], "run_active"),
    ).toBeNull();

    const html = renderToStaticMarkup(
      createElement(PlatformResearchResultCard, {
        locale: "en",
        result: {
          code: "research_failed",
          message: "Research failed.",
          outcome: "failed",
          status: "failed",
          terminal: true,
          candidate_id: "candidate-forbidden",
          source_digest: digest,
          provenance: {
            operation_id: operationId,
            material_digest: materialDigest,
            job_id: "job-active",
            job_key: "job-key-active",
          },
        },
      }),
    );
    expect(html).not.toContain("View in candidate library");
    expect(html).not.toContain("candidate-forbidden");
  });

  it("renders a content-addressed evidence link and accessible disclosure", () => {
    const operationId = "d".repeat(64);
    const digest = "a".repeat(64);
    const boundEvidence = evidence(operationId, digest).value;
    const html = renderToStaticMarkup(
      createElement(PlatformResearchResultCard, {
        locale: "en",
        result: {
          code: "verified_candidate_ready",
          message: "Candidate verified.",
          outcome: "verified_candidate",
          status: "candidate_ready",
          terminal: true,
          candidate_id: "candidate-active",
          source_digest: digest,
          evidence: boundEvidence,
          provenance: {
            operation_id: operationId,
            material_digest: "e".repeat(64),
            job_id: "job-active",
            job_key: "job-key-active",
            candidate_id: "candidate-active",
            source_digest: digest,
            ...evidence(operationId, digest).provenance,
          },
        },
      }),
    );

    expect(html).toContain(`href="${boundEvidence.href}"`);
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain("Show evidence");
  });

  it("keeps the Chinese primary card readable and moves raw identities into technical details", () => {
    const digest = "a".repeat(64);
    const verified = renderToStaticMarkup(
      createElement(PlatformResearchResultCard, {
        locale: "zh",
        result: {
          code: "candidate_verified_internal",
          message: "Candidate verified raw message.",
          display_name_zh: "21 日横截面动量策略",
          summary_zh: "研究已完成验证，当前尚未启用模拟运行。",
          outcome: "verified_candidate",
          status: "candidate_ready",
          terminal: true,
          candidate_id: "candidate-active",
          source_digest: digest,
          provenance: {
            operation_id: "d".repeat(64),
            material_digest: "e".repeat(64),
            job_id: "job-active",
            job_key: "job-key-active",
            candidate_id: "candidate-active",
            source_digest: digest,
          },
        },
      }),
    );
    const technicalStart = verified.indexOf(">技术信息<");
    expect(technicalStart).toBeGreaterThan(0);
    const primary = verified.slice(0, technicalStart);
    const technical = verified.slice(technicalStart);
    expect(primary).toContain("21 日横截面动量策略");
    expect(primary).toContain("研究已完成验证，当前尚未启用模拟运行。");
    expect(primary).toContain("已验证");
    expect(primary).toContain("去候选库");
    expect(primary).not.toContain("candidate_verified_internal");
    expect(primary).not.toContain("Candidate verified raw message.");
    expect(primary).not.toContain("candidate-active");
    expect(primary).not.toContain(digest);
    expect(technical).toContain("candidate_verified_internal");
    expect(technical).toContain("Candidate verified raw message.");
    expect(technical).toContain("candidate-active");
    expect(technical).toContain(digest);

    const fallback = renderToStaticMarkup(
      createElement(PlatformResearchResultCard, {
        locale: "zh",
        result: {
          code: "candidate_verified",
          message: "Candidate verified.",
          outcome: "verified_candidate",
          status: "candidate_ready",
          terminal: true,
          candidate_id: "candidate-fallback",
          source_digest: digest,
          provenance: {
            operation_id: "d".repeat(64),
            material_digest: "e".repeat(64),
            job_id: "job-fallback",
            job_key: "job-key-fallback",
          },
        },
      }),
    );
    expect(fallback).toContain("已验证因子候选");

    const queued = renderToStaticMarkup(
      createElement(PlatformResearchResultCard, {
        locale: "zh",
        result: {
          code: "research_queued",
          message: "Research job queued.",
          outcome: "queued",
          status: "queued",
          terminal: false,
          provenance: {
            operation_id: "d".repeat(64),
            material_digest: "e".repeat(64),
            job_id: "job-queued",
            job_key: "job-key-queued",
          },
        },
      }),
    );
    expect(queued).toContain("平台研究进度");
    expect(queued).toContain("排队中");
    expect(queued).toContain("研究任务已排队。");
  });
});
