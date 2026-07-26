import { describe, expect, it } from "vitest";

import {
  canRetryComposerAttempt,
  createComposerAttempt,
  retryComposerAttempt,
  shouldRetainComposerAttemptAfterError,
} from "./composerAttempt";

describe("composer durable retry identity", () => {
  it("reuses the original client_action_id and exact prompt", () => {
    const first = createComposerAttempt(
      "continue the managed thread",
      () => "action-original",
    );
    const retry = retryComposerAttempt(first);

    expect(retry).toBe(first);
    expect(retry).toEqual({
      prompt: "continue the managed thread",
      clientActionId: "action-original",
    });
  });

  it("retains identity after transport and 5xx failures", () => {
    expect(shouldRetainComposerAttemptAfterError(new TypeError("network"))).toBe(
      true,
    );
    expect(shouldRetainComposerAttemptAfterError({ status: 503 })).toBe(true);
    expect(shouldRetainComposerAttemptAfterError({ status: 500 })).toBe(true);
  });

  it("does not offer an unchanged retry after definitive client rejection", () => {
    expect(shouldRetainComposerAttemptAfterError({ status: 409 })).toBe(false);
    expect(shouldRetainComposerAttemptAfterError({ status: 400 })).toBe(false);
    expect(shouldRetainComposerAttemptAfterError({ status: 422 })).toBe(false);
  });

  it("only permits retry in the exact same writable Hermes Session", () => {
    const attempt = createComposerAttempt(
      "same session only",
      () => "action-session-bound",
    );
    const retry = {
      attempt,
      hermesSessionId: "web_" + "a".repeat(40),
    };

    expect(
      canRetryComposerAttempt(retry, retry.hermesSessionId, true),
    ).toBe(true);
    expect(
      canRetryComposerAttempt(retry, "web_" + "b".repeat(40), true),
    ).toBe(false);
    expect(
      canRetryComposerAttempt(retry, retry.hermesSessionId, false),
    ).toBe(false);
    expect(canRetryComposerAttempt(null, retry.hermesSessionId, true)).toBe(
      false,
    );
  });
});
