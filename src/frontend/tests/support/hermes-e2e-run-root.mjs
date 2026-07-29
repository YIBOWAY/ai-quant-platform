import fs from "node:fs";
import path from "node:path";

export const E2E_RUN_PROVENANCE_FILE = ".hermes-playwright-run-root.json";

const RUN_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/;
const PROVENANCE_SCHEMA = "hermes-playwright-run-root.v1";

function requireSafeRunId(rawRunId, backendPort, frontendPort, processId) {
  const candidate =
    rawRunId === undefined
      ? `${backendPort}-${frontendPort}-pid${processId}`
      : rawRunId;
  if (typeof candidate !== "string" || !RUN_ID_PATTERN.test(candidate)) {
    throw new Error(
      "PW_E2E_RUN_ID must match /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/",
    );
  }
  return candidate;
}

function assertBoundedChild(baseRoot, dataRoot) {
  const relative = path.relative(baseRoot, dataRoot);
  if (
    relative === "" ||
    relative === "." ||
    relative.startsWith(`..${path.sep}`) ||
    relative === ".." ||
    path.isAbsolute(relative)
  ) {
    throw new Error("Playwright data root must be one child of its owned base");
  }
  if (relative.includes(path.sep)) {
    throw new Error("Playwright data root must not contain nested path segments");
  }
}

export function buildE2ERunIdentity({
  baseRoot,
  rawRunId,
  backendPort,
  frontendPort,
  processId,
}) {
  const resolvedBaseRoot = path.resolve(baseRoot);
  const runId = requireSafeRunId(
    rawRunId,
    backendPort,
    frontendPort,
    processId,
  );
  const dataRoot = path.resolve(resolvedBaseRoot, runId);
  assertBoundedChild(resolvedBaseRoot, dataRoot);
  return Object.freeze({
    backendPort,
    baseRoot: resolvedBaseRoot,
    dataRoot,
    frontendPort,
    runId,
  });
}

function expectedProvenance(identity, fixture, ownerToken) {
  return {
    backend_port: identity.backendPort,
    data_root: identity.dataRoot,
    fixture,
    frontend_port: identity.frontendPort,
    owner_token: ownerToken,
    run_id: identity.runId,
    schema_version: PROVENANCE_SCHEMA,
  };
}

function sameProvenance(actual, expected) {
  return (
    actual !== null &&
    typeof actual === "object" &&
    !Array.isArray(actual) &&
    Object.keys(actual).length === Object.keys(expected).length &&
    Object.entries(expected).every(([key, value]) => actual[key] === value)
  );
}

export function prepareE2ERunRoot(
  identity,
  { fixture = null, ownerToken },
) {
  if (typeof ownerToken !== "string" || ownerToken.length === 0) {
    throw new Error("Playwright data-root owner token is required");
  }
  assertBoundedChild(identity.baseRoot, identity.dataRoot);
  fs.mkdirSync(identity.baseRoot, { recursive: true, mode: 0o700 });
  fs.mkdirSync(identity.dataRoot, { mode: 0o700 });
  try {
    const provenance = expectedProvenance(identity, fixture, ownerToken);
    fs.writeFileSync(
      path.join(identity.dataRoot, E2E_RUN_PROVENANCE_FILE),
      `${JSON.stringify(provenance)}\n`,
      {
        encoding: "utf8",
        flag: "wx",
        mode: 0o600,
      },
    );
    return provenance;
  } catch (error) {
    fs.rmdirSync(identity.dataRoot);
    throw error;
  }
}

export function cleanupE2ERunRoot(
  identity,
  { fixture = null, ownerToken },
) {
  if (typeof ownerToken !== "string" || ownerToken.length === 0) {
    throw new Error("Playwright data-root owner token is required");
  }
  assertBoundedChild(identity.baseRoot, identity.dataRoot);
  const rootStat = fs.lstatSync(identity.dataRoot);
  if (!rootStat.isDirectory() || rootStat.isSymbolicLink()) {
    throw new Error("Playwright data root is not an owned directory");
  }

  const provenancePath = path.join(
    identity.dataRoot,
    E2E_RUN_PROVENANCE_FILE,
  );
  const provenanceStat = fs.lstatSync(provenancePath);
  if (!provenanceStat.isFile() || provenanceStat.isSymbolicLink()) {
    throw new Error("Playwright data-root provenance is not a regular file");
  }
  const actual = JSON.parse(fs.readFileSync(provenancePath, "utf8"));
  const expected = expectedProvenance(identity, fixture, ownerToken);
  if (!sameProvenance(actual, expected)) {
    throw new Error("Playwright data-root provenance mismatch; cleanup refused");
  }

  fs.rmSync(identity.dataRoot, { recursive: true });
}
