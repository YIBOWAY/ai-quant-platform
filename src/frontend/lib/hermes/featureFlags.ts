import type { HermesFeatureFlags } from "./types";

/**
 * Shell, Agent Studio cutover, and local chat unlock are env-configurable.
 * chat defaults off; set QS_HERMES_CHAT_ENABLED=true only on the authorized
 * local single-user path (paired with QS_LOCAL_MUTATION_* on the API).
 * execution / approvalMutations / unifiedResultsCutoverAccepted / legacyRedirects
 * stay hard false. deliveryState is a versioned delivery fact, never a live probe.
 */
export function hermesFeatureFlags(
  env: { [key: string]: string | undefined } = process.env,
): HermesFeatureFlags {
  const chat = env.QS_HERMES_CHAT_ENABLED === "true";
  return {
    shell: env.QS_HERMES_SHELL_ENABLED !== "false",
    sessionRead: true,
    chat,
    execution: false,
    approvalMutations: false,
    // The read-only preview is intentionally visible for acceptance. This flag
    // records cutover acceptance; it is not a visibility switch.
    unifiedResultsCutoverAccepted: false,
    legacyRedirects: false,
    agentStudioRedirect:
      env.QS_HERMES_AGENT_STUDIO_REDIRECT_ENABLED === "true",
    deliveryState: chat ? "local_mutation_authorized" : "blocked_in_this_slice",
  } as const;
}
