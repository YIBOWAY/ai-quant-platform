import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError, apiRequestOnce } from "./apiClient";
import { ensureOwnerSession, ownerPostJson } from "./hermes/workspaceClient";
import {
  hangLibraryCandidate,
  loadVerifiedLibraryCandidates,
  resolveLibraryHangOutcome,
} from "./researchLibrary";

vi.mock("./apiClient", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./apiClient")>()),
  apiRequestOnce: vi.fn(),
}));
vi.mock("./hermes/workspaceClient", () => ({
  ensureOwnerSession: vi.fn(),
  ownerPostJson: vi.fn(),
}));

const mockedApiRequest = vi.mocked(apiRequestOnce);
const mockedEnsureOwnerSession = vi.mocked(ensureOwnerSession);
const mockedOwnerPostJson = vi.mocked(ownerPostJson);

describe("research library authority", () => {
  beforeEach(() => {
    mockedApiRequest.mockReset();
    mockedEnsureOwnerSession.mockReset();
    mockedOwnerPostJson.mockReset();
  });

  it("loads only unbound verified candidates with a canonical source digest", async () => {
    const digest = "a".repeat(64);
    mockedApiRequest.mockResolvedValue({
      candidates: [
        {
          candidate_id: "ready",
          source_digest: digest,
          status: "verified",
          sleeve_id: null,
          activation_eligibility: { eligible: true, reason: null },
        },
        {
          candidate_id: "review-only",
          source_digest: digest,
          status: "verified",
          sleeve_id: null,
          activation_eligibility: {
            eligible: false,
            reason: "cost_sensitivity_failed",
          },
        },
        { candidate_id: "unassessed", source_digest: digest, status: "verified", sleeve_id: null },
        { candidate_id: "hung", source_digest: digest, status: "verified", sleeve_id: "sleeve-1" },
        { candidate_id: "draft", source_digest: digest, status: "candidate_ready", sleeve_id: null },
        { candidate_id: "bad-digest", source_digest: "abc", status: "verified", sleeve_id: null },
      ],
    });

    await expect(loadVerifiedLibraryCandidates()).resolves.toEqual([
      expect.objectContaining({ candidate_id: "ready", source_digest: digest }),
      expect.objectContaining({
        candidate_id: "review-only",
        activation_eligibility: {
          eligible: false,
          reason: "cost_sensitivity_failed",
        },
      }),
    ]);
    expect(mockedApiRequest).toHaveBeenCalledOnce();
    expect(mockedApiRequest).toHaveBeenCalledWith("/api/assistant/remote/book");
    expect(mockedOwnerPostJson).not.toHaveBeenCalled();
  });

  it("hangs through the one digest-bound mutation interface", async () => {
    const digest = "b".repeat(64);
    mockedEnsureOwnerSession.mockResolvedValue({
      mutation_enabled: true,
      security_ready: true,
      session_id: "owner-session",
    });
    mockedOwnerPostJson.mockResolvedValue({
      already_hung: true,
      candidate_id: "ready",
      sleeve_id: "sleeve-1",
      source_digest: digest,
      status: "hung",
    });

    await expect(
      hangLibraryCandidate({ candidate_id: "ready", source_digest: digest }),
    ).resolves.toMatchObject({ already_hung: true, sleeve_id: "sleeve-1" });
    expect(mockedEnsureOwnerSession).toHaveBeenCalledOnce();
    expect(mockedOwnerPostJson).toHaveBeenCalledOnce();
    expect(mockedOwnerPostJson).toHaveBeenCalledWith(
      "/api/assistant/remote/hang",
      {
        candidate_id: "ready",
        expected_source_digest: digest,
      },
      expect.any(AbortSignal),
    );
  });

  it.each([
    ["hung", "sleeve-1", "resolved_hung"],
    ["verified", null, "still_verified"],
    ["failed", null, "still_unknown"],
  ] as const)("resolves an unknown outcome as %s", async (status, sleeveId, expected) => {
    const digest = "d".repeat(64);
    mockedApiRequest.mockResolvedValue({
      candidates: [
        {
          candidate_id: "ready",
          source_digest: digest,
          status,
          sleeve_id: sleeveId,
        },
      ],
    });

    await expect(
      resolveLibraryHangOutcome({ candidate_id: "ready", source_digest: digest }),
    ).resolves.toBe(expected);
    expect(mockedOwnerPostJson).not.toHaveBeenCalled();
  });

  it("surfaces a single uncertain hang without retrying the mutation", async () => {
    const digest = "c".repeat(64);
    mockedEnsureOwnerSession.mockResolvedValue({
      mutation_enabled: true,
      security_ready: true,
      session_id: "owner-session",
    });
    mockedOwnerPostJson.mockRejectedValue(
      Object.assign(new Error("response lost"), {
        status: 503,
        code: "hang_account_outcome_unknown",
      }),
    );

    await expect(
      hangLibraryCandidate({ candidate_id: "ready", source_digest: digest }),
    ).rejects.toMatchObject({
      name: "ApiClientError",
      outcome: "outcome_unknown",
    } satisfies Partial<ApiClientError>);
    expect(mockedOwnerPostJson).toHaveBeenCalledOnce();
  });

  it("maps a lost network response to outcome_unknown without retry", async () => {
    const digest = "e".repeat(64);
    mockedEnsureOwnerSession.mockResolvedValue({
      mutation_enabled: true,
      security_ready: true,
      session_id: "owner-session",
    });
    mockedOwnerPostJson.mockRejectedValue(new TypeError("network disconnected"));

    await expect(
      hangLibraryCandidate({ candidate_id: "ready", source_digest: digest }),
    ).rejects.toMatchObject({
      name: "ApiClientError",
      outcome: "outcome_unknown",
    } satisfies Partial<ApiClientError>);
    expect(mockedOwnerPostJson).toHaveBeenCalledOnce();
  });
});
