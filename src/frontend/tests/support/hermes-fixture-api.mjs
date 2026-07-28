/**
 * Loopback GET-only Hermes workbench fixture API.
 * Serves combined fixtures for hermetic Playwright runs.
 * No platform modules, database, provider, or external network.
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE_DIR = path.resolve(
  __dirname,
  "..",
  "fixtures",
  "hermes-workbench",
);

export const HERMES_WORKBENCH_FIXTURE_NAMES = Object.freeze([
  "normal",
  "degraded",
  "offline",
  "empty",
  "long-content",
]);

const ROOT_KEYS = Object.freeze([
  "schema_version",
  "health",
  "artifacts",
  "candidates",
  "factors",
]);

const FACTOR_REQUIRED_KEYS = Object.freeze([
  "factor_id",
  "factor_name",
  "factor_version",
  "lookback",
  "direction",
  "description",
  "origin",
]);
const FACTOR_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$/;
const MAX_FACTOR_ROWS = 2_000;
const MAX_FACTOR_TEXT_CHARS = 1_024;

/** Eleven required CandidateReadItem keys (nullable ≠ omitted). */
export const CANDIDATE_REQUIRED_KEYS = Object.freeze([
  "candidate_id",
  "artifact_type",
  "goal",
  "universe",
  "status",
  "integrity_state",
  "manifest_digest",
  "observed_manifest_digest",
  "approval_binding",
  "approval_enabled",
  "integrity_error_code",
]);

const ARTIFACT_REQUIRED_KEYS = Object.freeze([
  "schema_version",
  "read_status",
  "as_of",
  "items",
  "sources",
  "warnings",
]);

const HEALTH_REQUIRED_KEYS = Object.freeze([
  "status",
  "app_name",
  "environment",
  "data_provider",
]);

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

/**
 * Shared contract validator for combined workbench fixtures.
 * Rejects unknown root keys, incomplete candidate rows, and malformed envelopes.
 */
