#!/usr/bin/env node

import fs from "node:fs";
import crypto from "node:crypto";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import net from "node:net";
import path from "node:path";

const FRONTEND_ROOT = path.dirname(
  path.dirname(fileURLToPath(import.meta.url)),
);
const GATE5_RUNTIME_PARENT = path.join(
  FRONTEND_ROOT,
  ".tmp",
  "gate5-runtime",
);
const RUNTIME_OWNER_MARKER = ".gate5-runtime-owner.json";
const TERM_GRACE_MS = 15_000;
const JSON_NUMBER_PATTERN =
  /-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/y;

const FIXTURES = Object.freeze([
  "normal",
  "degraded",
  "offline",
  "empty",
  "long-content",
]);

const PLAYWRIGHT_SAFETY_ARGS = Object.freeze([
  "--config=playwright.config.ts",
  "--workers=1",
  "--project=chromium",
  "--forbid-only",
  "--reporter=json",
  "--update-snapshots=none",
  "--grep-invert=@live-hermes-sessions",
]);

const FIXTURE_TEST_FILES = Object.freeze([
  "tests/e2e/hermes-workbench.spec.ts",
  "tests/e2e/hermes-workbench-visual.spec.ts",
  "tests/e2e/hermes-closure-matrix.spec.ts",
  "tests/e2e/hermes-closure-quality.spec.ts",
]);

const FIXTURE_CONTRACTS = Object.freeze({
  normal: Object.freeze({ expected: 30, skipped: 0 }),
  degraded: Object.freeze({ expected: 23, skipped: 2 }),
  offline: Object.freeze({ expected: 22, skipped: 3 }),
  empty: Object.freeze({ expected: 22, skipped: 3 }),
  "long-content": Object.freeze({ expected: 22, skipped: 3 }),
});

const SAFE_INHERITED_ENV = Object.freeze([
  "LANG",
  "LC_ALL",
  "LC_CTYPE",
  "PATH",
  "PLAYWRIGHT_BROWSERS_PATH",
]);

function cleanBaseEnv(baseEnv) {
  const clean = {};
  for (const name of SAFE_INHERITED_ENV) {
    const value = baseEnv[name];
    if (value !== undefined) {
      clean[name] = String(value);
    }
  }
  return clean;
}

class DuplicateJsonKeyError extends Error {}

function skipJsonWhitespace(rawJson, state) {
  while (
    state.index < rawJson.length &&
    [" ", "\t", "\n", "\r"].includes(rawJson[state.index])
  ) {
    state.index += 1;
  }
}

function scanJsonString(rawJson, state) {
  const start = state.index;
  state.index += 1;
  while (state.index < rawJson.length) {
    const character = rawJson[state.index];
    if (character === "\"") {
      state.index += 1;
      return JSON.parse(rawJson.slice(start, state.index));
    }
    if (character === "\\") {
      state.index += 1;
      if (state.index >= rawJson.length) {
        throw new SyntaxError("unterminated JSON escape");
      }
      state.index += rawJson[state.index] === "u" ? 5 : 1;
      continue;
    }
    state.index += 1;
  }
  throw new SyntaxError("unterminated JSON string");
}

function scanJsonValue(rawJson, state, depth) {
  if (depth > 512) {
    throw new SyntaxError("JSON nesting exceeds Gate 5 limit");
  }
  skipJsonWhitespace(rawJson, state);
  const character = rawJson[state.index];
  if (character === "\"") {
    scanJsonString(rawJson, state);
    return;
  }
  if (character === "{") {
    state.index += 1;
    skipJsonWhitespace(rawJson, state);
    const keys = new Set();
    if (rawJson[state.index] === "}") {
      state.index += 1;
      return;
    }
    while (state.index < rawJson.length) {
      if (rawJson[state.index] !== "\"") {
        throw new SyntaxError("JSON object key must be a string");
      }
      const key = scanJsonString(rawJson, state);
      if (keys.has(key)) {
        throw new DuplicateJsonKeyError();
      }
      keys.add(key);
      skipJsonWhitespace(rawJson, state);
      if (rawJson[state.index] !== ":") {
        throw new SyntaxError("JSON object key is missing a colon");
      }
      state.index += 1;
      scanJsonValue(rawJson, state, depth + 1);
      skipJsonWhitespace(rawJson, state);
      if (rawJson[state.index] === "}") {
        state.index += 1;
        return;
      }
      if (rawJson[state.index] !== ",") {
        throw new SyntaxError("JSON object is missing a comma");
      }
      state.index += 1;
      skipJsonWhitespace(rawJson, state);
    }
    throw new SyntaxError("unterminated JSON object");
  }
  if (character === "[") {
    state.index += 1;
    skipJsonWhitespace(rawJson, state);
    if (rawJson[state.index] === "]") {
      state.index += 1;
      return;
    }
    while (state.index < rawJson.length) {
      scanJsonValue(rawJson, state, depth + 1);
      skipJsonWhitespace(rawJson, state);
      if (rawJson[state.index] === "]") {
        state.index += 1;
        return;
      }
      if (rawJson[state.index] !== ",") {
        throw new SyntaxError("JSON array is missing a comma");
      }
      state.index += 1;
      skipJsonWhitespace(rawJson, state);
    }
    throw new SyntaxError("unterminated JSON array");
  }
  for (const literal of ["true", "false", "null"]) {
    if (rawJson.startsWith(literal, state.index)) {
      state.index += literal.length;
      return;
    }
  }
  JSON_NUMBER_PATTERN.lastIndex = state.index;
  const number = JSON_NUMBER_PATTERN.exec(rawJson);
  if (number === null) {
    throw new SyntaxError("invalid JSON value");
  }
  state.index = JSON_NUMBER_PATTERN.lastIndex;
}

