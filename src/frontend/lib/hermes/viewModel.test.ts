import { describe, expect, it } from "vitest";
import type { AgentCandidatesResponse } from "@/lib/api";
import { buildHermesTodayModel } from "./viewModel";
import {
  candidateFixture,
  degradedArtifacts,
  healthyArtifacts,
  noArtifacts,
} from "./viewModelFixtures";

describe("buildHermesTodayModel", () => {
  it("compresses healthy automation to one summary and emits no normal job cards", () => {
    const model = buildHermesTodayModel({
      artifacts: healthyArtifacts,
      candidates: { candidates: [] },
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
    });
    expect(model.state).toBe("degraded");
    expect(model.attention.map((item) => item.kind)).toEqual([
      "approval",
      "stale",
    ]);
    expect(model.automation.exceptions).toHaveLength(1);
  });

  it("distinguishes empty feed from unavailable Hermes sources", () => {
    expect(
      buildHermesTodayModel({
        artifacts: noArtifacts("empty"),
        candidates: { candidates: [] },
      }).state,
    ).toBe("empty");
    expect(
      buildHermesTodayModel({
        artifacts: noArtifacts("unavailable"),
        candidates: { candidates: [] },
      }).state,
    ).toBe("offline");
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
    });
    expect(model.attention).toEqual([
      expect.objectContaining({ kind: "degraded", id: "legacy-pending" }),
    ]);
  });
});
