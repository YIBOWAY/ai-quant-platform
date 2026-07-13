import { describe, expect, it } from "vitest";
import type { Tone } from "@/components/hermes/artifacts/formatters";
import {
  asCandidateApprovalBinding,
  candidateBindingTone,
  candidateDigestPresentation,
  type CandidateApprovalBinding,
} from "./candidatePresentation";

describe("candidateBindingTone", () => {
  const table: Array<[CandidateApprovalBinding, Tone]> = [
    ["pending", "warning"],
    ["approved", "success"],
    ["rejected", "danger"],
    ["legacy_unbound", "danger"],
    [null, "neutral"],
  ];

  it.each(table)("maps %s → %s", (binding, expected) => {
    expect(candidateBindingTone(binding)).toBe(expected);
  });

  it("covers every digest-aware API member exactly once", () => {
    const members = table.map(([binding]) => binding);
    expect(new Set(members).size).toBe(5);
    expect(members).toEqual(
      expect.arrayContaining([
        "pending",
        "approved",
        "rejected",
        "legacy_unbound",
        null,
      ]),
    );
  });
});

describe("asCandidateApprovalBinding", () => {
  it("preserves known members and collapses unknown/undefined to null", () => {
    expect(asCandidateApprovalBinding("pending")).toBe("pending");
    expect(asCandidateApprovalBinding("approved")).toBe("approved");
    expect(asCandidateApprovalBinding("rejected")).toBe("rejected");
    expect(asCandidateApprovalBinding("legacy_unbound")).toBe("legacy_unbound");
    expect(asCandidateApprovalBinding(null)).toBe(null);
    expect(asCandidateApprovalBinding(undefined)).toBe(null);
    expect(asCandidateApprovalBinding("other")).toBe(null);
  });
});

describe("candidateDigestPresentation", () => {
  it("shows authoritative digest only for verified candidates", () => {
    expect(
      candidateDigestPresentation({
        integrity_state: "verified",
        manifest_digest: "a".repeat(64),
        observed_manifest_digest: "b".repeat(64),
        integrity_error_code: null,
      }),
    ).toEqual({ kind: "authoritative", digest: "a".repeat(64) });
  });

  it("shows migration evidence for migration_required", () => {
    expect(
      candidateDigestPresentation({
        integrity_state: "migration_required",
        manifest_digest: null,
        observed_manifest_digest: "b".repeat(64),
        integrity_error_code: null,
      }),
    ).toEqual({ kind: "migration_evidence", digest: "b".repeat(64) });
  });

  it("shows stable error code and no digest for corrupt", () => {
    expect(
      candidateDigestPresentation({
        integrity_state: "corrupt",
        manifest_digest: "a".repeat(64),
        observed_manifest_digest: "b".repeat(64),
        integrity_error_code: "candidate_manifest_corrupt",
      }),
    ).toEqual({
      kind: "corrupt",
      errorCode: "candidate_manifest_corrupt",
    });
  });
});