export function validateCombinedFixture(payload) {
  assert(isPlainObject(payload), "fixture payload must be an object");
  const keys = Object.keys(payload).sort();
  assert(
    keys.length === ROOT_KEYS.length &&
      ROOT_KEYS.every((key) => Object.hasOwn(payload, key)),
    `fixture root must have exactly ${ROOT_KEYS.join(", ")}; got ${keys.join(", ")}`,
  );

  assert(
    typeof payload.schema_version === "string" && payload.schema_version.length > 0,
    "schema_version must be a non-empty string",
  );

  assert(isPlainObject(payload.health), "health must be an object");
  for (const key of HEALTH_REQUIRED_KEYS) {
    assert(Object.hasOwn(payload.health, key), `health missing required key: ${key}`);
  }
  assert(
    isPlainObject(payload.health.data_provider),
    "health.data_provider must be an object",
  );

  assert(isPlainObject(payload.artifacts), "artifacts must be an object");
  for (const key of ARTIFACT_REQUIRED_KEYS) {
    assert(
      Object.hasOwn(payload.artifacts, key),
      `artifacts missing required key: ${key}`,
    );
  }
  assert(Array.isArray(payload.artifacts.items), "artifacts.items must be an array");
  assert(Array.isArray(payload.artifacts.sources), "artifacts.sources must be an array");
  assert(
    Array.isArray(payload.artifacts.warnings),
    "artifacts.warnings must be an array",
  );

  assert(isPlainObject(payload.candidates), "candidates must be an object");
  assert(
    Array.isArray(payload.candidates.candidates),
    "candidates.candidates must be an array",
  );

  for (const [index, candidate] of payload.candidates.candidates.entries()) {
    assert(
      isPlainObject(candidate),
      `candidates.candidates[${index}] must be an object`,
    );
    for (const key of CANDIDATE_REQUIRED_KEYS) {
      assert(
        Object.hasOwn(candidate, key),
        `candidates.candidates[${index}] missing required key: ${key}`,
      );
    }
    assert(
      typeof candidate.candidate_id === "string" && candidate.candidate_id.length > 0,
      `candidates.candidates[${index}].candidate_id must be a non-empty string`,
    );
  }

  assert(isPlainObject(payload.factors), "factors must be an object");
  assert(
    payload.factors.status === 200 || payload.factors.status === 503,
    "factors.status must be 200 or 503",
  );
  assert(isPlainObject(payload.factors.body), "factors.body must be an object");
  if (payload.factors.status === 503) {
    assert(
      typeof payload.factors.body.detail === "string" &&
        payload.factors.body.detail.length > 0 &&
        payload.factors.body.detail.length <= MAX_FACTOR_TEXT_CHARS,
      "degraded factors.body.detail must be a bounded non-empty string",
    );
    assert(
      !Object.hasOwn(payload.factors.body, "factors"),
      "degraded factors response must not masquerade as a factor catalog",
    );
  } else {
    assert(
      Array.isArray(payload.factors.body.factors),
      "normal factors.body.factors must be an array",
    );
    assert(
      payload.factors.body.factors.length <= MAX_FACTOR_ROWS,
      `normal factor catalog exceeds ${MAX_FACTOR_ROWS} rows`,
    );
    const factorIds = new Set();
    for (const [index, factor] of payload.factors.body.factors.entries()) {
      assert(isPlainObject(factor), `factors.body.factors[${index}] must be an object`);
      for (const key of FACTOR_REQUIRED_KEYS) {
        assert(
          Object.hasOwn(factor, key),
          `factors.body.factors[${index}] missing required key: ${key}`,
        );
      }
      assert(
        typeof factor.factor_id === "string" && FACTOR_ID_PATTERN.test(factor.factor_id),
        `factors.body.factors[${index}].factor_id is invalid`,
      );
      assert(!factorIds.has(factor.factor_id), `duplicate factor_id: ${factor.factor_id}`);
      factorIds.add(factor.factor_id);
      for (const key of ["factor_name", "factor_version", "description"]) {
        assert(
          typeof factor[key] === "string" &&
            factor[key].length > 0 &&
            factor[key].length <= MAX_FACTOR_TEXT_CHARS,
          `factors.body.factors[${index}].${key} must be a bounded non-empty string`,
        );
      }
      assert(
        Number.isInteger(factor.lookback) && factor.lookback >= 1 && factor.lookback <= 100_000,
        `factors.body.factors[${index}].lookback is invalid`,
      );
      assert(
        ["higher_is_better", "lower_is_better", "neutral"].includes(factor.direction),
        `factors.body.factors[${index}].direction is invalid`,
      );
      assert(
        factor.origin === "builtin" || factor.origin === "promoted",
        `factors.body.factors[${index}].origin is invalid`,
      );
    }
  }

  return payload;
}

