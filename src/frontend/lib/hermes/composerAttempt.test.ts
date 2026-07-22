import { describe, expect, it } from "vitest";

import {
  createComposerAttempt,
  retryComposerAttempt,
  shouldRetainComposerAttemptAfterError,
} from "./composerAttempt";

describe("composer outcome_unknown retry identity", () => {
  it("reuses the original client_action_id and prompt", () => {
    const first = createComposerAttempt(
      "continue the managed thread",
      () => "action-original",
    );
    const retry = retryComposerAttempt(first);

    expect(retry).toEqual(first);
    expect(retry.clientActionId).toBe("action-original");
  });

  it("retains identity after unknown/5xx failures but not definitive 4xx", () => {
    expect(shouldRetainComposerAttemptAfterError(new TypeError("network"))).toBe(
      true,
    );
    expect(shouldRetainComposerAttemptAfterError({ status: 503 })).toBe(true);
    expect(shouldRetainComposerAttemptAfterError({ status: 409 })).toBe(false);
    expect(shouldRetainComposerAttemptAfterError({ status: 400 })).toBe(false);
  });
});
