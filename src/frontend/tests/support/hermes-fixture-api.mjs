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
]);

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
export function createFixtureServer(fixture) {
  const validated = validateCombinedFixture(
    typeof structuredClone === "function"
      ? structuredClone(fixture)
      : JSON.parse(JSON.stringify(fixture)),
  );

  const routes = new Map([
    ["/api/health", validated.health],
    ["/api/hermes/artifacts", validated.artifacts],
    ["/api/agent/candidates", validated.candidates],
  ]);

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
      if (payload) {
        res.setHeader("Content-Type", "application/json; charset=utf-8");
      }
      res.end(payload);
      console.log(`${method} ${pathname} ${status}`);
    };

    if (method !== "GET") {
      finish(405, { detail: "method_not_allowed" });
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
  const server = createFixtureServer(fixture);
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

  const server = createFixtureServer(fixture);
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
