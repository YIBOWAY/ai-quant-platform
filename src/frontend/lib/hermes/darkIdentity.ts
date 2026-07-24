/**
 * Dark Identity Profile constants mirrored from platform
 * `quant_system.hermes.dark_identity_profile` for L2a-Send FE preflight.
 * FE never sends store owner/policy/ttl — only the locked digest on create.
 */

export const PLATFORM_WORKSPACE_ID = "ws-local-main" as const;

/** SHA-256 of store-canonical provider_policy JSON (locked). */
export const PROVIDER_POLICY_DIGEST =
  "be9265ec683224ba28643b01938dba87d2642944f3a0516ccb9ff0126f872e31" as const;

export const PAYLOAD_TTL_DAYS = 7 as const;

/** Chat rail hard cap (UTF-8 bytes) — FE, BFF, and dispatch adapter. */
export const CHAT_PROMPT_MAX_BYTES = 16_384 as const;

export const CSRF_COOKIE_NAME = "qs_aw_csrf" as const;
export const CSRF_HEADER_NAME = "X-CSRF-Token" as const;

export const MANAGED_SESSION_STORAGE_KEY =
  "qs.hermes.l2a.managed_session_ref" as const;
