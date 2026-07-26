import { describe, expect, it } from "vitest";

import {
  canActGate,
  filterGatesForPanel,
  gateRequiresHumanNote,
} from "@/components/hermes/gates/WorkbenchGateSurfacesPanel";
import type { WorkspaceGateProjection } from "@/lib/hermes/workspaceClient";

function gate(
  partial: Partial<WorkspaceGateProjection> & {
    gate_id: string;
    gate_kind: string;
  },
): WorkspaceGateProjection {
  return {
    status: "pending",
    ...partial,
  };
}

describe("gate surfaces helpers (V7e)", () => {
  it("canActGate gate1 requires task + sha256", () => {
    expect(
      canActGate(
        gate({
          gate_id: "g1",
          gate_kind: "gate1",
          task_id: "t1",
          reviewed_source_sha256: "a".repeat(64),
        }),
      ),
    ).toBe(true);
    expect(
      canActGate(
        gate({
          gate_id: "g1",
          gate_kind: "gate1",
          task_id: "t1",
          reviewed_source_sha256: "nope",
        }),
      ),
    ).toBe(false);
    expect(
      canActGate(
        gate({
          gate_id: "g1",
          gate_kind: "gate1",
          status: "confirmed",
          task_id: "t1",
          reviewed_source_sha256: "a".repeat(64),
        }),
      ),
    ).toBe(false);
  });

  it("canActGate gate3 requires base_commit 40-hex + receipt", () => {
    expect(
      canActGate(
        gate({
          gate_id: "g3",
          gate_kind: "gate3",
          candidate_id: "c1",
          expected_digest: "b".repeat(64),
          final_backtest_receipt_id: "r1",
          base_commit: "c".repeat(40),
        }),
      ),
    ).toBe(true);
    expect(
      canActGate(
        gate({
          gate_id: "g3",
          gate_kind: "gate3",
          candidate_id: "c1",
          expected_digest: "b".repeat(64),
          final_backtest_receipt_id: "r1",
          base_commit: "short",
        }),
      ),
    ).toBe(false);
  });

  it("filterGatesForPanel hides only while still pending after consume", () => {
    const pending = gate({
      gate_id: "g1",
      gate_kind: "gate1",
      task_id: "t",
      reviewed_source_sha256: "a".repeat(64),
    });
    const decided = gate({
      gate_id: "g1",
      gate_kind: "gate1",
      status: "confirmed",
      task_id: "t",
      reviewed_source_sha256: "a".repeat(64),
      note: "done",
    });
    expect(filterGatesForPanel([pending], { g1: true })).toEqual([]);
    expect(filterGatesForPanel([decided], { g1: true })).toEqual([decided]);
  });

  it("buildConfirmFormulaSourceAction shape matches HQA fields", async () => {
    const { buildConfirmFormulaSourceAction, buildReviewCandidateCASAction, buildPreparePromotionReviewAction } =
      await import("@/lib/hermes/workspaceClient");
    const g1 = buildConfirmFormulaSourceAction({
      taskId: "t1",
      reviewedSourceSha256: "a".repeat(64),
      confirmationNote: "ok",
      clientActionId: "act1",
      workspaceId: "ws",
    });
    expect(g1.kind).toBe("gate1.formula_source.confirm");
    expect(g1.task_ref).toBe("task:t1");
    const g2 = buildReviewCandidateCASAction({
      candidateId: "c1",
      expectedDigest: "b".repeat(64),
      note: "n",
      clientActionId: "act2",
      workspaceId: "ws",
    });
    expect(g2.kind).toBe("gate2.candidate.review");
    expect(g2.expected_status).toBe("pending");
    const g3 = buildPreparePromotionReviewAction({
      candidateId: "c2",
      expectedDigest: "a".repeat(64),
      finalBacktestReceiptId: "r1",
      baseCommit: "c".repeat(40),
      clientActionId: "act3",
      workspaceId: "ws",
    });
    expect(g3.kind).toBe("gate3.promotion_review.prepare");
    expect(g3.base_commit).toBe("c".repeat(40));
  });

  it("gate1/2 require human note; gate3 does not", () => {
    expect(
      gateRequiresHumanNote(
        gate({ gate_id: "g1", gate_kind: "gate1", task_id: "t" }),
      ),
    ).toBe(true);
    expect(
      gateRequiresHumanNote(
        gate({ gate_id: "g2", gate_kind: "gate2", candidate_id: "c" }),
      ),
    ).toBe(true);
    expect(
      gateRequiresHumanNote(
        gate({
          gate_id: "g3",
          gate_kind: "gate3",
          candidate_id: "c",
          expected_digest: "b".repeat(64),
          final_backtest_receipt_id: "r1",
          base_commit: "c".repeat(40),
        }),
      ),
    ).toBe(false);
  });

  it("keeps exact Gate 1 review material and Gate 2 digest in the panel source", async () => {
    const { readFile } = await import("node:fs/promises");
    const source = await readFile(
      new URL(
        "../../components/hermes/gates/WorkbenchGateSurfacesPanel.tsx",
        import.meta.url,
      ),
      "utf8",
    );
    expect(source).toContain("row.source_file_ref");
    expect(source).toContain("row.universe");
    expect(source).toContain("source SHA-256: {row.reviewed_source_sha256}");
    expect(source).toContain("candidate digest: {row.expected_digest}");
    expect(source).toContain("data-hermes-gate-source-load");
    expect(source).toContain("data-hermes-gate-source-bytes");
    expect(source).toContain("data-hermes-gate-source-acknowledge");
    expect(source).toContain("client_verified_sha256");
    expect(source).toContain("Open candidate evidence");
    expect(source).not.toContain(
      "source: {displayId(row.reviewed_source_sha256)}",
    );
    expect(source).not.toContain("digest: {displayId(row.expected_digest)}");
  });

  it("independently hashes Gate 1 UTF-8 source and rejects substituted bytes", async () => {
    const { verifyGate1SourceEvidence, WorkspaceClientError } = await import(
      "@/lib/hermes/workspaceClient"
    );
    const exactDigest =
      "e13df8c44af5dea1e412403910b99cc5a48f2ccbf68a66b3374d6ab9cef9fc65";
    const wire = {
      schema_version: "1.0" as const,
      gate_id: "paper-gate-1",
      workspace_id: "workspace-root",
      source_file_ref: "/safe/reversal.py",
      reviewed_source_sha256: exactDigest,
      observed_source_sha256: exactDigest,
      byte_length: 10,
      media_type: "text/x-python; charset=utf-8" as const,
      source_utf8: "VALUE = 1\n",
    };
    const verified = await verifyGate1SourceEvidence(wire, {
      workspaceId: "workspace-root",
      gateId: "paper-gate-1",
      reviewedSourceSha256: exactDigest,
    });
    expect(verified.client_verified_sha256).toBe(exactDigest);

    await expect(
      verifyGate1SourceEvidence(
        { ...wire, source_utf8: "VALUE = 2\n" },
        {
          workspaceId: "workspace-root",
          gateId: "paper-gate-1",
          reviewedSourceSha256: exactDigest,
        },
      ),
    ).rejects.toBeInstanceOf(WorkspaceClientError);
  });
});