export function parsePlaywrightJson(rawJson, rowId) {
  if (typeof rawJson !== "string") {
    throw new Error(`${rowId} produced invalid Playwright JSON`);
  }
  const state = { index: 0 };
  try {
    scanJsonValue(rawJson, state, 0);
    skipJsonWhitespace(rawJson, state);
    if (state.index !== rawJson.length) {
      throw new SyntaxError("trailing JSON bytes");
    }
    return JSON.parse(rawJson);
  } catch (error) {
    if (error instanceof DuplicateJsonKeyError) {
      throw new Error(
        `${rowId} Playwright JSON contains a duplicate object key`,
      );
    }
    throw new Error(`${rowId} produced invalid Playwright JSON`);
  }
}

export function assertSafeCliArgs(args) {
  if (
    args.some(
      (arg) => arg === "-u" || arg.startsWith("--update-snapshots"),
    )
  ) {
    throw new Error("Gate 5 forbids snapshot updates");
  }

  const parsed = {};
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    let name;
    let value;
    if (arg === "--output-dir" || arg === "--backend-python") {
      name = arg.slice(2);
      value = args[++index];
    } else if (arg.startsWith("--output-dir=")) {
      name = "output-dir";
      value = arg.slice("--output-dir=".length);
    } else if (arg.startsWith("--backend-python=")) {
      name = "backend-python";
      value = arg.slice("--backend-python=".length);
    } else {
      throw new Error(`Gate 5 does not accept ${arg}`);
    }
    if (!value || value.startsWith("--")) {
      throw new Error(`Gate 5 requires a value for --${name}`);
    }
    const key = name === "output-dir" ? "outputDir" : "backendPython";
    if (parsed[key] !== undefined) {
      throw new Error(`Gate 5 received --${name} more than once`);
    }
    if (!path.isAbsolute(value)) {
      throw new Error(`Gate 5 --${name} must be an absolute path`);
    }
    parsed[key] = path.resolve(value);
  }
  for (const [key, name] of [
    ["outputDir", "output-dir"],
    ["backendPython", "backend-python"],
  ]) {
    if (parsed[key] === undefined) {
      throw new Error(`Gate 5 requires --${name}`);
    }
  }
  return parsed;
}

export function validateSupportTap(row, rawTap) {
  if (typeof rawTap !== "string") {
    throw new Error(`${row.id} did not produce TAP output`);
  }
  const counters = {};
  for (const name of [
    "tests",
    "pass",
    "fail",
    "cancelled",
    "skipped",
    "todo",
  ]) {
    const matches = [
      ...rawTap.matchAll(new RegExp(`^# ${name} (\\d+)\\s*$`, "gm")),
    ];
    if (matches.length !== 1) {
      throw new Error(`${row.id} TAP is missing one exact ${name} counter`);
    }
    counters[name] = Number(matches[0][1]);
  }
  if (counters.tests === 0) {
    throw new Error(`${row.id} discovered zero tests`);
  }
  if (counters.skipped !== row.contract.skipped) {
    throw new Error(
      `${row.id} skip contract mismatch: expected ${row.contract.skipped}, got ${counters.skipped}`,
    );
  }
  if (counters.fail !== 0 || counters.cancelled !== 0 || counters.todo !== 0) {
    throw new Error(
      `${row.id} TAP has fail=${counters.fail} cancelled=${counters.cancelled} todo=${counters.todo}`,
    );
  }
  if (counters.pass !== row.contract.expected) {
    throw new Error(
      `${row.id} pass contract mismatch: expected ${row.contract.expected}, got ${counters.pass}`,
    );
  }
  if (counters.tests !== counters.pass + counters.skipped) {
    throw new Error(`${row.id} TAP counters are internally inconsistent`);
  }
  return {
    expected: counters.pass,
    skipped: counters.skipped,
    total: counters.tests,
  };
}

export function validatePlaywrightReport(row, report) {
  const stats = report?.stats;
  if (
    stats === null ||
    typeof stats !== "object" ||
    !["expected", "flaky", "skipped", "unexpected"].every((name) =>
      Number.isInteger(stats[name]),
    )
  ) {
    throw new Error(`${row.id} did not produce a valid Playwright JSON report`);
  }
  const total =
    stats.expected + stats.flaky + stats.skipped + stats.unexpected;
  if (total === 0) {
    throw new Error(`${row.id} discovered zero tests`);
  }
  if (stats.skipped !== row.contract.skipped) {
    throw new Error(
      `${row.id} skip contract mismatch: expected ${row.contract.skipped}, got ${stats.skipped}`,
    );
  }
  if (stats.unexpected !== 0) {
    throw new Error(
      `${row.id} has ${stats.unexpected} unexpected test outcomes`,
    );
  }
  if (stats.flaky !== 0) {
    throw new Error(`${row.id} has ${stats.flaky} flaky test outcomes`);
  }
  if (stats.expected !== row.contract.expected) {
    throw new Error(
      `${row.id} pass contract mismatch: expected ${row.contract.expected}, got ${stats.expected}`,
    );
  }
  if (!Array.isArray(report.errors) || report.errors.length !== 0) {
    throw new Error(`${row.id} Playwright report contains top-level errors`);
  }
  return Object.freeze({
    expected: stats.expected,
    skipped: stats.skipped,
    total,
  });
}

