import { describe, expect, it } from "vitest";
import { hermesFeatureFlags } from "./featureFlags";

const attemptedCapabilityOverrides = {
  QS_HERMES_SHELL_ENABLED: "true",
  QS_HERMES_CHAT_ENABLED: "true",
  QS_HERMES_EXECUTION_ENABLED: "true",
  QS_HERMES_APPROVAL_MUTATIONS_ENABLED: "true",
  QS_HERMES_UNIFIED_RESULTS_ENABLED: "true",
  QS_HERMES_LEGACY_REDIRECTS_ENABLED: "true",
  QS_HERMES_AGENT_STUDIO_REDIRECT_ENABLED: "true",
};

describe("hermesFeatureFlags", () => {
  it("allows only the shell and independent Agent Studio cutover flags to vary", () => {
    expect(hermesFeatureFlags(attemptedCapabilityOverrides)).toEqual({
      shell: true,
      sessionRead: true,
      chat: false,
      execution: false,
      approvalMutations: false,
      unifiedResultsCutoverAccepted: false,
      legacyRedirects: false,
      agentStudioRedirect: true,
      deliveryState: "blocked_in_this_slice",
    });
    expect(
      hermesFeatureFlags({
        ...attemptedCapabilityOverrides,
        QS_HERMES_SHELL_ENABLED: "false",
      }),
    ).toEqual({
      shell: false,
      sessionRead: true,
      chat: false,
      execution: false,
      approvalMutations: false,
      unifiedResultsCutoverAccepted: false,
      legacyRedirects: false,
      agentStudioRedirect: true,
      deliveryState: "blocked_in_this_slice",
    });
  });

  it("defaults shell to true when the shell env var is unset", () => {
    expect(hermesFeatureFlags({}).shell).toBe(true);
    expect(hermesFeatureFlags({}).agentStudioRedirect).toBe(false);
  });
});
