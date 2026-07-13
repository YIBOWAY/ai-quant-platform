import { describe, expect, it } from "vitest";
import { hermesFeatureFlags } from "./featureFlags";

const attemptedCapabilityOverrides = {
  QS_HERMES_SHELL_ENABLED: "true",
  QS_HERMES_CHAT_ENABLED: "true",
  QS_HERMES_EXECUTION_ENABLED: "true",
  QS_HERMES_UNIFIED_RESULTS_ENABLED: "true",
  QS_HERMES_LEGACY_REDIRECTS_ENABLED: "true",
};

describe("hermesFeatureFlags", () => {
  it("allows only the shell flag to vary in this slice", () => {
    expect(hermesFeatureFlags(attemptedCapabilityOverrides)).toEqual({
      shell: true,
      chat: false,
      execution: false,
      unifiedResults: false,
      legacyRedirects: false,
      deliveryState: "blocked_in_this_slice",
    });
    expect(
      hermesFeatureFlags({
        ...attemptedCapabilityOverrides,
        QS_HERMES_SHELL_ENABLED: "false",
      }),
    ).toEqual({
      shell: false,
      chat: false,
      execution: false,
      unifiedResults: false,
      legacyRedirects: false,
      deliveryState: "blocked_in_this_slice",
    });
  });

  it("defaults shell to true when the shell env var is unset", () => {
    expect(hermesFeatureFlags({}).shell).toBe(true);
  });
});