function writeNewFile(filePath, contents) {
  fs.writeFileSync(filePath, contents, {
    encoding: "utf8",
    flag: "wx",
    mode: 0o600,
  });
}

export function canonicalJson(value) {
  const normalize = (candidate) => {
    if (Array.isArray(candidate)) {
      return Array.from({ length: candidate.length }, (_, index) => {
        if (!Object.hasOwn(candidate, index)) {
          throw new Error(
            "Gate 5 canonical JSON forbids undefined array entries",
          );
        }
        return normalize(candidate[index]);
      });
    }
    if (candidate !== null && typeof candidate === "object") {
      if (Object.getOwnPropertySymbols(candidate).length !== 0) {
        throw new Error(
          "Gate 5 canonical JSON forbids symbol-keyed properties",
        );
      }
      return Object.fromEntries(
        Object.keys(candidate)
          .sort()
          .map((key) => [key, normalize(candidate[key])]),
      );
    }
    if (
      typeof candidate === "number" &&
      !Number.isFinite(candidate)
    ) {
      throw new Error("Gate 5 canonical JSON forbids non-finite numbers");
    }
    if (
      ["bigint", "function", "symbol", "undefined"].includes(
        typeof candidate,
      )
    ) {
      throw new Error(
        `Gate 5 canonical JSON forbids ${typeof candidate} values`,
      );
    }
    return candidate;
  };
  return JSON.stringify(normalize(value));
}

function writeCanonicalSummary(reportDir, summary) {
  const summaryPath = path.join(reportDir, "gate5-summary.json");
  writeNewFile(summaryPath, canonicalJson(summary));
}

function sha256Utf8(value) {
  return crypto.createHash("sha256").update(value, "utf8").digest("hex");
}

function assertEmptyOwnerOnlyOutputDir(reportDir) {
  if (!path.isAbsolute(reportDir)) {
    throw new Error("Gate 5 output directory must be absolute");
  }
  const resolved = path.resolve(reportDir);
  const stat = fs.lstatSync(resolved);
  if (stat.isSymbolicLink() || !stat.isDirectory()) {
    throw new Error("Gate 5 output directory must be a real directory");
  }
  if (typeof process.getuid === "function" && stat.uid !== process.getuid()) {
    throw new Error("Gate 5 output directory must belong to the current user");
  }
  if ((stat.mode & 0o077) !== 0) {
    throw new Error("Gate 5 output directory must be owner-only");
  }
  if (fs.realpathSync(resolved) !== resolved) {
    throw new Error("Gate 5 output directory must be canonical");
  }
  if (fs.readdirSync(resolved).length !== 0) {
    throw new Error("Gate 5 output directory must be empty");
  }
}

function pathsOverlap(left, right) {
  const leftToRight = path.relative(left, right);
  const rightToLeft = path.relative(right, left);
  const isInside = (relative) =>
    relative === "" ||
    (relative !== ".." &&
      !relative.startsWith(`..${path.sep}`) &&
      !path.isAbsolute(relative));
  return isInside(leftToRight) || isInside(rightToLeft);
}

function assertOwnedCanonicalDirectory(directory, label, ownerOnly) {
  const stat = fs.lstatSync(directory);
  if (stat.isSymbolicLink() || !stat.isDirectory()) {
    throw new Error(`${label} must be a real directory`);
  }
  if (typeof process.getuid === "function" && stat.uid !== process.getuid()) {
    throw new Error(`${label} must belong to the current user`);
  }
  if (ownerOnly && (stat.mode & 0o077) !== 0) {
    throw new Error(`${label} must be owner-only`);
  }
  if (fs.realpathSync(directory) !== path.resolve(directory)) {
    throw new Error(`${label} must be canonical`);
  }
}

function runtimeRunRootForToken(runToken) {
  if (
    typeof runToken !== "string" ||
    !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(runToken)
  ) {
    throw new Error("Gate 5 run token must be path-safe");
  }
  return path.join(GATE5_RUNTIME_PARENT, runToken);
}

function assertMatrixRuntimeContract(matrix) {
  const runtimeRunRoots = new Set(
    matrix.map((row) => path.dirname(row.runtimeRoot)),
  );
  if (runtimeRunRoots.size !== 1) {
    throw new Error("Gate 5 rows must share one runtime run root");
  }
  const [runtimeRunRoot] = runtimeRunRoots;
  if (
    path.dirname(runtimeRunRoot) !== GATE5_RUNTIME_PARENT ||
    matrix.some(
      (row) =>
        path.dirname(row.runtimeRoot) !== runtimeRunRoot ||
        path.basename(row.runtimeRoot) !== row.id,
    )
  ) {
    throw new Error("Gate 5 runtime paths escaped the controlled runtime root");
  }
  return runtimeRunRoot;
}