export function loadFixture(name) {
  if (!HERMES_WORKBENCH_FIXTURE_NAMES.includes(name)) {
    throw new Error(
      `unknown hermes workbench fixture: ${name}; allowlist=${HERMES_WORKBENCH_FIXTURE_NAMES.join(",")}`,
    );
  }
  const fixturePath = path.join(FIXTURE_DIR, `${name}.json`);
  let raw;
  try {
    raw = fs.readFileSync(fixturePath, "utf8");
  } catch (error) {
    throw new Error(`failed to read fixture ${name}: ${error.message}`);
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (error) {
    throw new Error(`fixture ${name} is not valid JSON: ${error.message}`);
  }
  return validateCombinedFixture(parsed);
}

/**
 * Create a GET-only HTTP server bound by the caller.
 * Accepts only a validated combined fixture object.
 */
export function createFixtureServer(
  fixture,
  { includePersistedSession = false } = {},
) {
  const validated = validateCombinedFixture(
    typeof structuredClone === "function"
      ? structuredClone(fixture)
      : JSON.parse(JSON.stringify(fixture)),
  );

  const routes = new Map([
    ["/api/health", validated.health],
    [
      "/api/settings",
      {
        safety: validated.health.safety,
        settings: {},
      },
    ],
    ["/api/hermes/artifacts", validated.artifacts],
    ["/api/agent/candidates", validated.candidates],
  ]);

  const candidateById = new Map(
    validated.candidates.candidates.map((candidate) => [
      candidate.candidate_id,
      candidate,
    ]),
  );

  const persistedSession = {
    id: "fixture-long-session",
    title: "Fixture long session",
    source: "fixture",
    model: "fixture-model",
    message_count: 48,
    last_active: "2026-07-16T00:47:00Z",
    preview: "Deterministic long transcript for session navigation testing.",
    parent_session_id: null,
    ended_at: null,
  };
  const persistedMessages = Array.from({ length: 48 }, (_, index) => ({
    id: `fixture-message-${String(index + 1).padStart(2, "0")}`,
    role: index % 2 === 0 ? "user" : "assistant",
    content:
      index === 47
        ? "Latest fixture message"
        : `Fixture transcript message ${index + 1}: ${"bounded research context ".repeat(4)}`,
    timestamp: `2026-07-16T00:${String(index).padStart(2, "0")}:00Z`,
  }));
  const gatewayStatus = {
    read_status: "available",
    connected: true,
    model: "fixture-model",
    session_api_available: true,
    chat_write_ready: false,
    features: { session_resources: true },
    upstream_blockers: ["fixture_write_disabled"],
    platform_delivery_blockers: ["fixture_write_disabled"],
    blockers: ["fixture_write_disabled"],
    warnings: [],
  };
  const sessionsResponse = {
    read_status: "available",
    sessions: [persistedSession],
    limit: 50,
    offset: 0,
    has_more: false,
    warnings: [],
  };

  /** Detail read model synthesized from list rows (GET-only, no mutations). */
  function candidateDetailResponse(candidate) {
    return {
      candidate_id: candidate.candidate_id,
      metadata: {
        goal: candidate.goal ?? null,
        artifact_type: candidate.artifact_type ?? null,
        universe: candidate.universe ?? [],
      },
      source_preview:
        candidate.integrity_state === "verified"
          ? `def fixture_factor(frame):\n    return frame["close"].pct_change()`
          : null,
      // Production excludes global/legacy audit rows that are not bound to the
      // exact candidate digest. The fixture must preserve that authority rule.
      audit: [],
      reviews:
        candidate.status === "approved"
          ? [
              JSON.stringify({
                candidate_id: candidate.candidate_id,
                decision: "approve",
                note: "fixture review",
                manifest_digest: candidate.manifest_digest,
              }),
            ]
          : [],
      evidence_truncated: false,
      integrity_state: candidate.integrity_state,
      manifest_digest: candidate.manifest_digest,
      observed_manifest_digest: candidate.observed_manifest_digest,
      approval_binding: candidate.approval_binding,
      approval_enabled: candidate.approval_enabled,
      integrity_error_code: candidate.integrity_error_code,
      status: candidate.status,
      safety: validated.candidates.safety ?? validated.health.safety ?? null,
    };
  }

  const server = http.createServer((req, res) => {
    const method = req.method ?? "GET";
    const url = new URL(req.url ?? "/", "http://127.0.0.1");
    const pathname = url.pathname;

    const finish = (status, body) => {
      const payload =
        body === undefined || body === null
          ? ""
          : typeof body === "string"
            ? body
            : JSON.stringify(body);
      res.statusCode = status;
      res.setHeader("Cache-Control", "no-store");
      // Browser client components (Gate 2 detail re-fetch) need CORS on loopback.
      res.setHeader("Access-Control-Allow-Origin", "*");
      res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
      res.setHeader("Access-Control-Allow-Headers", "accept, content-type");
      if (payload) {
        res.setHeader("Content-Type", "application/json; charset=utf-8");
      }
      res.end(payload);
      console.log(`${method} ${pathname} ${status}`);
    };

    // Preflight for browser GET from the Next origin.
    if (method === "OPTIONS") {
      finish(204, null);
      return;
    }

    // GET-only fixture surface — review POST remains intentionally unavailable.
    if (method !== "GET") {
      finish(405, { detail: "method_not_allowed" });
      return;
    }

    if (includePersistedSession && pathname === "/api/hermes/gateway") {
      finish(200, gatewayStatus);
      return;
    }

    if (includePersistedSession && pathname === "/api/hermes/sessions") {
      finish(200, sessionsResponse);
      return;
    }

    const sessionMessagesMatch = pathname.match(
      /^\/api\/hermes\/sessions\/([^/]+)\/messages$/,
    );
    if (includePersistedSession && sessionMessagesMatch) {
      const sessionId = decodeURIComponent(sessionMessagesMatch[1]);
      if (sessionId !== persistedSession.id) {
        finish(404, { detail: "session_not_found" });
        return;
      }
      finish(200, {
        read_status: "available",
        session_id: sessionId,
        messages: persistedMessages,
        omitted_message_count: 0,
        warnings: [],
      });
      return;
    }

    const sessionDetailMatch = pathname.match(
      /^\/api\/hermes\/sessions\/([^/]+)$/,
    );
    if (includePersistedSession && sessionDetailMatch) {
      const sessionId = decodeURIComponent(sessionDetailMatch[1]);
      if (sessionId !== persistedSession.id) {
        finish(404, { detail: "session_not_found" });
        return;
      }
      finish(200, {
        read_status: "available",
        session: persistedSession,
        warnings: [],
      });
      return;
    }

    const detailMatch = pathname.match(
      /^\/api\/agent\/candidates\/([^/]+)$/,
    );
    if (detailMatch) {
      const candidateId = decodeURIComponent(detailMatch[1]);
      const candidate = candidateById.get(candidateId);
      if (!candidate) {
        finish(404, { detail: "candidate_not_found" });
        return;
      }
      finish(200, candidateDetailResponse(candidate));
      return;
    }

    if (pathname === "/api/factors") {
      finish(validated.factors.status, validated.factors.body);
      return;
    }

    if (!routes.has(pathname)) {
      finish(404, { detail: "not_found" });
      return;
    }

    finish(200, routes.get(pathname));
  });

  return server;
}

export function startFixtureServer(port, fixtureName) {
  const fixture = loadFixture(fixtureName);
  const server = createFixtureServer(fixture, {
    includePersistedSession: fixtureName === "normal",
  });
  return new Promise((resolve, reject) => {
    const onError = (error) => {
      server.off("error", onError);
      reject(error);
    };
    server.once("error", onError);
    server.listen(port, "127.0.0.1", () => {
      server.off("error", onError);
      resolve(server);
    });
  });
}

function main(argv) {
  const [, , portRaw, fixtureName] = argv;
  if (!portRaw || !fixtureName) {
    console.error("usage: node hermes-fixture-api.mjs <port> <fixture>");
    process.exit(2);
  }
  const port = Number(portRaw);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    console.error("port must be an integer TCP port between 1 and 65535");
    process.exit(2);
  }

  let fixture;
  try {
    fixture = loadFixture(fixtureName);
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(2);
  }

  const server = createFixtureServer(fixture, {
    includePersistedSession: fixtureName === "normal",
  });
  server.on("error", (error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
  });
  server.listen(port, "127.0.0.1", () => {
    console.log(
      `hermes-fixture-api listening on 127.0.0.1:${port} fixture=${fixtureName}`,
    );
  });
}

const isDirectRun =
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isDirectRun) {
  main(process.argv);
}
