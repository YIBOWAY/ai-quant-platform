import { describe, expect, it } from "vitest";

import type { AgentCandidateDetailResponse } from "@/lib/api";
import {
  canReviewCandidateDetail,
  listRowShowsGate2Controls,
} from "./gate2Review";

const DIGEST_A = "a".repeat(64);
const DIGEST_B = "294bbe7b846ae86384e56deae8ba8df2576ac6ffa8a5937e4f82a2352fdd8558";

function detail(
  overrides: Partial<AgentCandidateDetailResponse> = {},
): AgentCandidateDetailResponse {
  return {
    candidate_id: "factor-momentum_20d_reversal-323b045e4b",
    metadata: null,
    source_preview: null,
    audit: [],
    reviews: [],
    integrity_state: "verified",
    manifest_digest: DIGEST_B,
    observed_manifest_digest: null,
    approval_binding: "pending",
    approval_enabled: true,
    integrity_error_code: null,
    status: "pending",
    safety: {
      dry_run: true,
      paper_trading: true,
      live_trading_enabled: false,
      kill_switch: true,
      bind_address: "127.0.0.1",
    },
    ...overrides,
  };
}

describe("canReviewCandidateDetail (Gate 2 CAS)", () => {
  it("accepts verified pending detail with approval_enabled and 64-hex digest", () => {
    expect(canReviewCandidateDetail(detail())).toBe(true);
    expect(canReviewCandidateDetail(detail({ manifest_digest: DIGEST_A }))).toBe(
      true,
    );
  });

  it("rejects missing detail", () => {
    expect(canReviewCandidateDetail(undefined)).toBe(false);
    expect(canReviewCandidateDetail(null)).toBe(false);
  });

  it("rejects when approval_enabled is not true", () => {
    expect(canReviewCandidateDetail(detail({ approval_enabled: false }))).toBe(
      false,
    );
  });

  it("rejects non-pending status or binding", () => {
    expect(canReviewCandidateDetail(detail({ status: "approved" }))).toBe(false);
    expect(canReviewCandidateDetail(detail({ status: "rejected" }))).toBe(false);
    expect(canReviewCandidateDetail(detail({ status: null }))).toBe(false);
    expect(
      canReviewCandidateDetail(detail({ approval_binding: "approved" })),
    ).toBe(false);
    expect(
      canReviewCandidateDetail(detail({ approval_binding: "legacy_unbound" })),
    ).toBe(false);
    expect(canReviewCandidateDetail(detail({ approval_binding: null }))).toBe(
      false,
    );
  });

  it("rejects migration_required and corrupt integrity (no buttons path)", () => {
    expect(
      canReviewCandidateDetail(
        detail({
          integrity_state: "migration_required",
          manifest_digest: null,
          observed_manifest_digest: DIGEST_A,
          approval_enabled: false,
        }),
      ),
    ).toBe(false);
    expect(
      canReviewCandidateDetail(
        detail({
          integrity_state: "corrupt",
          manifest_digest: null,
          integrity_error_code: "manifest_mismatch",
          approval_enabled: false,
        }),
      ),
    ).toBe(false);
  });

  it("rejects non-64-hex or missing digests (never invent from list alone)", () => {
    expect(canReviewCandidateDetail(detail({ manifest_digest: null }))).toBe(
      false,
    );
    expect(canReviewCandidateDetail(detail({ manifest_digest: "" }))).toBe(
      false,
    );
    expect(
      canReviewCandidateDetail(detail({ manifest_digest: "not-a-digest" })),
    ).toBe(false);
    expect(
      canReviewCandidateDetail(detail({ manifest_digest: "A".repeat(64) })),
    ).toBe(false); // uppercase rejected; API uses lowercase hex
    expect(
      canReviewCandidateDetail(detail({ manifest_digest: "a".repeat(63) })),
    ).toBe(false);
  });
});

describe("listRowShowsGate2Controls", () => {
  it("shows controls only for approval_enabled + verified + pending list rows", () => {
    expect(
      listRowShowsGate2Controls({
        approval_enabled: true,
        status: "pending",
        integrity_state: "verified",
      }),
    ).toBe(true);
  });

  it("hides controls for migration_required / corrupt / disabled approval", () => {
    expect(
      listRowShowsGate2Controls({
        approval_enabled: false,
        status: "pending",
        integrity_state: "verified",
      }),
    ).toBe(false);
    expect(
      listRowShowsGate2Controls({
        approval_enabled: true,
        status: "pending",
        integrity_state: "migration_required",
      }),
    ).toBe(false);
    expect(
      listRowShowsGate2Controls({
        approval_enabled: true,
        status: "pending",
        integrity_state: "corrupt",
      }),
    ).toBe(false);
    expect(
      listRowShowsGate2Controls({
        approval_enabled: true,
        status: "approved",
        integrity_state: "verified",
      }),
    ).toBe(false);
  });
});