function createOwnedRuntimeRunRoot(runtimeRunRoot) {
  const temporaryRoot = path.dirname(GATE5_RUNTIME_PARENT);
  if (!fs.existsSync(temporaryRoot)) {
    fs.mkdirSync(temporaryRoot, { mode: 0o700 });
  }
  assertOwnedCanonicalDirectory(
    temporaryRoot,
    "Gate 5 frontend temporary directory",
    false,
  );
  if (!fs.existsSync(GATE5_RUNTIME_PARENT)) {
    fs.mkdirSync(GATE5_RUNTIME_PARENT, { mode: 0o700 });
    fs.chmodSync(GATE5_RUNTIME_PARENT, 0o700);
  }
  assertOwnedCanonicalDirectory(
    GATE5_RUNTIME_PARENT,
    "Gate 5 runtime parent",
    true,
  );
  if (fs.existsSync(runtimeRunRoot)) {
    throw new Error(
      `Gate 5 runtime run root already exists: ${runtimeRunRoot}`,
    );
  }
  fs.mkdirSync(runtimeRunRoot, { mode: 0o700 });
  fs.chmodSync(runtimeRunRoot, 0o700);
  assertOwnedCanonicalDirectory(
    runtimeRunRoot,
    "Gate 5 runtime run root",
    true,
  );
  writeNewFile(
    path.join(runtimeRunRoot, RUNTIME_OWNER_MARKER),
    canonicalJson({
      runtime_root: runtimeRunRoot,
      schema_version: "hermes-gate5-runtime.v1",
    }),
  );
}

function cleanupOwnedRuntimeRunRoot(runtimeRunRoot) {
  if (
    path.dirname(runtimeRunRoot) !== GATE5_RUNTIME_PARENT ||
    path.basename(runtimeRunRoot).length === 0
  ) {
    throw new Error(
      `refusing to clean unbounded runtime root ${runtimeRunRoot}`,
    );
  }
  assertOwnedCanonicalDirectory(
    runtimeRunRoot,
    "Gate 5 runtime run root",
    true,
  );
  const markerPath = path.join(runtimeRunRoot, RUNTIME_OWNER_MARKER);
  const markerStat = fs.lstatSync(markerPath);
  if (markerStat.isSymbolicLink() || !markerStat.isFile()) {
    throw new Error(`Gate 5 runtime owner marker is invalid: ${markerPath}`);
  }
  const expectedMarker = canonicalJson({
    runtime_root: runtimeRunRoot,
    schema_version: "hermes-gate5-runtime.v1",
  });
  if (fs.readFileSync(markerPath, "utf8") !== expectedMarker) {
    throw new Error(`Gate 5 runtime owner marker drifted: ${markerPath}`);
  }
  fs.rmSync(runtimeRunRoot, { recursive: true });
}

function prepareRuntimeDirs(row, runtimeRunRoot) {
  if (
    path.dirname(row.runtimeRoot) !== runtimeRunRoot ||
    path.basename(row.runtimeRoot) !== row.id ||
    fs.existsSync(row.runtimeRoot)
  ) {
    throw new Error(`Gate 5 refused runtime directory ${row.runtimeRoot}`);
  }
  fs.mkdirSync(row.runtimeRoot, { mode: 0o700 });
  fs.chmodSync(row.runtimeRoot, 0o700);
  for (const directory of [
    row.env.HOME,
    row.env.TMPDIR,
    row.env.XDG_CACHE_HOME,
  ]) {
    if (
      path.dirname(directory) !== row.runtimeRoot ||
      fs.existsSync(directory)
    ) {
      throw new Error(`Gate 5 refused runtime child ${directory}`);
    }
    fs.mkdirSync(directory, { mode: 0o700 });
    fs.chmodSync(directory, 0o700);
  }
}

