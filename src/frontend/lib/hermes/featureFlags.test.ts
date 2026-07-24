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
  it("allows shell, local chat unlock, and Agent Studio cutover to vary", () => {
    expect(hermesFeatureFlags(attemptedCapabilityOverrides)).toEqual({
      shell: true,
      sessionRead: true,
      chat: true,
      execution: false,
      approvalMutations: false,
      unifiedResultsCutoverAccepted: false,
      legacyRedirects: false,
      agentStudioRedirect: true,
      deliveryState: "local_mutation_authorized",
    });
    expect(
      hermesFeatureFlags({
        ...attemptedCapabilityOverrides,
        QS_HERMES_SHELL_ENABLED: "false",
        QS_HERMES_CHAT_ENABLED: "false",
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

  it("defaults shell to true and chat to false when env vars are unset", () => {
    expect(hermesFeatureFlags({}).shell).toBe(true);
    expect(hermesFeatureFlags({}).chat).toBe(false);
    expect(hermesFeatureFlags({}).agentStudioRedirect).toBe(false);
    expect(hermesFeatureFlags({}).deliveryState).toBe("blocked_in_this_slice");
  });
});
