import type { HermesFeatureFlags } from "./types";

/**
 * Shell is the only env-configurable capability in this slice.
 * chat / execution / approvalMutations / unifiedResults / legacyRedirects are hard false and
 * must not be read from environment variables.
 * deliveryState is a versioned delivery fact, never a live probe.
 */
export function hermesFeatureFlags(
  env: { [key: string]: string | undefined } = process.env,
): HermesFeatureFlags {
  return {
    shell: env.QS_HERMES_SHELL_ENABLED !== "false",
    sessionRead: true,
    chat: false,
    execution: false,
    approvalMutations: false,
    unifiedResults: false,
    legacyRedirects: false,
    deliveryState: "blocked_in_this_slice",
  } as const;
}