export async function runGate5Matrix({
  execute,
  matrix,
  now = () => new Date(),
  reportDir,
}) {
  if (!Array.isArray(matrix) || matrix.length === 0) {
    throw new Error("Gate 5 matrix must not be empty");
  }
  if (typeof execute !== "function") {
    throw new Error("Gate 5 row executor is required");
  }
  assertEmptyOwnerOnlyOutputDir(reportDir);
  const runtimeRunRoot = assertMatrixRuntimeContract(matrix);
  if (pathsOverlap(path.resolve(reportDir), GATE5_RUNTIME_PARENT)) {
    throw new Error(
      "Gate 5 evidence directory must not overlap the runtime parent",
    );
  }
  createOwnedRuntimeRunRoot(runtimeRunRoot);

  const summary = {
    ended_at: null,
    report_dir: path.resolve(reportDir),
    rows: [],
    runtime_cleanup: {
      error: null,
      status: "running",
    },
    runtime_root: runtimeRunRoot,
    schema_version: "hermes-gate5.v1",
    started_at: now().toISOString(),
    status: "running",
  };

  const failedRows = [];
  const retainRuntimeReasons = [];
  try {
    for (const row of matrix) {
    const stdoutFile =
      row.kind === "node-test" ? `${row.id}.stdout.tap` : null;
    const stderrFile = `${row.id}.stderr.log`;
    const reportFile =
      row.kind === "playwright"
        ? path.join(reportDir, `${row.id}.playwright.json`)
        : null;
    let capturedOutput = "";
    let result = null;
    let observed = null;
    let playwrightReportFile = null;
    let rowError = null;

    try {
      prepareRuntimeDirs(row, runtimeRunRoot);
      result = await execute(row, { reportDir });
      const stdout =
        typeof result?.stdout === "string" ? result.stdout : "";

      if (row.kind === "node-test") {
        capturedOutput = stdout;
        observed = validateSupportTap(row, stdout);
      } else {
        const rawReport =
          typeof result.reportText === "string"
            ? result.reportText
            : stdout;
        capturedOutput = rawReport;
        const parsedReport = parsePlaywrightJson(rawReport, row.id);
        let validationError = null;
        try {
          observed = validatePlaywrightReport(row, parsedReport);
        } catch (error) {
          validationError =
            error instanceof Error ? error : new Error(String(error));
        }
        writeNewFile(reportFile, canonicalJson(parsedReport));
        playwrightReportFile = path.basename(reportFile);
        if (validationError !== null) {
          throw validationError;
        }
      }
      if (!Number.isInteger(result?.exitCode) || result.exitCode !== 0) {
        throw new Error(
          `${row.id} exited ${String(result?.exitCode ?? "without a code")}`,
        );
      }
    } catch (error) {
      rowError = error instanceof Error ? error.message : String(error);
      failedRows.push(row.id);
    }

    const stdout =
      typeof result?.stdout === "string" ? result.stdout : "";
    const stderr =
      typeof result?.stderr === "string" ? result.stderr : "";
    if (row.kind === "node-test") {
      capturedOutput = stdout;
      writeNewFile(path.join(reportDir, stdoutFile), stdout);
    }
    writeNewFile(path.join(reportDir, stderrFile), stderr);
    if (result?.closeConfirmed === false) {
      retainRuntimeReasons.push(
        `${row.id}: child ${String(result.processId ?? "unknown")} did not close after SIGTERM`,
      );
    }
    summary.rows.push({
      args: [...row.args],
      backend_port: row.backendPort,
      close_confirmed: result?.closeConfirmed !== false,
      command: row.command,
      contract: { ...row.contract },
      environment_names: Object.keys(row.env).sort(),
      error: rowError,
      exit_code:
        Number.isInteger(result?.exitCode) ? result.exitCode : null,
      frontend_port: row.frontendPort,
      id: row.id,
      kind: row.kind,
      observed,
      output_bytes: Buffer.byteLength(capturedOutput, "utf8"),
      output_sha256: sha256Utf8(capturedOutput),
      playwright_report: playwrightReportFile,
      process_id:
        Number.isInteger(result?.processId) ? result.processId : null,
      rollback_port: row.rollbackPort ?? null,
      run_id: row.runId,
      runtime_root: row.runtimeRoot,
      status: rowError === null ? "passed" : "failed",
      stderr: stderrFile,
      stdout: stdoutFile,
      timed_out: result?.timedOut === true,
    });
    process.stdout.write(
      `[gate5] ${row.id} status=${
        rowError === null ? "passed" : "failed"
      } observed=${
        observed === null
          ? "none"
          : `${observed.expected}+${observed.skipped}`
      }\n`,
    );
    }
  } finally {
    if (retainRuntimeReasons.length !== 0) {
      summary.runtime_cleanup = {
        error: retainRuntimeReasons.join("; "),
        status: "retained",
      };
      failedRows.push("runtime-retained");
    } else {
      try {
        cleanupOwnedRuntimeRunRoot(runtimeRunRoot);
        summary.runtime_cleanup = {
          error: null,
          status: "removed",
        };
      } catch (error) {
        summary.runtime_cleanup = {
          error: `Gate 5 runtime cleanup failed: ${
            error instanceof Error ? error.message : String(error)
          }`,
          status: "failed",
        };
        failedRows.push("runtime-cleanup");
      }
    }
  }

  summary.ended_at = now().toISOString();
  summary.status = failedRows.length === 0 ? "passed" : "failed";
  if (failedRows.length !== 0) {
    summary.error = `Gate 5 failed rows: ${failedRows.join(", ")}`;
    summary.failed_rows = [...failedRows];
  }
  writeCanonicalSummary(reportDir, summary);
  if (failedRows.length !== 0) {
    throw new Error(
      `${summary.error}; summary=${path.join(reportDir, "gate5-summary.json")}`,
    );
  }
  return summary;
}

async function allocateUniquePorts(count, forbiddenPorts = new Set()) {
  const servers = [];
  try {
    while (servers.length < count) {
      const server = net.createServer();
      await new Promise((resolve, reject) => {
        server.once("error", reject);
        server.listen(
          { exclusive: true, host: "127.0.0.1", port: 0 },
          resolve,
        );
      });
      const address = server.address();
      if (
        address === null ||
        typeof address === "string" ||
        forbiddenPorts.has(address.port)
      ) {
        await new Promise((resolve) => server.close(resolve));
        continue;
      }
      servers.push(server);
    }
    return servers.map((server) => {
      const address = server.address();
      if (address === null || typeof address === "string") {
        throw new Error("Gate 5 failed to allocate an IPv4 loopback port");
      }
      return address.port;
    });
  } finally {
    await Promise.all(
      servers.map(
        (server) =>
          new Promise((resolve) => {
            server.close(() => resolve());
          }),
      ),
    );
  }
}

function existingFrontendWorkspacePorts(frontendRoot) {
  const workspaceParent = path.join(frontendRoot, ".tmp");
  if (!fs.existsSync(workspaceParent)) {
    return new Set();
  }
  return new Set(
    fs
      .readdirSync(workspaceParent)
      .map((entry) => /^e2e-frontend-(\d+)$/.exec(entry)?.[1])
      .filter((value) => value !== undefined)
      .map(Number),
  );
}

