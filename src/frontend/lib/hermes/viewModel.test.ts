import { describe, expect, it } from "vitest";
import type { AgentCandidatesResponse, HermesResultsResponse } from "@/lib/api";
import { buildHermesTodayModel, pickLatestAutomation } from "./viewModel";
import {
  candidateFixture,
  degradedArtifacts,
  healthyArtifacts,
  noArtifacts,
} from "./viewModelFixtures";

const emptyResults = {
  read_status: "empty",
  total: 0,
  total_is_exact: true,
  limit: 5,
  offset: 0,
  has_more: false,
  items: [],
  sources: [],
  warnings: [],
} satisfies HermesResultsResponse;

describe("buildHermesTodayModel", () => {
  it("does not report an empty desk when the unified catalog contains a platform result", () => {
    const results = {
      read_status: "available",
      total: 1,
      total_is_exact: true,
      limit: 5,
      offset: 0,
      has_more: false,
      items: [
        {
          kind: "backtest",
          resource_id: "backtest-wave3-001",
          display_title: "AAPL momentum backtest",
          summary: "2026-01-01 → 2026-06-30 · provider futu",
          status: "completed",
          occurred_at: "2026-07-15T08:00:00Z",
          source: "platform_runs",
          authority: "platform_run_artifact",
          freshness: "fresh",
          read_status: "available",
          detail_href: "/api/hermes/results/backtest/backtest-wave3-001",
          original_href: "/api/backtest/runs/backtest-wave3-001",
          run_links: [],
        },
      ],
      sources: [
        {
          source: "platform_runs",
          read_status: "available",
          item_count: 1,
        },
      ],
      warnings: [],
    } as unknown as HermesResultsResponse;

    const model = buildHermesTodayModel({
      artifacts: noArtifacts("empty"),
      candidates: { candidates: [] },
      results,
    });

    expect(model.state).toBe("normal");
    expect(model.unifiedResults.items).toEqual([
      expect.objectContaining({
        kind: "backtest",
        resourceId: "backtest-wave3-001",
        displayTitle: "AAPL momentum backtest",
      }),
    ]);
  });

  it("orders mixed-offset artifact timestamps by their actual instant", () => {
    const automation = healthyArtifacts.items.find(
      (item) => item.kind === "automation_status",
    );
    const weekly = healthyArtifacts.items.find(
      (item) => item.kind === "weekly_review",
    );
    if (!automation || !weekly) throw new Error("fixture is incomplete");

    const olderAutomation = {
      ...automation,
      id: "automation-older-offset",
      occurred_at: "2026-07-14T10:00:00+08:00",
    };
    const newerAutomation = {
      ...automation,
      id: "automation-newer-z",
      occurred_at: "2026-07-14T03:00:00Z",
    };
    expect(
      pickLatestAutomation([olderAutomation, newerAutomation])?.id,
    ).toBe("automation-newer-z");

    const model = buildHermesTodayModel({
      artifacts: {
        ...healthyArtifacts,
        items: [
          { ...weekly, id: "result-older-offset", occurred_at: "2026-07-14T10:00:00+08:00" },
          { ...weekly, id: "result-newer-z", occurred_at: "2026-07-14T03:00:00Z" },
          newerAutomation,
        ],
      },
      candidates: { candidates: [] },
      results: emptyResults,
    });
    expect(model.hqaConclusions.map((item) => item.id)).toEqual([
      "result-newer-z",
      "result-older-offset",
    ]);
  });

  it("compresses healthy automation to one summary and emits no normal job cards", () => {
    const model = buildHermesTodayModel({
      artifacts: healthyArtifacts,
      candidates: { candidates: [] },
      results: emptyResults,
    });
    expect(model.automation).toMatchObject({
      healthy: 4,
      total: 4,
      status: "healthy",
      exceptions: [],
    });
    expect(model.attention).toEqual([]);
    expect(model.state).toBe("normal");
  });

  it("degrades Today when the candidate endpoint fails independently", () => {
    const model = buildHermesTodayModel({
      artifacts: healthyArtifacts,
      candidates: {
        candidates: [],
        apiError: "503: candidate repository unavailable",
      },
      results: emptyResults,
    });

    expect(model.state).toBe("degraded");
    expect(model.attention).toContainEqual({
      id: "candidate-feed",
      kind: "degraded",
      title: "Candidate source unavailable",
      summary: "503: candidate repository unavailable",
    });
  });

  it("keeps normal posture when the only attention is a verified research approval", () => {
    const model = buildHermesTodayModel({
      artifacts: healthyArtifacts,
      candidates: {
        candidates: [
          candidateFixture({
            candidate_id: "factor-healthy-approval",
            artifact_type: "factor",
            goal: "Evaluate a healthy pending factor",
            universe: ["AAPL"],
            status: "pending",
            manifest_digest: "a".repeat(64),
            observed_manifest_digest: null,
            approval_binding: "pending",
            integrity_state: "verified",
            approval_enabled: true,
            integrity_error_code: null,
          }),
        ],
      } satisfies AgentCandidatesResponse,
      results: emptyResults,
    });
    expect(model.state).toBe("normal");
    expect(model.attention.map((item) => item.kind)).toEqual(["approval"]);
    expect(model.automation.exceptions).toEqual([]);
  });

  it("promotes only failed/stale jobs and research approvals to attention", () => {
    const model = buildHermesTodayModel({
      artifacts: degradedArtifacts,
      candidates: {
        candidates: [
          candidateFixture({
            candidate_id: "factor-long-approval-id",
            artifact_type: "factor",
            goal: "Evaluate a deterministic reversal factor",
            universe: ["AAPL"],
            status: "pending",
            manifest_digest: "a".repeat(64),
            observed_manifest_digest: null,
            approval_binding: "pending",
            integrity_state: "verified",
            approval_enabled: true,
            integrity_error_code: null,
          }),
        ],
      } satisfies AgentCandidatesResponse,
      results: emptyResults,
    });
    expect(model.state).toBe("degraded");
    expect(model.attention.map((item) => item.kind)).toEqual([
      "approval",
      "stale",
    ]);
    expect(model.automation.exceptions).toHaveLength(1);
  });

  it("distinguishes empty feed from unavailable Hermes sources", () => {
    const empty = buildHermesTodayModel({
      artifacts: noArtifacts("empty"),
      candidates: { candidates: [] },
      results: emptyResults,
    });
    expect(empty.state).toBe("empty");
    expect(empty.automation).toMatchObject({
      healthy: 0,
      total: 4,
      status: "unavailable",
    });
    expect(
      buildHermesTodayModel({
        artifacts: noArtifacts("unavailable"),
        candidates: { candidates: [] },
        results: emptyResults,
      }).state,
    ).toBe("offline");
  });

  it("keeps HQA source outage authoritative when the unified catalog is also unavailable", () => {
    const model = buildHermesTodayModel({
      artifacts: noArtifacts("unavailable"),
      candidates: { candidates: [] },
      results: {
        ...emptyResults,
        read_status: "unavailable",
        warnings: [
          {
            source: "results_catalog",
            code: "api_unavailable",
            kind: null,
            resource_id: null,
          },
        ],
      },
    });

    expect(model.state).toBe("offline");
    expect(model.unifiedResults).toMatchObject({
      readStatus: "unavailable",
      total: null,
    });
  });

  it("degrades an available feed that is missing its automation artifact", () => {
    const artifacts = {
      ...healthyArtifacts,
      items: healthyArtifacts.items.filter(
        (item) => item.kind !== "automation_status",
      ),
    };
    const model = buildHermesTodayModel({
      artifacts,
      candidates: { candidates: [] },
      results: emptyResults,
    });

    expect(model.automation.status).toBe("unavailable");
    expect(model.state).toBe("degraded");
  });

  it("shows unversioned candidates as migration attention, never approval", () => {
    const model = buildHermesTodayModel({
      artifacts: healthyArtifacts,
      candidates: {
        candidates: [
          candidateFixture({
            candidate_id: "legacy-pending",
            artifact_type: "factor",
            goal: "Migrate an unversioned factor candidate",
            universe: ["AAPL"],
            status: "pending",
            manifest_digest: null,
            observed_manifest_digest: "b".repeat(64),
            approval_binding: "pending",
            integrity_state: "migration_required",
            approval_enabled: false,
            integrity_error_code: null,
          }),
        ],
      } satisfies AgentCandidatesResponse,
      results: emptyResults,
    });
    expect(model.attention).toEqual([
      expect.objectContaining({ kind: "degraded", id: "legacy-pending" }),
    ]);
  });

  it("surfaces a corrupt candidate's stable integrity reason", () => {
    const model = buildHermesTodayModel({
      artifacts: healthyArtifacts,
      candidates: {
        candidates: [
          candidateFixture({
            candidate_id: "corrupt-candidate",
            artifact_type: null,
            goal: null,
            universe: null,
            status: null,
            integrity_state: "corrupt",
            manifest_digest: null,
            observed_manifest_digest: null,
            approval_binding: null,
            approval_enabled: false,
            integrity_error_code: "manifest_digest_mismatch",
          }),
        ],
      } satisfies AgentCandidatesResponse,
      results: emptyResults,
    });

    expect(model.attention).toContainEqual({
      id: "corrupt-candidate",
      kind: "degraded",
      title: "Candidate integrity failed",
      summary: "manifest_digest_mismatch",
    });
  });
});
