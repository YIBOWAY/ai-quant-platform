import type { HermesFeatureFlags } from "./types";

/**
 * Shell and the page-scoped Agent Studio cutover are the only env-configurable
 * flags. The cutover defaults off and never enables a mutation capability.
 * chat / execution / approvalMutations / unifiedResultsCutoverAccepted / legacyRedirects are hard false and
 * must not be read from environment variables. Unified Results stays false until
 * live real-data acceptance verifies the catalog and exact run-link boundary.
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
    // The read-only preview is intentionally visible for acceptance. This flag
    // records cutover acceptance; it is not a visibility switch.
    unifiedResultsCutoverAccepted: false,
    legacyRedirects: false,
    agentStudioRedirect:
      env.QS_HERMES_AGENT_STUDIO_REDIRECT_ENABLED === "true",
    deliveryState: "blocked_in_this_slice",
  } as const;
}