function resolvePlaywrightBrowsersPath(baseEnv) {
  const configured = baseEnv.PLAYWRIGHT_BROWSERS_PATH;
  if (configured) {
    if (!path.isAbsolute(configured) || !fs.existsSync(configured)) {
      throw new Error(
        "Gate 5 PLAYWRIGHT_BROWSERS_PATH must be an existing absolute path",
      );
    }
    return path.resolve(configured);
  }
  if (!baseEnv.HOME) {
    throw new Error(
      "Gate 5 needs HOME or PLAYWRIGHT_BROWSERS_PATH to locate browsers",
    );
  }
  const candidate =
    process.platform === "darwin"
      ? path.join(baseEnv.HOME, "Library", "Caches", "ms-playwright")
      : path.join(baseEnv.HOME, ".cache", "ms-playwright");
  if (!fs.existsSync(candidate)) {
    throw new Error(`Gate 5 Playwright browser directory is missing: ${candidate}`);
  }
  return candidate;
}

function frontendWorkspacePath(frontendRoot, port) {
  const workspaceParent = path.join(frontendRoot, ".tmp");
  const target = path.join(workspaceParent, `e2e-frontend-${port}`);
  if (
    path.dirname(target) !== workspaceParent ||
    path.basename(target) !== `e2e-frontend-${port}`
  ) {
    throw new Error("Gate 5 refused an invalid frontend workspace path");
  }
  return target;
}

function cleanupOwnedFrontendWorkspace(frontendRoot, target) {
  if (!fs.existsSync(target)) {
    return;
  }
  const workspaceParent = path.join(frontendRoot, ".tmp");
  if (
    path.dirname(target) !== workspaceParent ||
    !/^e2e-frontend-\d+$/.test(path.basename(target))
  ) {
    throw new Error(`refusing to clean unbounded workspace ${target}`);
  }
  const stat = fs.lstatSync(target);
  if (stat.isSymbolicLink() || !stat.isDirectory()) {
    throw new Error(`refusing to clean non-directory workspace ${target}`);
  }
  if (fs.realpathSync(target) !== target) {
    throw new Error(`refusing to clean non-canonical workspace ${target}`);
  }
  const marker = path.join(target, ".source-fingerprint");
  const nodeModules = path.join(target, "node_modules");
  if (!fs.lstatSync(marker).isFile()) {
    throw new Error(`workspace ownership marker is invalid: ${marker}`);
  }
  if (!fs.lstatSync(nodeModules).isSymbolicLink()) {
    throw new Error(`workspace node_modules link is invalid: ${nodeModules}`);
  }
  const expectedNodeModules = path.join(frontendRoot, "node_modules");
  if (fs.realpathSync(nodeModules) !== fs.realpathSync(expectedNodeModules)) {
    throw new Error(`workspace node_modules target drifted: ${nodeModules}`);
  }
  fs.rmSync(target, { recursive: true });
}

