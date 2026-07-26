import { describe, expect, it, vi } from "vitest";

import { PROVIDER_POLICY_DIGEST } from "./darkIdentity";
import { ensureSessionForkAttempt } from "./sessionForkAttempt";

describe("session fork attempt", () => {
  it("reuses one immutable id, cursor, and policy for retries", () => {
    const createId = vi.fn(() => "11111111-1111-4111-8111-111111111111");
    const first = ensureSessionForkAttempt(
      null,
      {
        hermesSessionId: "agent:main:discord",
        forkPoint: "message:42",
        providerPolicyDigest: PROVIDER_POLICY_DIGEST,
      },
      createId,
    );
    const retry = ensureSessionForkAttempt(
      first,
      {
        hermesSessionId: "agent:main:discord",
        forkPoint: "message:42",
        providerPolicyDigest: PROVIDER_POLICY_DIGEST,
      },
      createId,
    );

    expect(retry).toBe(first);
    expect(createId).toHaveBeenCalledOnce();
    expect(first).toEqual({
      clientActionId: "11111111-1111-4111-8111-111111111111",
      hermesSessionId: "agent:main:discord",
      forkPoint: "message:42",
      providerPolicyDigest: PROVIDER_POLICY_DIGEST,
    });
    expect(Object.isFrozen(first)).toBe(true);
  });

  it("creates a new id only after the user changes the exact message selection", () => {
    const createId = vi
      .fn<() => string>()
      .mockReturnValueOnce("11111111-1111-4111-8111-111111111111")
      .mockReturnValueOnce("22222222-2222-4222-8222-222222222222");
    const first = ensureSessionForkAttempt(
      null,
      {
        hermesSessionId: "agent:main:discord",
        forkPoint: "message:42",
        providerPolicyDigest: PROVIDER_POLICY_DIGEST,
      },
      createId,
    );
    const changed = ensureSessionForkAttempt(
      first,
      {
        hermesSessionId: "agent:main:discord",
        forkPoint: "message:43",
        providerPolicyDigest: PROVIDER_POLICY_DIGEST,
      },
      createId,
    );

    expect(changed).not.toBe(first);
    expect(changed.clientActionId).toBe(
      "22222222-2222-4222-8222-222222222222",
    );
    expect(changed.forkPoint).toBe("message:43");
    expect(createId).toHaveBeenCalledTimes(2);
  });
});