function createRowExecutor(frontendRoot) {
  return async (row) => {
    process.stdout.write(
      `[gate5] ${row.id} ports=${row.backendPort}/${row.frontendPort} run_id=${row.runId}\n`,
    );
    const workspaces =
      row.kind === "playwright"
        ? [
            frontendWorkspacePath(frontendRoot, row.frontendPort),
            ...(row.rollbackPort === undefined
              ? []
              : [frontendWorkspacePath(frontendRoot, row.rollbackPort)]),
          ]
        : [];
    for (const workspace of workspaces) {
      if (fs.existsSync(workspace)) {
        throw new Error(
          `Gate 5 frontend workspace already exists: ${workspace}`,
        );
      }
    }

    const child = spawn(row.command, row.args, {
      cwd: frontendRoot,
      env: row.env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    const stdout = [];
    const stderr = [];
    child.stdout.on("data", (chunk) => {
      stdout.push(Buffer.from(chunk));
    });
    child.stderr.on("data", (chunk) => {
      stderr.push(Buffer.from(chunk));
    });
    let timedOut = false;
    let timeout = null;
    let terminationGrace = null;
    let close;
    try {
      close = await new Promise((resolve, reject) => {
        let settled = false;
        const finish = (callback) => {
          if (settled) {
            return;
          }
          settled = true;
          child.removeListener("error", onError);
          child.removeListener("close", onClose);
          callback();
        };
        const onError = (error) => finish(() => reject(error));
        const onClose = (code, signal) =>
          finish(() =>
            resolve({ closeConfirmed: true, code, signal }),
          );
        child.once("error", onError);
        child.once("close", onClose);
        timeout = setTimeout(() => {
          timedOut = true;
          child.kill("SIGTERM");
          terminationGrace = setTimeout(() => {
            finish(() =>
              resolve({
                closeConfirmed: false,
                code: null,
                signal: "SIGTERM",
              }),
            );
          }, TERM_GRACE_MS);
          terminationGrace.unref();
        }, row.timeoutMs);
        timeout.unref();
      });
    } finally {
      clearTimeout(timeout);
      clearTimeout(terminationGrace);
    }
    if (close.closeConfirmed && close.signal !== null) {
      stderr.push(
        Buffer.from(`Gate 5 child terminated by ${close.signal}\n`, "utf8"),
      );
    }
    if (timedOut) {
      stderr.push(
        Buffer.from(
          `Gate 5 row timed out after ${row.timeoutMs}ms\n`,
          "utf8",
        ),
      );
    }
    if (!close.closeConfirmed) {
      stderr.push(
        Buffer.from(
          `Gate 5 child pid=${String(child.pid ?? "unknown")} did not close within ${TERM_GRACE_MS}ms after SIGTERM; runtime and workspace retained\n`,
          "utf8",
        ),
      );
      child.stdout.destroy();
      child.stderr.destroy();
      child.unref();
    }
    let cleanupFailed = false;
    if (close.closeConfirmed) {
      for (const workspace of workspaces) {
        try {
          cleanupOwnedFrontendWorkspace(frontendRoot, workspace);
        } catch (error) {
          cleanupFailed = true;
          stderr.push(
            Buffer.from(
              `Gate 5 workspace cleanup failed: ${
                error instanceof Error ? error.message : String(error)
              }\n`,
              "utf8",
            ),
          );
        }
      }
    }
    return {
      closeConfirmed: close.closeConfirmed,
      exitCode:
        timedOut || cleanupFailed || !close.closeConfirmed
          ? 1
          : (close.code ?? 1),
      processId: child.pid,
      reportText:
        row.kind === "playwright"
          ? Buffer.concat(stdout).toString("utf8")
          : undefined,
      stderr: Buffer.concat(stderr).toString("utf8"),
      stdout: Buffer.concat(stdout).toString("utf8"),
      timedOut,
    };
  };
}

async function main(argv) {
  const { backendPython, outputDir } = assertSafeCliArgs(argv);
  const scriptPath = fileURLToPath(import.meta.url);
  const frontendRoot = path.dirname(path.dirname(scriptPath));
  const repoRoot = path.resolve(frontendRoot, "..", "..");
  const playwrightCli = path.join(
    frontendRoot,
    "node_modules",
    "@playwright",
    "test",
    "cli.js",
  );
  for (const [label, candidate] of [
    ["backend Python", backendPython],
    ["Playwright CLI", playwrightCli],
  ]) {
    if (!fs.existsSync(candidate)) {
      throw new Error(`Gate 5 ${label} is missing: ${candidate}`);
    }
  }
  const backendRelative = path.relative(repoRoot, backendPython);
  if (
    backendRelative === "" ||
    backendRelative === ".." ||
    backendRelative.startsWith(`..${path.sep}`) ||
    path.isAbsolute(backendRelative)
  ) {
    throw new Error("Gate 5 backend Python must live inside the release checkout");
  }
  fs.accessSync(backendPython, fs.constants.X_OK);
  assertEmptyOwnerOnlyOutputDir(outputDir);
  const playwrightBrowsersPath = resolvePlaywrightBrowsersPath(process.env);

  const runToken = [
    Date.now().toString(36),
    process.pid.toString(36),
    crypto.randomBytes(4).toString("hex"),
  ].join("-");
  const ports = await allocateUniquePorts(
    19,
    existingFrontendWorkspacePorts(frontendRoot),
  );
  const matrix = buildGate5Matrix({
    backendPython,
    baseEnv: {
      ...process.env,
      PLAYWRIGHT_BROWSERS_PATH: playwrightBrowsersPath,
    },
    outputDir,
    ports,
    runToken,
  });
  const summary = await runGate5Matrix({
    execute: createRowExecutor(frontendRoot),
    matrix,
    reportDir: outputDir,
  });
  process.stdout.write(
    `HERMES_GATE5_PASS ${path.join(summary.report_dir, "gate5-summary.json")}\n`,
  );
}

const invokedPath =
  process.argv[1] === undefined ? null : path.resolve(process.argv[1]);
if (invokedPath === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2)).catch((error) => {
    process.stderr.write(
      `HERMES_GATE5_FAIL ${
        error instanceof Error ? error.message : String(error)
      }\n`,
    );
    process.exitCode = 1;
  });
}

export function buildGate5Matrix({
  backendPython = "python",
  baseEnv = process.env,
  outputDir,
  ports,
  runToken,
}) {
  if (!Array.isArray(ports) || ports.length !== 19) {
    throw new Error("Gate 5 requires exactly 19 preallocated ports");
  }
  const runtimeRunRoot = runtimeRunRootForToken(runToken);
  if (typeof outputDir !== "string" || !path.isAbsolute(outputDir)) {
    throw new Error("Gate 5 output directory must be absolute");
  }

  const definitions = [
    {
      args: ["run", "test:gate5-support"],
      command: process.platform === "win32" ? "npm.cmd" : "npm",
      contract: { expected: 37, skipped: 0 },
      id: "support",
      kind: "node-test",
      timeoutMs: 60_000,
    },
    {
      contract: { expected: 2, skipped: 0 },
      grep: "@real-backend-smoke",
      id: "real-smoke",
      kind: "playwright",
      testFiles: ["tests/e2e/hermes-workbench.spec.ts"],
      timeoutMs: 300_000,
    },
    ...FIXTURES.map((fixture) => ({
      contract: FIXTURE_CONTRACTS[fixture],
      fixture,
      grep: "@combined-fixture",
      id: `fixture-${fixture}`,
      kind: "playwright",
      testFiles: FIXTURE_TEST_FILES,
      timeoutMs: 600_000,
    })),
    {
      contract: { expected: 7, skipped: 0 },
      grep: "@lifecycle-fixture",
      id: "lifecycle",
      kind: "playwright",
      testFiles: ["tests/e2e/hermes-lifecycle.spec.ts"],
      timeoutMs: 900_000,
    },
    {
      contract: { expected: 2, skipped: 0 },
      grep: "@rollback",
      id: "rollback",
      kind: "playwright",
      testFiles: ["tests/e2e/hermes-rollback.spec.ts"],
      timeoutMs: 300_000,
    },
  ];
  let portIndex = 0;
  const matrix = definitions.map((definition, index) => {
    const backendPort = ports[portIndex++];
    const frontendPort = ports[portIndex++];
    const runId = `gate5-${runToken}-${String(index + 1).padStart(2, "0")}-${definition.id}`;
    const runtimeRoot = path.join(runtimeRunRoot, definition.id);
    const env = {
      ...cleanBaseEnv(baseEnv),
      HOME: path.join(runtimeRoot, "home"),
      NEXT_TELEMETRY_DISABLED: "1",
      NO_PROXY: "127.0.0.1,localhost,::1",
      PW_BACKEND_PORT: String(backendPort),
      PW_E2E: "1",
      PW_E2E_RUN_ID: runId,
      PW_FRONTEND_PORT: String(frontendPort),
      PW_PYTHON: backendPython,
      QS_AGENT_V02_CANDIDATE_ENABLED: "false",
      QS_AIHOT_ENABLED: "false",
      QS_ALPHA_VANTAGE_API_KEY: "",
      QS_API_BIND_ADDRESS: "127.0.0.1",
      QS_BACKTEST_JOBS_ENABLED: "false",
      QS_DATABASE_AUTO_MIGRATE: "false",
      QS_DATABASE_ENABLED: "false",
      QS_DATA_DIR: path.join(runtimeRoot, "data"),
      QS_DEFAULT_DATA_PROVIDER: "sample",
      QS_DRY_RUN: "true",
      QS_DUCKDB_PATH: path.join(runtimeRoot, "data", "gate5.duckdb"),
      QS_ENVIRONMENT: "test",
      QS_FINNHUB_API_KEY: "",
      QS_FUTU_ENABLED: "false",
      QS_FUTU_CACHE_DIR: path.join(runtimeRoot, "futu-cache"),
      QS_FUTU_OPTIONS_ENABLED: "false",
      QS_HERMES_GATEWAY_ENABLED: "false",
      QS_HORIZON_ENABLED: "false",
      QS_KILL_SWITCH: "true",
      QS_LIVE_TRADING_ENABLED: "false",
      QS_LLM_API_KEY: "",
      QS_LLM_BASE_URL: "",
      QS_LLM_MODEL: "",
      QS_LLM_PROVIDER: "stub",
      QS_LOCAL_MUTATION_COMPOSER_OPEN: "false",
      QS_LOCAL_MUTATION_ENABLED: "false",
      QS_NEWSAPI_KEY: "",
      QS_NEWS_FAILOVER_ENABLED: "false",
      QS_OPTIONS_RADAR_ENABLED: "false",
      QS_OPTIONS_RADAR_OUTPUT_DIR: path.join(
        runtimeRoot,
        "options-radar",
      ),
      QS_OPTIONS_RADAR_PROVIDER: "sample",
      QS_OPTIONS_RADAR_STARTUP_CATCHUP_ENABLED: "false",
      QS_PAPER_ACCOUNT_AUTO_PROCESS_PENDING_ORDERS_ENABLED: "false",
      QS_PAPER_ACCOUNT_DB_MODE: "file",
      QS_PAPER_TRADING: "true",
      QS_PARQUET_DIR: path.join(runtimeRoot, "parquet"),
      QS_POLYGON_API_KEY: "",
      QS_POLYMARKET_CACHE_DIR: path.join(runtimeRoot, "polymarket-cache"),
      QS_PREDICTION_MARKET_HISTORY_DIR: path.join(
        runtimeRoot,
        "prediction-history",
      ),
      QS_PREDICTION_MARKET_PROVIDER: "sample",
      QS_REPORTS_DIR: path.join(runtimeRoot, "reports"),
      QS_TIINGO_API_TOKEN: "",
      QS_TWELVEDATA_API_KEY: "",
      QS_TWITTER_API_KEY: "",
      QS_TWITTER_API_KEY_SECRET: "",
      QS_TWITTER_BEARER_TOKEN: "",
      TMPDIR: path.join(runtimeRoot, "tmp"),
      XDG_CACHE_HOME: path.join(runtimeRoot, "cache"),
      ...(definition.fixture
        ? { PW_HERMES_WORKBENCH_FIXTURE: definition.fixture }
        : {}),
      ...(definition.id === "lifecycle"
        ? { PW_HERMES_LIFECYCLE_FIXTURE: "1" }
        : {}),
    };
    const row = {
      ...definition,
      backendPort,
      env,
      frontendPort,
      runtimeRoot,
      runId,
      ...(definition.kind === "playwright"
        ? {
            args: [
              "node_modules/@playwright/test/cli.js",
              "test",
              ...definition.testFiles,
              ...PLAYWRIGHT_SAFETY_ARGS,
              `--grep=${definition.grep}`,
            ],
            command: process.execPath,
          }
        : {}),
    };
    if (definition.id === "rollback") {
      row.rollbackPort = ports[portIndex++];
      row.env.PW_HERMES_ROLLBACK_E2E = "1";
      row.env.PW_HERMES_ROLLBACK_PORT = String(row.rollbackPort);
      row.env.PW_HERMES_WORKBENCH_FIXTURE = "normal";
    }
    Object.freeze(row.env);
    return Object.freeze(row);
  });
  return Object.freeze(matrix);
}
