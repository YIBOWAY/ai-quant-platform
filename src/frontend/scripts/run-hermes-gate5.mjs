#!/usr/bin/env node

import fs from "node:fs";
import crypto from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
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
const EXPECTED_BRANCH = "codex/agent-v0-2-release";
const PUBLICATION_REMOTE = "github";
const PUBLICATION_REMOTE_URL =
  "https://github.com/YIBOWAY/ai-quant-platform.git";
const COMMIT_PATTERN = /^[0-9a-f]{40}$/;
const SANDBOX_EXEC = "/usr/bin/sandbox-exec";
const BACKEND_PROBE_SANDBOX_PROFILE =
  "(version 1) (allow default) (deny network*) (deny file-write*)";
const JSON_NUMBER_PATTERN =
  /-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/y;

const BACKEND_IDENTITY_PROBE = String.raw`
import hashlib
import importlib.metadata
import json
import pathlib
import site
import sys

def reject_duplicate_keys(pairs):
    document = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate JSON key")
        document[key] = value
    return document

package = __import__("quant_system")
distribution = importlib.metadata.distribution("quant-system")
direct_url_text = distribution.read_text("direct_url.json")
direct_url = (
    json.loads(direct_url_text, object_pairs_hook=reject_duplicate_keys)
    if direct_url_text
    else None
)
inventory = sorted(
    {
        f"{candidate.metadata['Name']}=={candidate.version}"
        for candidate in importlib.metadata.distributions()
        if candidate.metadata.get("Name")
    }
)
site_paths = [
    pathlib.Path(value).resolve()
    for value in site.getsitepackages()
]
pth_files = []
for site_path in site_paths:
    for pth_path in sorted(site_path.glob("*.pth")):
        contents = pth_path.read_bytes()
        pth_files.append(
            {
                "path": str(pth_path.resolve()),
                "sha256": hashlib.sha256(contents).hexdigest(),
                "size_bytes": len(contents),
            }
        )
document = {
    "base_prefix": str(pathlib.Path(sys.base_prefix).resolve()),
    "dependency_inventory": inventory,
    "direct_url": direct_url,
    "distribution_version": distribution.version,
    "prefix": str(pathlib.Path(sys.prefix).resolve()),
    "pth_files": pth_files,
    "quant_system_file": str(pathlib.Path(package.__file__).resolve()),
    "site_packages": [str(value) for value in site_paths],
    "sys_executable": str(pathlib.Path(sys.executable).absolute()),
    "sys_executable_realpath": str(pathlib.Path(sys.executable).resolve()),
    "sys_path": list(sys.path),
    "version": sys.version,
    "version_info": list(sys.version_info[:3]),
}
sys.stdout.write(
    json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    + "\n"
)
`;

const GATE2_JUNIT_VALIDATION_SOURCE = String.raw`
import importlib.util
import json
import pathlib
import sys

helper_path = pathlib.Path(sys.argv[1]).resolve(strict=True)
payload = json.loads(sys.argv[2])
spec = importlib.util.spec_from_file_location(
    "gate2_receipt_validation",
    helper_path,
)
if spec is None or spec.loader is None:
    raise SystemExit(2)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
runtime_root = pathlib.Path(payload["runtime_root"])
output = pathlib.Path(payload["output"])
python = pathlib.Path(payload["python"])
uv = pathlib.Path(payload["uv"])
node = pathlib.Path(payload["node"])
transient_paths = helper._transient_paths(runtime_root)
commands = helper.build_pytest_shard_commands(
    sandbox_exec=helper.SANDBOX_EXEC,
    python=python,
    transient_paths=transient_paths,
    output=output,
    marker_expression=helper.MARKER_EXPRESSION,
    inner_sandbox_node_ids=helper.INNER_SANDBOX_NODE_IDS,
)
junit_results = []
for item in payload["junit_plan"]:
    junit_results.append(
        helper.validate_junit(
            pathlib.Path(item["path"]).read_bytes(),
            pytest_exit=0,
            expected_skip_node_ids=tuple(item["expected_skips"]),
        )
    )
document = {
    "collection_source": helper.COLLECTION_SOURCE,
    "environment": {
        "install": helper._uv_environment(transient_paths, uv),
        "tests": helper._test_environment(transient_paths, uv, node),
    },
    "inner_sandbox_node_ids": list(helper.INNER_SANDBOX_NODE_IDS),
    "inner_shard_source": helper.INNER_SHARD_SOURCE,
    "junit_results": junit_results,
    "marker_expression": helper.MARKER_EXPRESSION,
    "network_denial_source": helper._NETWORK_DENIAL_SOURCE,
    "pytest_commands": {
        name: list(argv)
        for name, argv in sorted(commands.items())
    },
    "transient_paths": {
        name: str(path)
        for name, path in sorted(transient_paths.items())
    },
}
sys.stdout.write(
    json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    + "\n"
)
`;

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

const PERSISTED_TRANSCRIPT_SKIP = Object.freeze({
  id: "hermes-workbench.spec.ts::@combined-fixture opens a persisted transcript at its latest message with pinned context::chromium",
  reason:
    "The deterministic long session belongs to the normal combined fixture.",
});
const RETURN_TARGET_SKIP = Object.freeze({
  id: "hermes-workbench.spec.ts::@combined-fixture exposes a 44px return target on persisted transcripts::chromium",
  reason:
    "The deterministic persisted session belongs to the normal combined fixture.",
});
const CANDIDATE_EVIDENCE_SKIP = Object.freeze({
  id: "hermes-workbench.spec.ts::@combined-fixture Hermes Approvals navigates complete GET-only candidate evidence::chromium",
  reason:
    "Candidate detail evidence requires a fixture with one persisted candidate.",
});
const PERSISTED_SKIPS = Object.freeze([
  PERSISTED_TRANSCRIPT_SKIP,
  RETURN_TARGET_SKIP,
]);
const PERSISTED_AND_CANDIDATE_SKIPS = Object.freeze([
  CANDIDATE_EVIDENCE_SKIP,
  ...PERSISTED_SKIPS,
].sort((left, right) => left.id.localeCompare(right.id)));
const NO_SKIPS = Object.freeze([]);

const FIXTURE_CONTRACTS = Object.freeze({
  normal: Object.freeze({
    expected: 30,
    expectedSkips: NO_SKIPS,
    skipped: 0,
  }),
  degraded: Object.freeze({
    expected: 23,
    expectedSkips: PERSISTED_SKIPS,
    skipped: 2,
  }),
  offline: Object.freeze({
    expected: 22,
    expectedSkips: PERSISTED_AND_CANDIDATE_SKIPS,
    skipped: 3,
  }),
  empty: Object.freeze({
    expected: 22,
    expectedSkips: PERSISTED_AND_CANDIDATE_SKIPS,
    skipped: 3,
  }),
  "long-content": Object.freeze({
    expected: 22,
    expectedSkips: PERSISTED_AND_CANDIDATE_SKIPS,
    skipped: 3,
  }),
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
    if (
      arg === "--output-dir" ||
      arg === "--backend-python" ||
      arg === "--gate2-receipt" ||
      arg === "--frontend-install-receipt" ||
      arg === "--expected-commit"
    ) {
      name = arg.slice(2);
      value = args[++index];
    } else if (arg.startsWith("--output-dir=")) {
      name = "output-dir";
      value = arg.slice("--output-dir=".length);
    } else if (arg.startsWith("--backend-python=")) {
      name = "backend-python";
      value = arg.slice("--backend-python=".length);
    } else if (arg.startsWith("--gate2-receipt=")) {
      name = "gate2-receipt";
      value = arg.slice("--gate2-receipt=".length);
    } else if (arg.startsWith("--frontend-install-receipt=")) {
      name = "frontend-install-receipt";
      value = arg.slice("--frontend-install-receipt=".length);
    } else if (arg.startsWith("--expected-commit=")) {
      name = "expected-commit";
      value = arg.slice("--expected-commit=".length);
    } else {
      throw new Error(`Gate 5 does not accept ${arg}`);
    }
    if (!value || value.startsWith("--")) {
      throw new Error(`Gate 5 requires a value for --${name}`);
    }
    const key =
      name === "output-dir"
        ? "outputDir"
        : name === "backend-python"
          ? "backendPython"
          : name === "gate2-receipt"
            ? "gate2Receipt"
            : name === "frontend-install-receipt"
              ? "frontendInstallReceipt"
              : "expectedCommit";
    if (parsed[key] !== undefined) {
      throw new Error(`Gate 5 received --${name} more than once`);
    }
    if (name === "expected-commit") {
      if (!COMMIT_PATTERN.test(value)) {
        throw new Error(
          "Gate 5 --expected-commit must be a lowercase 40-hex commit",
        );
      }
      parsed[key] = value;
      continue;
    }
    if (!path.isAbsolute(value)) {
      throw new Error(`Gate 5 --${name} must be an absolute path`);
    }
    parsed[key] = path.resolve(value);
  }
  for (const [key, name] of [
    ["outputDir", "output-dir"],
    ["backendPython", "backend-python"],
    ["gate2Receipt", "gate2-receipt"],
    ["frontendInstallReceipt", "frontend-install-receipt"],
    ["expectedCommit", "expected-commit"],
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
  const expectedSkips = row.contract.expectedSkips;
  if (
    !Array.isArray(expectedSkips) ||
    expectedSkips.length !== row.contract.skipped ||
    expectedSkips.some(
      (entry) =>
        entry === null ||
        typeof entry !== "object" ||
        typeof entry.id !== "string" ||
        entry.id.length === 0 ||
        typeof entry.reason !== "string" ||
        entry.reason.length === 0,
    )
  ) {
    throw new Error(`${row.id} has an invalid repository skip contract`);
  }
  const outcomes = collectPlaywrightOutcomes(report, row.id);
  if (outcomes.length !== total) {
    throw new Error(
      `${row.id} Playwright suite population mismatch: stats=${total}, tree=${outcomes.length}`,
    );
  }
  const actualSkips = outcomes
    .filter((outcome) => outcome.status === "skipped")
    .map(({ id, reason }) => ({ id, reason }))
    .sort((left, right) => left.id.localeCompare(right.id));
  const normalizedExpectedSkips = [...expectedSkips].sort((left, right) =>
    left.id.localeCompare(right.id),
  );
  if (
    canonicalJson(actualSkips) !== canonicalJson(normalizedExpectedSkips)
  ) {
    throw new Error(`${row.id} exact skip identity/reason mismatch`);
  }
  return Object.freeze({
    expected: stats.expected,
    exact_skips: actualSkips,
    skipped: stats.skipped,
    total,
  });
}

export function collectPlaywrightOutcomes(report, rowId) {
  if (!Array.isArray(report?.suites)) {
    throw new Error(`${rowId} Playwright report has no suite tree`);
  }
  const outcomes = [];
  const seen = new Set();
  const visit = (suite) => {
    if (suite === null || typeof suite !== "object") {
      throw new Error(`${rowId} Playwright suite entry is invalid`);
    }
    const specs = suite.specs ?? [];
    const childSuites = suite.suites ?? [];
    if (
      !Array.isArray(specs) ||
      !Array.isArray(childSuites) ||
      (specs.length === 0 && childSuites.length === 0)
    ) {
      throw new Error(`${rowId} Playwright suite shape is invalid`);
    }
    for (const spec of specs) {
      if (
        spec === null ||
        typeof spec !== "object" ||
        typeof spec.file !== "string" ||
        spec.file.length === 0 ||
        typeof spec.title !== "string" ||
        spec.title.length === 0 ||
        !Array.isArray(spec.tests) ||
        spec.tests.length === 0
      ) {
        throw new Error(`${rowId} Playwright spec identity is invalid`);
      }
      for (const test of spec.tests) {
        if (
          test === null ||
          typeof test !== "object" ||
          typeof test.projectName !== "string" ||
          test.projectName.length === 0 ||
          typeof test.status !== "string" ||
          typeof test.expectedStatus !== "string" ||
          !Array.isArray(test.annotations) ||
          !Array.isArray(test.results)
        ) {
          throw new Error(`${rowId} Playwright test identity is invalid`);
        }
        const id = `${spec.file}::${spec.title}::${test.projectName}`;
        if (seen.has(id)) {
          throw new Error(`${rowId} Playwright test identity is duplicated`);
        }
        seen.add(id);
        const skipAnnotations = test.annotations.filter(
          (annotation) => annotation?.type === "skip",
        );
        const isSkipped =
          test.status === "skipped" ||
          test.expectedStatus === "skipped" ||
          test.results.some((result) => result?.status === "skipped");
        if (isSkipped) {
          if (
            test.status !== "skipped" ||
            test.expectedStatus !== "skipped" ||
            test.results.length === 0 ||
            test.results.some((result) => result?.status !== "skipped") ||
            skipAnnotations.length !== 1 ||
            typeof skipAnnotations[0].description !== "string" ||
            skipAnnotations[0].description.length === 0
          ) {
            throw new Error(
              `${rowId} Playwright skip is not exact and justified`,
            );
          }
          outcomes.push({
            id,
            reason: skipAnnotations[0].description,
            status: "skipped",
          });
        } else {
          if (skipAnnotations.length !== 0) {
            throw new Error(
              `${rowId} non-skipped Playwright test has a skip annotation`,
            );
          }
          outcomes.push({ id, reason: null, status: test.status });
        }
      }
    }
    for (const child of childSuites) {
      visit(child);
    }
  };
  for (const suite of report.suites) {
    visit(suite);
  }
  return outcomes;
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

function sha256Bytes(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function fileIdentity(filePath) {
  const info = fs.lstatSync(filePath);
  if (info.isSymbolicLink() || !info.isFile()) {
    throw new Error(`Gate 5 authority input must be a regular file: ${filePath}`);
  }
  const contents = fs.readFileSync(filePath);
  return {
    mode: (info.mode & 0o777).toString(8).padStart(3, "0"),
    path: path.resolve(filePath),
    sha256: sha256Bytes(contents),
    size_bytes: contents.length,
  };
}

export function runtimeExecutableIdentity(invokedPath) {
  const invoked = path.resolve(invokedPath);
  const invokedInfo = fs.lstatSync(invoked);
  if (
    (!invokedInfo.isFile() && !invokedInfo.isSymbolicLink()) ||
    (typeof process.getuid === "function" &&
      invokedInfo.uid !== process.getuid())
  ) {
    throw new Error(`Gate 5 runtime executable is unsafe: ${invoked}`);
  }
  const realpath = fs.realpathSync(invoked);
  const resolvedInfo = fs.lstatSync(realpath);
  if (
    resolvedInfo.isSymbolicLink() ||
    !resolvedInfo.isFile() ||
    resolvedInfo.nlink !== 1 ||
    (resolvedInfo.mode & 0o022) !== 0
  ) {
    throw new Error(
      `Gate 5 runtime executable target is unsafe: ${realpath}`,
    );
  }
  const contents = fs.readFileSync(realpath);
  return {
    invoked_path: invoked,
    invoked_mode: (invokedInfo.mode & 0o777)
      .toString(8)
      .padStart(3, "0"),
    invoked_owner_uid: invokedInfo.uid,
    link_target: invokedInfo.isSymbolicLink()
      ? fs.readlinkSync(invoked)
      : null,
    realpath,
    realpath_mode: (resolvedInfo.mode & 0o777)
      .toString(8)
      .padStart(3, "0"),
    realpath_owner_uid: resolvedInfo.uid,
    realpath_sha256: sha256Bytes(contents),
    realpath_size_bytes: contents.length,
  };
}

export function frontendInstallEnvironment(
  nodeIdentity,
  transientRoot,
) {
  if (
    typeof transientRoot !== "string" ||
    !path.isAbsolute(transientRoot)
  ) {
    throw new Error(
      "Gate 5 frontend install transient root must be absolute",
    );
  }
  return {
    HOME: path.join(transientRoot, "home"),
    LANG: "C",
    LC_ALL: "C",
    NPM_CONFIG_AUDIT: "false",
    NPM_CONFIG_CACHE: path.join(transientRoot, "cache"),
    NPM_CONFIG_FUND: "false",
    NPM_CONFIG_UPDATE_NOTIFIER: "false",
    PATH: `${path.dirname(nodeIdentity.realpath)}:/usr/bin:/bin`,
  };
}

function regularTreeIdentity(treeRoot) {
  const canonicalRoot = path.resolve(treeRoot);
  const rootInfo = fs.lstatSync(canonicalRoot);
  if (
    rootInfo.isSymbolicLink() ||
    !rootInfo.isDirectory() ||
    (typeof process.getuid === "function" &&
      rootInfo.uid !== process.getuid()) ||
    (rootInfo.mode & 0o022) !== 0
  ) {
    throw new Error("Gate 5 installed module tree root is unsafe");
  }
  const records = [];
  const visit = (directory) => {
    for (const entry of fs
      .readdirSync(directory, { withFileTypes: true })
      .sort((left, right) =>
        left.name < right.name
          ? -1
          : left.name > right.name
            ? 1
            : 0,
      )) {
      const absolute = path.join(directory, entry.name);
      const relative = path.relative(canonicalRoot, absolute);
      const info = fs.lstatSync(absolute);
      if (
        info.isSymbolicLink() ||
        (typeof process.getuid === "function" &&
          info.uid !== process.getuid()) ||
        (info.mode & 0o022) !== 0
      ) {
        throw new Error(
          `Gate 5 installed module tree entry is unsafe: ${relative}`,
        );
      }
      if (entry.isDirectory()) {
        visit(absolute);
      } else if (entry.isFile()) {
        const contents = fs.readFileSync(absolute);
        records.push({
          mode: (info.mode & 0o777).toString(8).padStart(3, "0"),
          path: relative.split(path.sep).join("/"),
          sha256: sha256Bytes(contents),
          size_bytes: contents.length,
        });
      } else {
        throw new Error(
          `Gate 5 installed module tree entry is not regular: ${relative}`,
        );
      }
    }
  };
  visit(canonicalRoot);
  if (records.length === 0) {
    throw new Error("Gate 5 installed module tree is empty");
  }
  return {
    file_count: records.length,
    root: canonicalRoot,
    tree_sha256: sha256Utf8(canonicalJson(records)),
  };
}

export function installedEnvironmentTreeIdentity(treeRoot) {
  const canonicalRoot = path.resolve(treeRoot);
  const rootInfo = fs.lstatSync(canonicalRoot);
  if (
    rootInfo.isSymbolicLink() ||
    !rootInfo.isDirectory() ||
    (typeof process.getuid === "function" &&
      rootInfo.uid !== process.getuid()) ||
    (rootInfo.mode & 0o022) !== 0
  ) {
    throw new Error("Gate 5 installed environment tree root is unsafe");
  }
  const candidates = [];
  const visit = (directory) => {
    for (const entry of fs.readdirSync(directory, {
      withFileTypes: true,
    })) {
      const absolute = path.join(directory, entry.name);
      candidates.push(absolute);
      if (entry.isDirectory()) {
        visit(absolute);
      }
    }
  };
  visit(canonicalRoot);
  candidates.sort((left, right) => {
    const leftRelative = path
      .relative(canonicalRoot, left)
      .split(path.sep)
      .join("/");
    const rightRelative = path
      .relative(canonicalRoot, right)
      .split(path.sep)
      .join("/");
    return leftRelative < rightRelative
      ? -1
      : leftRelative > rightRelative
        ? 1
        : 0;
  });
  const records = candidates.map((absolute) => {
    const info = fs.lstatSync(absolute);
    const relative = path
      .relative(canonicalRoot, absolute)
      .split(path.sep)
      .join("/");
    if (
      typeof process.getuid === "function" &&
      info.uid !== process.getuid()
    ) {
      throw new Error(
        `Gate 5 installed environment tree entry is unsafe: ${relative}`,
      );
    }
    const mode = (info.mode & 0o777).toString(8).padStart(3, "0");
    if (info.isSymbolicLink()) {
      const resolved = fs.realpathSync(absolute);
      const resolvedInfo = fs.statSync(resolved);
      if ((resolvedInfo.mode & 0o022) !== 0) {
        throw new Error(
          `Gate 5 installed environment tree entry is unsafe: ${relative}`,
        );
      }
      if (resolvedInfo.isDirectory()) {
        const relativeTarget = path.relative(canonicalRoot, resolved);
        if (
          relativeTarget === ".." ||
          relativeTarget.startsWith(`..${path.sep}`) ||
          path.isAbsolute(relativeTarget)
        ) {
          throw new Error(
            `Gate 5 installed environment tree entry is unsafe: ${relative}`,
          );
        }
        return {
          link_target: fs.readlinkSync(absolute),
          mode,
          path: relative,
          resolved: {
            mode: (resolvedInfo.mode & 0o777)
              .toString(8)
              .padStart(3, "0"),
            owner_uid: resolvedInfo.uid,
            path: resolved,
            type: "directory",
          },
          type: "symlink",
        };
      }
      if (!resolvedInfo.isFile()) {
        throw new Error(
          `Gate 5 installed environment tree entry is unsafe: ${relative}`,
        );
      }
      const contents = fs.readFileSync(resolved);
      return {
        link_target: fs.readlinkSync(absolute),
        mode,
        path: relative,
        resolved: {
          mode: (resolvedInfo.mode & 0o777)
            .toString(8)
            .padStart(3, "0"),
          owner_uid: resolvedInfo.uid,
          path: resolved,
          sha256: sha256Bytes(contents),
          size_bytes: contents.length,
          type: "file",
        },
        type: "symlink",
      };
    }
    if ((info.mode & 0o022) !== 0) {
      throw new Error(
        `Gate 5 installed environment tree entry is unsafe: ${relative}`,
      );
    }
    if (info.isDirectory()) {
      return {
        mode,
        path: relative,
        type: "directory",
      };
    }
    if (!info.isFile() || info.nlink !== 1) {
      throw new Error(
        `Gate 5 installed environment tree entry is unsafe: ${relative}`,
      );
    }
    const contents = fs.readFileSync(absolute);
    return {
      mode,
      path: relative,
      sha256: sha256Bytes(contents),
      size_bytes: contents.length,
      type: "file",
    };
  });
  if (records.length === 0) {
    throw new Error("Gate 5 installed environment tree is empty");
  }
  return {
    entry_count: records.length,
    root: canonicalRoot,
    tree_sha256: sha256Utf8(canonicalJson(records)),
  };
}

function gitEnvironment() {
  return {
    LANG: "C",
    LC_ALL: "C",
    PATH: "/usr/bin:/bin",
  };
}

function runGit(repoRoot, args, acceptedStatuses = [0]) {
  const completed = spawnSync(
    "/usr/bin/git",
    ["-C", repoRoot, ...args],
    {
      encoding: null,
      env: gitEnvironment(),
      maxBuffer: 64 * 1024 * 1024,
      timeout: 30_000,
    },
  );
  if (
    completed.error !== undefined ||
    completed.signal !== null ||
    !acceptedStatuses.includes(completed.status)
  ) {
    const stderr = Buffer.isBuffer(completed.stderr)
      ? completed.stderr.toString("utf8")
      : "";
    throw new Error(
      `Gate 5 git authority failed: git ${args.join(" ")} status=${String(
        completed.status,
      )} stderr=${stderr.trim()}`,
    );
  }
  return {
    status: completed.status,
    stderr: Buffer.isBuffer(completed.stderr)
      ? completed.stderr
      : Buffer.alloc(0),
    stdout: Buffer.isBuffer(completed.stdout)
      ? completed.stdout
      : Buffer.alloc(0),
  };
}

function gitBytes(repoRoot, ...args) {
  const completed = runGit(repoRoot, args);
  if (completed.stderr.length !== 0) {
    throw new Error(`Gate 5 git authority wrote stderr: git ${args.join(" ")}`);
  }
  return completed.stdout;
}

function gitText(repoRoot, ...args) {
  return gitBytes(repoRoot, ...args).toString("utf8").trim();
}

function assertGitQuiet(repoRoot, ...args) {
  const completed = runGit(repoRoot, args, [0, 1]);
  if (
    completed.stdout.length !== 0 ||
    completed.stderr.length !== 0 ||
    completed.status !== 0
  ) {
    throw new Error(`Gate 5 release checkout is not clean: git ${args.join(" ")}`);
  }
}

function taggedGitRecords(contents) {
  const records = contents
    .toString("utf8")
    .split("\0")
    .filter((entry) => entry.length !== 0);
  if (
    records.length === 0 ||
    records.some(
      (entry) => entry.length < 3 || entry[1] !== " ",
    )
  ) {
    throw new Error("Gate 5 tracked-index authority is malformed");
  }
  return records;
}

function assertIgnoredRuntimeConfigurationAbsent(repoRoot) {
  const candidates = [path.join(repoRoot, ".env")];
  const frontendRoot = path.join(repoRoot, "src", "frontend");
  let frontendEntries = [];
  try {
    frontendEntries = fs.readdirSync(frontendRoot);
  } catch (error) {
    if (error?.code !== "ENOENT") {
      throw error;
    }
  }
  candidates.push(
    ...frontendEntries
      .filter(
        (name) =>
          name.startsWith(".env") && name !== ".env.example",
      )
      .map((name) => path.join(frontendRoot, name)),
  );
  for (const candidate of candidates) {
    try {
      fs.lstatSync(candidate);
    } catch (error) {
      if (error?.code === "ENOENT") {
        continue;
      }
      throw error;
    }
    throw new Error(
      `Gate 5 release checkout has ignored runtime configuration: ${path.relative(
        repoRoot,
        candidate,
      )}`,
    );
  }
}

export function collectRepositoryAuthority(repoRoot, expectedCommit) {
  const canonicalRoot = path.resolve(repoRoot);
  if (fs.realpathSync(canonicalRoot) !== canonicalRoot) {
    throw new Error("Gate 5 release checkout root must be canonical");
  }
  const topLevel = path.resolve(
    gitText(canonicalRoot, "rev-parse", "--show-toplevel"),
  );
  if (topLevel !== canonicalRoot) {
    throw new Error("Gate 5 release checkout top-level mismatch");
  }
  assertIgnoredRuntimeConfigurationAbsent(canonicalRoot);
  const commit = gitText(
    canonicalRoot,
    "rev-parse",
    "--verify",
    "HEAD",
  );
  if (commit !== expectedCommit) {
    throw new Error("Gate 5 expected commit does not match HEAD");
  }
  const branch = gitText(
    canonicalRoot,
    "symbolic-ref",
    "--short",
    "HEAD",
  );
  if (branch !== EXPECTED_BRANCH) {
    throw new Error("Gate 5 release checkout branch mismatch");
  }
  const publicationFetchUrls = gitText(
    canonicalRoot,
    "remote",
    "get-url",
    "--all",
    PUBLICATION_REMOTE,
  )
    .split("\n")
    .filter((entry) => entry.length !== 0);
  if (
    publicationFetchUrls.length !== 1 ||
    publicationFetchUrls[0] !== PUBLICATION_REMOTE_URL
  ) {
    throw new Error("Gate 5 publication remote mismatch");
  }
  const publicationPushUrls = gitText(
    canonicalRoot,
    "remote",
    "get-url",
    "--push",
    "--all",
    PUBLICATION_REMOTE,
  )
    .split("\n")
    .filter((entry) => entry.length !== 0);
  if (
    publicationPushUrls.length !== 1 ||
    publicationPushUrls[0] !== PUBLICATION_REMOTE_URL
  ) {
    throw new Error("Gate 5 publication push URL mismatch");
  }

  const verboseRecords = taggedGitRecords(
    gitBytes(canonicalRoot, "ls-files", "-v", "-z"),
  );
  const taggedRecords = taggedGitRecords(
    gitBytes(canonicalRoot, "ls-files", "-t", "-z"),
  );
  if (verboseRecords.length !== taggedRecords.length) {
    throw new Error("Gate 5 tracked-index authority is inconsistent");
  }
  if (
    verboseRecords.some((entry) => /^[a-z]/.test(entry)) ||
    [...verboseRecords, ...taggedRecords].some(
      (entry) => entry[0] === "S",
    )
  ) {
    throw new Error("Gate 5 release checkout has hidden index flags");
  }
  if (
    gitBytes(canonicalRoot, "ls-files", "-u", "-z").length !== 0
  ) {
    throw new Error("Gate 5 release checkout has unmerged index entries");
  }
  assertGitQuiet(
    canonicalRoot,
    "diff-index",
    "--quiet",
    "--cached",
    "--ignore-submodules=none",
    "HEAD",
    "--",
  );
  assertGitQuiet(
    canonicalRoot,
    "diff-files",
    "--quiet",
    "--ignore-submodules=none",
    "--",
  );
  const status = gitBytes(
    canonicalRoot,
    "status",
    "--porcelain=v1",
    "-z",
    "--untracked-files=all",
  );
  if (status.length !== 0) {
    throw new Error("Gate 5 release checkout is not clean");
  }
  if (
    gitBytes(canonicalRoot, "for-each-ref", "refs/replace").length !== 0
  ) {
    throw new Error("Gate 5 release checkout has replace refs");
  }
  const indexLockValue = gitText(
    canonicalRoot,
    "rev-parse",
    "--git-path",
    "index.lock",
  );
  const indexLock = path.isAbsolute(indexLockValue)
    ? indexLockValue
    : path.resolve(canonicalRoot, indexLockValue);
  if (
    fs.existsSync(indexLock) ||
    fs.lstatSync(path.dirname(indexLock)).isSymbolicLink()
  ) {
    throw new Error("Gate 5 release checkout has an unsafe index lock path");
  }

  return {
    branch,
    clean: true,
    clean_status_sha256: sha256Bytes(status),
    commit,
    git_toplevel: canonicalRoot,
    ignored_runtime_configuration_absent: [".env"],
    publication_fetch_urls: publicationFetchUrls,
    publication_push_urls: publicationPushUrls,
    publication_remote: PUBLICATION_REMOTE,
    publication_remote_url: publicationFetchUrls[0],
    replace_ref_count: 0,
    root: canonicalRoot,
    tracked_tree: {
      assume_unchanged_count: 0,
      conflict_entry_count: 0,
      index_matches_head: true,
      ls_files_flags_sha256: sha256Utf8(
        `verbose\0${verboseRecords.join("\0")}\0tagged\0${taggedRecords.join(
          "\0",
        )}`,
      ),
      skip_worktree_count: 0,
      tracked_path_count: verboseRecords.length,
      worktree_matches_index: true,
    },
    tree: gitText(
      canonicalRoot,
      "rev-parse",
      "--verify",
      "HEAD^{tree}",
    ),
  };
}

function pathIsInside(parent, candidate) {
  const relative = path.relative(parent, candidate);
  return (
    relative !== "" &&
    relative !== ".." &&
    !relative.startsWith(`..${path.sep}`) &&
    !path.isAbsolute(relative)
  );
}

function assertPrivateRealAncestors(repoRoot, candidate) {
  const relative = path.relative(repoRoot, candidate);
  if (
    relative === "" ||
    relative === ".." ||
    relative.startsWith(`..${path.sep}`) ||
    path.isAbsolute(relative)
  ) {
    throw new Error("Gate 5 backend Python must live inside the release checkout");
  }
  let current = repoRoot;
  for (const component of relative.split(path.sep).slice(0, -1)) {
    current = path.join(current, component);
    const info = fs.lstatSync(current);
    if (
      info.isSymbolicLink() ||
      !info.isDirectory() ||
      (typeof process.getuid === "function" && info.uid !== process.getuid()) ||
      (info.mode & 0o022) !== 0
    ) {
      throw new Error(`Gate 5 backend Python ancestor is unsafe: ${current}`);
    }
  }
}

export function validateBackendPythonIdentity({
  backendPython,
  document,
  expectedCommit,
  repoRoot,
}) {
  if (
    document === null ||
    typeof document !== "object" ||
    Array.isArray(document)
  ) {
    throw new Error("Gate 5 backend Python identity is invalid");
  }
  const requiredKeys = [
    "base_prefix",
    "dependency_inventory",
    "direct_url",
    "distribution_version",
    "prefix",
    "pth_files",
    "quant_system_file",
    "site_packages",
    "sys_executable",
    "sys_executable_realpath",
    "sys_path",
    "version",
    "version_info",
  ];
  if (
    JSON.stringify(Object.keys(document).sort()) !==
    JSON.stringify(requiredKeys)
  ) {
    throw new Error("Gate 5 backend Python identity fields are invalid");
  }
  const canonicalRoot = path.resolve(repoRoot);
  const canonicalPython = path.resolve(backendPython);
  const backendRelative = path
    .relative(canonicalRoot, canonicalPython)
    .split(path.sep)
    .join("/");
  const expectedEnvironment = new RegExp(
    `^\\.tmp/backend-non-postgres-${expectedCommit.slice(
      0,
      12,
    )}-[0-9a-f]{16}/venv/bin/python$`,
  );
  if (!expectedEnvironment.test(backendRelative)) {
    throw new Error(
      "Gate 5 backend Python is not the exact Gate 2 fresh environment",
    );
  }
  const venv = path.dirname(path.dirname(canonicalPython));
  const versionInfo = document.version_info;
  if (
    !Array.isArray(versionInfo) ||
    versionInfo.length !== 3 ||
    versionInfo[0] !== 3 ||
    versionInfo[1] !== 11 ||
    !Number.isInteger(versionInfo[2])
  ) {
    throw new Error("Gate 5 backend Python is not Python 3.11");
  }
  if (
    path.resolve(String(document.prefix)) !== venv ||
    path.resolve(String(document.sys_executable)) !== canonicalPython ||
    !path.isAbsolute(String(document.sys_executable_realpath)) ||
    path.resolve(String(document.base_prefix)) === venv
  ) {
    throw new Error("Gate 5 backend Python prefix/executable identity is invalid");
  }
  const importPath = path.resolve(String(document.quant_system_file));
  if (
    !pathIsInside(venv, importPath) ||
    pathIsInside(path.join(canonicalRoot, "src"), importPath)
  ) {
    throw new Error("Gate 5 backend import is not from the fresh install");
  }
  if (
    !Array.isArray(document.site_packages) ||
    document.site_packages.length === 0 ||
    document.site_packages.some(
      (entry) => !pathIsInside(venv, path.resolve(String(entry))),
    )
  ) {
    throw new Error("Gate 5 backend site-packages identity is invalid");
  }
  if (
    !Array.isArray(document.pth_files) ||
    document.pth_files.some(
      (entry) =>
        entry === null ||
        typeof entry !== "object" ||
        Array.isArray(entry) ||
        !pathIsInside(venv, path.resolve(String(entry.path))) ||
        !/^[0-9a-f]{64}$/.test(String(entry.sha256)) ||
        !Number.isInteger(entry.size_bytes) ||
        entry.size_bytes < 0,
    )
  ) {
    throw new Error("Gate 5 backend .pth identity is invalid");
  }
  const sourceRoot = path.join(canonicalRoot, "src");
  if (
    !Array.isArray(document.sys_path) ||
    document.sys_path.some((entry) => typeof entry !== "string") ||
    document.sys_path.some((entry) => {
      if (entry.length === 0) {
        return false;
      }
      const resolved = path.resolve(entry);
      return resolved === sourceRoot || pathIsInside(sourceRoot, resolved);
    }) ||
    typeof document.version !== "string" ||
    document.version.length === 0
  ) {
    throw new Error("Gate 5 backend sys.path/version identity is invalid");
  }
  const directUrl = document.direct_url;
  if (
    directUrl === null ||
    typeof directUrl !== "object" ||
    Array.isArray(directUrl) ||
    directUrl.url !== pathToFileURL(canonicalRoot).href ||
    directUrl.dir_info === null ||
    typeof directUrl.dir_info !== "object" ||
    Array.isArray(directUrl.dir_info) ||
    directUrl.dir_info.editable !== false
  ) {
    throw new Error(
      "Gate 5 backend distribution is not an exact noneditable checkout install",
    );
  }
  if (
    typeof document.distribution_version !== "string" ||
    document.distribution_version.length === 0
  ) {
    throw new Error("Gate 5 backend distribution version is invalid");
  }
  const inventory = document.dependency_inventory;
  if (
    !Array.isArray(inventory) ||
    inventory.length === 0 ||
    inventory.some(
      (entry) => typeof entry !== "string" || entry.length === 0,
    ) ||
    new Set(inventory).size !== inventory.length ||
    JSON.stringify(inventory) !== JSON.stringify([...inventory].sort()) ||
    !inventory.includes(
      `quant-system==${document.distribution_version}`,
    )
  ) {
    throw new Error("Gate 5 backend dependency inventory is invalid");
  }
  return document;
}

function gate2InputIdentity(repoRoot) {
  return Object.fromEntries(
    [
      "pyproject.toml",
      "scripts/backend_non_postgres_gate.py",
      "scripts/verify_backend_non_postgres.sh",
      "uv.lock",
    ].map((relative) => {
      const identity = fileIdentity(path.join(repoRoot, relative));
      return [
        relative,
        {
          sha256: identity.sha256,
          size_bytes: identity.size_bytes,
        },
      ];
    }),
  );
}

function validateGate2Artifact(receiptDir, record) {
  if (
    record === null ||
    typeof record !== "object" ||
    Array.isArray(record) ||
    typeof record.path !== "string" ||
    path.basename(record.path) !== record.path ||
    !/^[0-9a-f]{64}$/.test(String(record.sha256)) ||
    !Number.isInteger(record.size_bytes) ||
    record.size_bytes < 0
  ) {
    throw new Error("Gate 5 Gate 2 artifact record is invalid");
  }
  const artifactPath = path.join(receiptDir, record.path);
  const info = fs.lstatSync(artifactPath);
  if (
    info.isSymbolicLink() ||
    !info.isFile() ||
    info.nlink !== 1 ||
    (typeof process.getuid === "function" && info.uid !== process.getuid()) ||
    (info.mode & 0o077) !== 0
  ) {
    throw new Error("Gate 5 Gate 2 artifact is unsafe");
  }
  const contents = fs.readFileSync(artifactPath);
  if (
    contents.length !== record.size_bytes ||
    sha256Bytes(contents) !== record.sha256
  ) {
    throw new Error("Gate 5 Gate 2 artifact digest mismatch");
  }
  return {
    path: artifactPath,
    sha256: record.sha256,
    size_bytes: record.size_bytes,
  };
}

export function frontendInputIdentity(frontendRoot) {
  return Object.fromEntries(
    [
      "package-lock.json",
      "package.json",
      "scripts/prepare-hermes-gate5-install.mjs",
      "scripts/run-hermes-gate5.mjs",
    ].map((relative) => {
      const identity = fileIdentity(path.join(frontendRoot, relative));
      return [
        relative,
        {
          sha256: identity.sha256,
          size_bytes: identity.size_bytes,
        },
      ];
    }),
  );
}

function validateFrontendArtifact(receiptDir, record) {
  if (
    record === null ||
    typeof record !== "object" ||
    Array.isArray(record) ||
    typeof record.path !== "string" ||
    path.basename(record.path) !== record.path ||
    !/^[0-9a-f]{64}$/.test(String(record.sha256)) ||
    !Number.isInteger(record.size_bytes) ||
    record.size_bytes < 0
  ) {
    throw new Error("Gate 5 frontend install artifact record is invalid");
  }
  const artifactPath = path.join(receiptDir, record.path);
  const info = fs.lstatSync(artifactPath);
  if (
    info.isSymbolicLink() ||
    !info.isFile() ||
    info.nlink !== 1 ||
    (typeof process.getuid === "function" &&
      info.uid !== process.getuid()) ||
    (info.mode & 0o077) !== 0
  ) {
    throw new Error("Gate 5 frontend install artifact is unsafe");
  }
  const contents = fs.readFileSync(artifactPath);
  if (
    contents.length !== record.size_bytes ||
    sha256Bytes(contents) !== record.sha256
  ) {
    throw new Error(
      "Gate 5 frontend install artifact digest mismatch",
    );
  }
  return {
    bytes: contents,
    path: artifactPath,
    sha256: record.sha256,
    size_bytes: record.size_bytes,
  };
}

export function loadFrontendInstallAuthority({
  currentInstalledTree,
  expectedCommit,
  frontendInstallReceipt,
  frontendRoot,
  repository,
}) {
  const repoRoot = path.resolve(frontendRoot, "..", "..");
  const canonicalReceipt = path.resolve(frontendInstallReceipt);
  if (
    !path.isAbsolute(frontendInstallReceipt) ||
    path.basename(canonicalReceipt) !==
      "frontend-fresh-install-receipt.json" ||
    fs.realpathSync(canonicalReceipt) !== canonicalReceipt ||
    pathIsInside(repoRoot, canonicalReceipt)
  ) {
    throw new Error("Gate 5 frontend install receipt path is unsafe");
  }
  const receiptInfo = fs.lstatSync(canonicalReceipt);
  const receiptDir = path.dirname(canonicalReceipt);
  const receiptDirInfo = fs.lstatSync(receiptDir);
  const receiptParentInfo = fs.lstatSync(path.dirname(receiptDir));
  if (
    receiptInfo.isSymbolicLink() ||
    !receiptInfo.isFile() ||
    receiptInfo.nlink !== 1 ||
    receiptDirInfo.isSymbolicLink() ||
    !receiptDirInfo.isDirectory() ||
    receiptParentInfo.isSymbolicLink() ||
    !receiptParentInfo.isDirectory() ||
    (typeof process.getuid === "function" &&
      (receiptInfo.uid !== process.getuid() ||
        receiptDirInfo.uid !== process.getuid() ||
        receiptParentInfo.uid !== process.getuid())) ||
    (receiptInfo.mode & 0o077) !== 0 ||
    (receiptDirInfo.mode & 0o077) !== 0 ||
    (receiptParentInfo.mode & 0o077) !== 0
  ) {
    throw new Error(
      "Gate 5 frontend install receipt ownership/mode is unsafe",
    );
  }
  const receiptBytes = fs.readFileSync(canonicalReceipt);
  const receiptText = receiptBytes.toString("utf8");
  if (
    !Buffer.from(receiptText, "utf8").equals(receiptBytes) ||
    receiptText.length === 0
  ) {
    throw new Error("Gate 5 frontend install receipt is not UTF-8");
  }
  const receipt = parsePlaywrightJson(
    receiptText,
    "frontend-install-receipt",
  );
  if (canonicalJson(receipt) !== receiptText) {
    throw new Error(
      "Gate 5 frontend install receipt is not canonical JSON",
    );
  }
  if (
    receipt.contract !== "platform-frontend-fresh-install/v1" ||
    receipt.status !== "passed" ||
    Object.hasOwn(receipt, "error")
  ) {
    throw new Error(
      "Gate 5 requires a passing frontend install receipt",
    );
  }
  if (
    canonicalJson(receipt.evidence_directory) !==
    canonicalJson({
      mode: (receiptDirInfo.mode & 0o777)
        .toString(8)
        .padStart(3, "0"),
      owner_uid: receiptDirInfo.uid,
      parent_mode: (receiptParentInfo.mode & 0o777)
        .toString(8)
        .padStart(3, "0"),
      parent_owner_uid: receiptParentInfo.uid,
      path: receiptDir,
    })
  ) {
    throw new Error(
      "Gate 5 frontend install evidence directory binding mismatch",
    );
  }
  const currentInputs = frontendInputIdentity(frontendRoot);
  if (
    canonicalJson(receipt.inputs_before) !==
      canonicalJson(currentInputs) ||
    canonicalJson(receipt.inputs_after) !==
      canonicalJson(currentInputs) ||
    canonicalJson(receipt.repository_before) !==
      canonicalJson(repository) ||
    canonicalJson(receipt.repository_after) !==
      canonicalJson(repository)
  ) {
    throw new Error(
      "Gate 5 frontend install source/repository binding mismatch",
    );
  }
  const currentNode = {
    ...runtimeExecutableIdentity(process.execPath),
    version: process.version,
    versions: process.versions,
  };
  const npmInvokedPath = receipt.npm?.invoked_path;
  if (
    typeof npmInvokedPath !== "string" ||
    !path.isAbsolute(npmInvokedPath)
  ) {
    throw new Error("Gate 5 frontend npm authority is invalid");
  }
  const currentNpm = runtimeExecutableIdentity(npmInvokedPath);
  const pathBin = path.dirname(currentNode.realpath);
  const currentPathCommands = Object.fromEntries(
    ["node", "npm", "npx"].map((name) => [
      name,
      runtimeExecutableIdentity(path.join(pathBin, name)),
    ]),
  );
  const npmReceiptProjection = { ...receipt.npm };
  delete npmReceiptProjection.version;
  const transientRoot = path.join(
    receiptDir,
    ".frontend-install-runtime",
  );
  let transientRuntimePresent = true;
  try {
    fs.lstatSync(transientRoot);
  } catch (error) {
    if (error?.code === "ENOENT") {
      transientRuntimePresent = false;
    } else {
      throw error;
    }
  }
  const nodeModulesBefore = receipt.node_modules_before;
  if (
    canonicalJson(receipt.node) !== canonicalJson(currentNode) ||
    canonicalJson(npmReceiptProjection) !==
      canonicalJson(currentNpm) ||
    canonicalJson(receipt.path_commands) !==
      canonicalJson(currentPathCommands) ||
    canonicalJson(receipt.environment) !==
      canonicalJson(
        frontendInstallEnvironment(currentNode, transientRoot),
      ) ||
    receipt.transient_runtime?.root !== transientRoot ||
    receipt.transient_runtime?.cleanup_status !== "removed" ||
    transientRuntimePresent ||
    nodeModulesBefore?.path !==
      path.join(frontendRoot, "node_modules") ||
    typeof nodeModulesBefore.exists !== "boolean" ||
    (nodeModulesBefore.exists &&
      (!/^[0-7]{3}$/.test(String(nodeModulesBefore.mode)) ||
        (Number.parseInt(nodeModulesBefore.mode, 8) & 0o022) !== 0 ||
        (typeof process.getuid === "function" &&
          nodeModulesBefore.owner_uid !== process.getuid())))
  ) {
    throw new Error("Gate 5 frontend Node/npm authority mismatch");
  }
  const installerPath = path.join(
    frontendRoot,
    "scripts",
    "prepare-hermes-gate5-install.mjs",
  );
  const command = receipt.command;
  if (
    canonicalJson(command) !==
      canonicalJson({
        argv: [
          process.execPath,
          installerPath,
          "--expected-commit",
          expectedCommit,
          "--npm-cli",
          currentNpm.invoked_path,
          "--output-dir",
          receiptDir,
        ],
        cwd: frontendRoot,
        environment_strategy: "allowlist",
        may_touch_database: false,
        may_touch_network_during_install: true,
        may_touch_provider: false,
        may_touch_runtime: false,
        may_touch_trading: false,
      })
  ) {
    throw new Error(
      "Gate 5 frontend install command authority mismatch",
    );
  }
  const npmVersion = receipt.npm.version;
  const install = receipt.install;
  if (
    npmVersion?.exit_code !== 0 ||
    npmVersion.signal !== null ||
    canonicalJson(npmVersion.argv) !==
      canonicalJson([
        currentNode.realpath,
        currentNpm.realpath,
        "--version",
      ]) ||
    install?.exit_code !== 0 ||
    install.signal !== null ||
    canonicalJson(install.argv) !==
      canonicalJson([
        currentNode.realpath,
        currentNpm.realpath,
        "ci",
        "--no-audit",
        "--no-fund",
      ])
  ) {
    throw new Error(
      "Gate 5 frontend npm install authority mismatch",
    );
  }
  const artifacts = {
    install_stderr: validateFrontendArtifact(
      receiptDir,
      install.stderr,
    ),
    install_stdout: validateFrontendArtifact(
      receiptDir,
      install.stdout,
    ),
    npm_version_stderr: validateFrontendArtifact(
      receiptDir,
      npmVersion.stderr,
    ),
    npm_version_stdout: validateFrontendArtifact(
      receiptDir,
      npmVersion.stdout,
    ),
  };
  if (
    canonicalJson(receipt.installed_tree_after) !==
      canonicalJson(currentInstalledTree) ||
    currentInstalledTree.root !==
      path.join(frontendRoot, "node_modules")
  ) {
    throw new Error(
      "Gate 5 current frontend dependency bytes differ from npm ci",
    );
  }
  return {
    artifacts: Object.fromEntries(
      Object.entries(artifacts).map(([name, artifact]) => [
        name,
        {
          path: artifact.path,
          sha256: artifact.sha256,
          size_bytes: artifact.size_bytes,
        },
      ]),
    ),
    expected_commit: expectedCommit,
    environment: frontendInstallEnvironment(
      currentNode,
      transientRoot,
    ),
    inputs: currentInputs,
    installed_tree: currentInstalledTree,
    node: currentNode,
    npm: currentNpm,
    path_commands: currentPathCommands,
    receipt_path: canonicalReceipt,
    receipt_sha256: sha256Bytes(receiptBytes),
    receipt_size_bytes: receiptBytes.length,
    repository,
    schema_version: "hermes-gate5-frontend-authority.v1",
  };
}

function collectFrontendAuthority({
  expectedCommit,
  frontendInstallReceipt,
  frontendRoot,
  playwrightBrowsersPath,
  repository,
}) {
  const installedTree = installedEnvironmentTreeIdentity(
    path.join(frontendRoot, "node_modules"),
  );
  const install = loadFrontendInstallAuthority({
    currentInstalledTree: installedTree,
    expectedCommit,
    frontendInstallReceipt,
    frontendRoot,
    repository,
  });
  return {
    browser_tree: installedEnvironmentTreeIdentity(
      playwrightBrowsersPath,
    ),
    expected_commit: expectedCommit,
    install,
    repository,
    schema_version: "hermes-gate5-frontend-authority.v1",
  };
}

function receiptRepositoryProjection(repository) {
  return {
    branch: repository.branch,
    clean: repository.clean,
    clean_status_sha256: repository.clean_status_sha256,
    commit: repository.commit,
    git_toplevel: repository.git_toplevel,
    publication_remote: repository.publication_remote,
    publication_remote_url: repository.publication_remote_url,
    root: repository.root,
    tracked_tree: repository.tracked_tree,
    tree: repository.tree,
  };
}

function gate2PythonProjection(identity) {
  return {
    base_prefix: identity.base_prefix,
    direct_url: identity.direct_url,
    distribution_version: identity.distribution_version,
    prefix: identity.prefix,
    pth_files: identity.pth_files,
    quant_system_file: identity.quant_system_file,
    site_packages: identity.site_packages,
    sys_executable: identity.sys_executable,
    sys_executable_realpath: identity.sys_executable_realpath,
    sys_path: identity.sys_path,
    version: identity.version,
    version_info: identity.version_info,
  };
}

const GATE2_MARKER_EXPRESSION =
  "not pg and not futu_opend and not provider and not network";
const GATE2_COLLECTION_PREFIX = "GATE2_COLLECTION_NODE_IDS=";

function gate2TransientPaths(runtimeRoot) {
  return Object.fromEntries(
    [
      ["basetemp", "basetemp"],
      ["home", "home"],
      ["pycache", "pycache"],
      ["sandbox_agent_data", "sandbox-agent-data"],
      ["sandbox_data", "sandbox-data"],
      ["tmp", "tmp"],
      ["uv_cache", "uv-cache"],
      ["venv", "venv"],
    ].map(([name, relative]) => [
      name,
      path.join(runtimeRoot, relative),
    ]),
  );
}

function gate2ExpectedEnvironment({
  nodePath,
  runtimeRoot,
  uvPath,
}) {
  const transientPaths = gate2TransientPaths(runtimeRoot);
  return {
    install: {
      HOME: transientPaths.home,
      LANG: "C",
      LC_ALL: "C",
      PATH: `${path.dirname(uvPath)}:/usr/bin:/bin`,
      TMPDIR: transientPaths.tmp,
      UV_CACHE_DIR: transientPaths.uv_cache,
      UV_LINK_MODE: "copy",
      UV_NO_CONFIG: "1",
      UV_PROJECT_ENVIRONMENT: transientPaths.venv,
      UV_PYTHON_DOWNLOADS: "never",
    },
    tests: {
      HOME: transientPaths.home,
      LANG: "C",
      LC_ALL: "C",
      PATH: [
        path.dirname(nodePath),
        path.join(transientPaths.venv, "bin"),
        path.dirname(uvPath),
        "/usr/bin",
        "/bin",
      ]
        .filter(
          (value, index, entries) =>
            entries.indexOf(value) === index,
        )
        .join(":"),
      PYTHONNOUSERSITE: "1",
      PYTHONPYCACHEPREFIX: transientPaths.pycache,
      PYTEST_DISABLE_PLUGIN_AUTOLOAD: "1",
      QS_AGENT_OUTPUT_DIR: transientPaths.sandbox_agent_data,
      QS_DATABASE_AUTO_MIGRATE: "false",
      QS_DATABASE_ENABLED: "false",
      QS_DATA_DIR: transientPaths.sandbox_data,
      QS_DRY_RUN: "true",
      QS_KILL_SWITCH: "true",
      QS_LIVE_TRADING_ENABLED: "false",
      QS_LOCAL_MUTATION_ENABLED: "false",
      QS_PAPER_ACCOUNT_DB_MODE: "file",
      QS_PAPER_TRADING: "true",
      QS_TEST_FUTU_OPEND: "0",
      TMPDIR: transientPaths.tmp,
    },
  };
}

function validateGate2PassResult(result, expectedTotal) {
  if (
    result === null ||
    typeof result !== "object" ||
    Array.isArray(result) ||
    canonicalJson(Object.keys(result).sort()) !==
      canonicalJson([
        "failed",
        "passed",
        "skip_node_ids",
        "skipped",
        "total",
      ]) ||
    !Number.isInteger(result.failed) ||
    !Number.isInteger(result.passed) ||
    !Number.isInteger(result.skipped) ||
    !Number.isInteger(result.total) ||
    result.failed !== 0 ||
    result.passed <= 0 ||
    result.skipped !== 0 ||
    result.total !== expectedTotal ||
    result.passed + result.skipped !== result.total ||
    canonicalJson(result.skip_node_ids) !== "[]"
  ) {
    throw new Error("Gate 5 Gate 2 pytest pass result is invalid");
  }
  return result;
}

function validateGate2TestSemantics({
  backendPython,
  receipt,
  receiptDir,
  runtimeRoot,
}) {
  if (
    receipt.marker_expression !== GATE2_MARKER_EXPRESSION ||
    canonicalJson(receipt.expected_skip_node_ids) !== "[]"
  ) {
    throw new Error("Gate 5 Gate 2 test selection authority mismatch");
  }
  const network = receipt.network_sandbox;
  const sandboxSha = sha256Bytes(fs.readFileSync(SANDBOX_EXEC));
  if (
    network?.exit_code !== 0 ||
    network.profile !==
      "(version 1) (allow default) (deny network*)" ||
    network.executable_sha256 !== sandboxSha ||
    !Array.isArray(network.argv) ||
    network.argv.length !== 8 ||
    canonicalJson(network.argv.slice(0, 6)) !==
      canonicalJson([
        SANDBOX_EXEC,
        "-p",
        "(version 1) (allow default) (deny network*)",
        path.resolve(backendPython),
        "-I",
        "-B",
      ]) ||
    network.argv[6] !== "-c" ||
    typeof network.argv[7] !== "string" ||
    network.argv[7].length === 0
  ) {
    throw new Error("Gate 5 Gate 2 network sandbox proof is invalid");
  }
  const networkStdout = validateGate2Artifact(
    receiptDir,
    network.stdout,
  );
  const networkStderr = validateGate2Artifact(
    receiptDir,
    network.stderr,
  );
  if (
    networkStdout.size_bytes !== 0 ||
    networkStderr.size_bytes !== 0
  ) {
    throw new Error(
      "Gate 5 Gate 2 network sandbox proof emitted output",
    );
  }

  const pytest = receipt.pytest;
  if (
    canonicalJson(pytest?.inner_sandbox_contract) !==
      canonicalJson({
        macos_outer_sandbox: false,
        parent_inet_audit_guard: true,
        product_child_macos_sandbox_required: true,
      }) ||
    pytest.collection?.exit_code !== 0 ||
    pytest.shards?.general?.exit_code !== 0 ||
    pytest.shards?.inner_sandbox?.exit_code !== 0
  ) {
    throw new Error("Gate 5 Gate 2 pytest shard authority is invalid");
  }
  const collectionStdout = validateGate2Artifact(
    receiptDir,
    pytest.collection.stdout,
  );
  const collectionStderr = validateGate2Artifact(
    receiptDir,
    pytest.collection.stderr,
  );
  if (collectionStderr.size_bytes !== 0) {
    throw new Error("Gate 5 Gate 2 pytest collection wrote stderr");
  }
  const collectionText = fs
    .readFileSync(collectionStdout.path)
    .toString("utf8");
  if (
    !Buffer.from(collectionText, "utf8").equals(
      fs.readFileSync(collectionStdout.path),
    )
  ) {
    throw new Error("Gate 5 Gate 2 pytest collection is not UTF-8");
  }
  const collectionDocuments = collectionText
    .split(/\r?\n/)
    .filter((line) => line.startsWith(GATE2_COLLECTION_PREFIX));
  if (collectionDocuments.length !== 1) {
    throw new Error(
      "Gate 5 Gate 2 pytest collection identity is invalid",
    );
  }
  const collected = parsePlaywrightJson(
    collectionDocuments[0].slice(GATE2_COLLECTION_PREFIX.length),
    "gate2-collection",
  );
  if (
    !Array.isArray(collected) ||
    collected.length === 0 ||
    new Set(collected).size !== collected.length ||
    collected.some(
      (nodeId) =>
        typeof nodeId !== "string" ||
        !nodeId.startsWith("tests/") ||
        !nodeId.includes("::"),
    )
  ) {
    throw new Error(
      "Gate 5 Gate 2 pytest collection identity is invalid",
    );
  }
  const partition = pytest.partition;
  const innerNodes = partition?.inner_sandbox?.node_ids;
  if (
    !Array.isArray(innerNodes) ||
    innerNodes.length === 0 ||
    new Set(innerNodes).size !== innerNodes.length ||
    innerNodes.some((nodeId) => !collected.includes(nodeId))
  ) {
    throw new Error("Gate 5 Gate 2 pytest partition is invalid");
  }
  const innerSet = new Set(innerNodes);
  const generalNodes = collected.filter(
    (nodeId) => !innerSet.has(nodeId),
  );
  if (
    generalNodes.length === 0 ||
    partition.exact_union !== true ||
    partition.overlap_count !== 0 ||
    canonicalJson(partition.collected) !==
      canonicalJson({
        count: collected.length,
        node_ids_sha256: sha256Utf8(canonicalJson(collected)),
      }) ||
    canonicalJson(partition.general) !==
      canonicalJson({
        count: generalNodes.length,
        node_ids_sha256: sha256Utf8(canonicalJson(generalNodes)),
      }) ||
    canonicalJson(partition.inner_sandbox) !==
      canonicalJson({
        count: innerNodes.length,
        node_ids: innerNodes,
        node_ids_sha256: sha256Utf8(canonicalJson(innerNodes)),
      })
  ) {
    throw new Error("Gate 5 Gate 2 pytest partition is invalid");
  }
  const basetemp = path.join(runtimeRoot, "basetemp");
  const collectionArgv = pytest.collection.argv;
  const generalArgv = pytest.shards.general.argv;
  const innerArgv = pytest.shards.inner_sandbox.argv;
  const outerProfile =
    "(version 1) (allow default) (deny network*)";
  if (
    !Array.isArray(collectionArgv) ||
    canonicalJson(collectionArgv.slice(0, 6)) !==
      canonicalJson([
        SANDBOX_EXEC,
        "-p",
        outerProfile,
        path.resolve(backendPython),
        "-I",
        "-B",
      ]) ||
    collectionArgv[6] !== "-c" ||
    typeof collectionArgv[7] !== "string" ||
    collectionArgv[7].length === 0 ||
    canonicalJson(collectionArgv.slice(8)) !==
      canonicalJson([
        "--collect-only",
        "-q",
        "--strict-config",
        "--strict-markers",
        "-p",
        "no:cacheprovider",
        "--basetemp",
        path.join(basetemp, "collection"),
        "-m",
        GATE2_MARKER_EXPRESSION,
        "tests",
      ]) ||
    canonicalJson(generalArgv) !==
      canonicalJson([
        SANDBOX_EXEC,
        "-p",
        outerProfile,
        path.resolve(backendPython),
        "-I",
        "-B",
        "-m",
        "pytest",
        "-q",
        "-rA",
        "--strict-config",
        "--strict-markers",
        "-p",
        "no:cacheprovider",
        "-m",
        GATE2_MARKER_EXPRESSION,
        "--basetemp",
        path.join(basetemp, "general"),
        ...innerNodes.map((nodeId) => `--deselect=${nodeId}`),
        "tests",
        `--junitxml=${path.join(
          receiptDir,
          "pytest-backend-non-postgres.junit.xml",
        )}`,
      ]) ||
    !Array.isArray(innerArgv) ||
    canonicalJson(innerArgv.slice(0, 3)) !==
      canonicalJson([path.resolve(backendPython), "-I", "-B"]) ||
    innerArgv[3] !== "-c" ||
    typeof innerArgv[4] !== "string" ||
    innerArgv[4].length === 0 ||
    canonicalJson(innerArgv.slice(5)) !==
      canonicalJson([
        "-q",
        "-rA",
        "--strict-config",
        "--strict-markers",
        "-p",
        "no:cacheprovider",
        "-m",
        GATE2_MARKER_EXPRESSION,
        "--basetemp",
        path.join(basetemp, "inner-sandbox"),
        ...innerNodes,
        `--junitxml=${path.join(
          receiptDir,
          "pytest-backend-non-postgres-inner-sandbox.junit.xml",
        )}`,
      ])
  ) {
    throw new Error("Gate 5 Gate 2 pytest command authority mismatch");
  }

  const shardArtifacts = {};
  for (const [name, record, expectedTotal] of [
    ["general", pytest.shards.general, generalNodes.length],
    ["inner_sandbox", pytest.shards.inner_sandbox, innerNodes.length],
  ]) {
    shardArtifacts[`${name}_stdout`] = validateGate2Artifact(
      receiptDir,
      record.stdout,
    );
    shardArtifacts[`${name}_stderr`] = validateGate2Artifact(
      receiptDir,
      record.stderr,
    );
    shardArtifacts[`${name}_junit`] = validateGate2Artifact(
      receiptDir,
      record.junit,
    );
    if (shardArtifacts[`${name}_stderr`].size_bytes !== 0) {
      throw new Error("Gate 5 Gate 2 pytest shard wrote stderr");
    }
    validateGate2PassResult(record.result, expectedTotal);
  }
  const combined = validateGate2PassResult(
    pytest.result,
    collected.length,
  );
  if (
    combined.passed !==
      pytest.shards.general.result.passed +
        pytest.shards.inner_sandbox.result.passed
  ) {
    throw new Error("Gate 5 Gate 2 pytest combined result is invalid");
  }
  return {
    artifacts: {
      collection_stderr: collectionStderr,
      collection_stdout: collectionStdout,
      network_stderr: networkStderr,
      network_stdout: networkStdout,
      ...shardArtifacts,
    },
    collected_node_ids: collected,
    junit_plan: [
      {
        expected_result: pytest.shards.general.result,
        expected_skips: [],
        path: shardArtifacts.general_junit.path,
      },
      {
        expected_result: pytest.shards.inner_sandbox.result,
        expected_skips: [],
        path: shardArtifacts.inner_sandbox_junit.path,
      },
    ],
    helper_projection: {
      collection_source: collectionArgv[7],
      environment: receipt.environment,
      inner_sandbox_node_ids: innerNodes,
      inner_shard_source: innerArgv[4],
      marker_expression: receipt.marker_expression,
      network_denial_source: network.argv[7],
      pytest_commands: {
        collection: collectionArgv,
        general: generalArgv,
        inner_sandbox: innerArgv,
      },
      transient_paths: receipt.transient_runtime?.paths,
    },
    result: combined,
  };
}

export function loadGate2ReceiptAuthority({
  backendPython,
  currentEnvironmentTree,
  currentIdentity,
  currentInputs,
  currentInstalledTree,
  expectedCommit,
  gate2Receipt,
  repoRoot,
  repository,
}) {
  const canonicalReceipt = path.resolve(gate2Receipt);
  if (
    !path.isAbsolute(gate2Receipt) ||
    path.basename(canonicalReceipt) !==
      "backend-non-postgres-receipt.json" ||
    fs.realpathSync(canonicalReceipt) !== canonicalReceipt ||
    pathIsInside(repoRoot, canonicalReceipt)
  ) {
    throw new Error("Gate 5 Gate 2 receipt path is unsafe");
  }
  const receiptInfo = fs.lstatSync(canonicalReceipt);
  const receiptDir = path.dirname(canonicalReceipt);
  const receiptDirInfo = fs.lstatSync(receiptDir);
  const receiptParentInfo = fs.lstatSync(path.dirname(receiptDir));
  if (
    receiptInfo.isSymbolicLink() ||
    !receiptInfo.isFile() ||
    receiptInfo.nlink !== 1 ||
    receiptDirInfo.isSymbolicLink() ||
    !receiptDirInfo.isDirectory() ||
    (typeof process.getuid === "function" &&
      (receiptInfo.uid !== process.getuid() ||
        receiptDirInfo.uid !== process.getuid())) ||
    (receiptInfo.mode & 0o077) !== 0 ||
    (receiptDirInfo.mode & 0o077) !== 0
  ) {
    throw new Error("Gate 5 Gate 2 receipt ownership/mode is unsafe");
  }
  const receiptBytes = fs.readFileSync(canonicalReceipt);
  const receiptText = receiptBytes.toString("utf8");
  if (
    !Buffer.from(receiptText, "utf8").equals(receiptBytes) ||
    receiptText.length === 0
  ) {
    throw new Error("Gate 5 Gate 2 receipt is not UTF-8");
  }
  const receipt = parsePlaywrightJson(
    receiptText,
    "gate2-receipt",
  );
  if (canonicalJson(receipt) !== receiptText) {
    throw new Error("Gate 5 Gate 2 receipt is not canonical JSON");
  }
  if (
    receipt.contract !== "quant-system-backend-non-postgres/v1" ||
    receipt.status !== "passed" ||
    Object.hasOwn(receipt, "error")
  ) {
    throw new Error("Gate 5 requires a passing Gate 2 receipt");
  }
  if (
    canonicalJson(receipt.evidence_directory) !==
      canonicalJson({
        mode: (receiptDirInfo.mode & 0o777)
          .toString(8)
          .padStart(3, "0"),
        owner_uid: receiptDirInfo.uid,
        parent_mode: (receiptParentInfo.mode & 0o777)
          .toString(8)
          .padStart(3, "0"),
        parent_owner_uid: receiptParentInfo.uid,
        path: receiptDir,
      }) ||
    receiptParentInfo.isSymbolicLink() ||
    !receiptParentInfo.isDirectory() ||
    (typeof process.getuid === "function" &&
      receiptParentInfo.uid !== process.getuid()) ||
    (receiptParentInfo.mode & 0o077) !== 0
  ) {
    throw new Error("Gate 5 Gate 2 evidence directory binding mismatch");
  }
  const expectedRepository = receiptRepositoryProjection(repository);
  for (const name of ["repository_before", "repository_after"]) {
    if (
      canonicalJson(receipt[name]) !== canonicalJson(expectedRepository)
    ) {
      throw new Error(`Gate 5 Gate 2 ${name} identity mismatch`);
    }
  }
  if (
    canonicalJson(receipt.inputs_before) !==
      canonicalJson(currentInputs) ||
    canonicalJson(receipt.inputs_after) !==
      canonicalJson(currentInputs)
  ) {
    throw new Error("Gate 5 Gate 2 source input identity mismatch");
  }

  const venv = path.dirname(path.dirname(path.resolve(backendPython)));
  const runtimeRoot = path.dirname(venv);
  const expectedTransientPaths = gate2TransientPaths(runtimeRoot);
  const expectedRuntimeRoot = path.join(
    repoRoot,
    ".tmp",
    `backend-non-postgres-${expectedCommit.slice(
      0,
      12,
    )}-${sha256Utf8(`${expectedCommit}\0${receiptDir}`).slice(0, 16)}`,
  );
  if (runtimeRoot !== expectedRuntimeRoot) {
    throw new Error("Gate 5 Gate 2 runtime digest binding mismatch");
  }
  const expectedWrapper = path.join(
    repoRoot,
    "scripts",
    "verify_backend_non_postgres.sh",
  );
  const command = receipt.command;
  const commandEntrypoint =
    Array.isArray(command?.argv) &&
    typeof command.argv[0] === "string"
      ? command.argv[0]
      : "";
  const resolvedCommandEntrypoint = path.resolve(
    repoRoot,
    commandEntrypoint,
  );
  if (
    command === null ||
    typeof command !== "object" ||
    command.cwd !== repoRoot ||
    resolvedCommandEntrypoint !== expectedWrapper ||
    canonicalJson(command.argv.slice(1)) !==
      canonicalJson([
        "--output-dir",
        receiptDir,
        "--expected-commit",
        expectedCommit,
      ]) ||
    canonicalJson(command.entrypoint_binding) !==
      canonicalJson({
        argument: commandEntrypoint,
        expected_path: expectedWrapper,
        resolved_path: expectedWrapper,
      }) ||
    command.environment_strategy !== "allowlist" ||
    command.may_touch_database !== false ||
    command.may_touch_network_during_install !== true ||
    command.may_touch_network_during_tests !== false ||
    command.may_touch_provider !== false ||
    command.may_touch_runtime !== false ||
    command.may_touch_trading !== false
  ) {
    throw new Error("Gate 5 Gate 2 command authority mismatch");
  }
  if (
    canonicalJson(receipt.fresh_environment) !==
      canonicalJson({
        inside_checkout: true,
        path: venv,
        preexisting: false,
      }) ||
    receipt.transient_runtime?.cleanup_owner !== "outer_collector" ||
    receipt.transient_runtime?.evidence_artifact !== false ||
    receipt.transient_runtime?.root !== runtimeRoot ||
    receipt.transient_runtime?.runner_recursive_cleanup !== false ||
    canonicalJson(receipt.transient_runtime?.paths) !==
      canonicalJson(expectedTransientPaths)
  ) {
    throw new Error("Gate 5 Gate 2 fresh environment binding mismatch");
  }

  const install = receipt.install;
  const uv = receipt.uv;
  if (
    install?.exit_code !== 0 ||
    !Array.isArray(install.argv) ||
    install.argv.length !== 7 ||
    !path.isAbsolute(String(install.argv[0])) ||
    canonicalJson(install.argv.slice(1, 6)) !==
      canonicalJson([
        "sync",
        "--frozen",
        "--no-editable",
        "--all-extras",
        "--python",
      ]) ||
    !path.isAbsolute(String(install.argv[6]))
  ) {
    throw new Error("Gate 5 Gate 2 installer authority mismatch");
  }
  const uvPath = path.resolve(String(uv?.realpath));
  let uvInfo;
  try {
    uvInfo = fs.lstatSync(uvPath);
  } catch {
    throw new Error("Gate 5 Gate 2 uv authority mismatch");
  }
  if (
    uvPath !== install.argv[0] ||
    uvInfo.isSymbolicLink() ||
    !uvInfo.isFile() ||
    !fs.existsSync(uvPath) ||
    (typeof process.getuid === "function" &&
      uvInfo.uid !== process.getuid()) ||
    (uvInfo.mode & 0o022) !== 0 ||
    !fs.statSync(uvPath).isFile() ||
    !/^[0-9a-f]{64}$/.test(String(uv?.sha256)) ||
    sha256Bytes(fs.readFileSync(uvPath)) !== uv.sha256 ||
    uv.version?.exit_code !== 0
  ) {
    throw new Error("Gate 5 Gate 2 uv authority mismatch");
  }
  fs.accessSync(uvPath, fs.constants.X_OK);
  const gate2NodeArgument = receipt.node?.argument;
  if (
    typeof gate2NodeArgument !== "string" ||
    !path.isAbsolute(gate2NodeArgument)
  ) {
    throw new Error("Gate 5 Gate 2 Node authority mismatch");
  }
  let currentGate2Node;
  let currentGate5Node;
  try {
    currentGate2Node = runtimeExecutableIdentity(gate2NodeArgument);
    currentGate5Node = runtimeExecutableIdentity(process.execPath);
  } catch {
    throw new Error("Gate 5 Gate 2 Node authority mismatch");
  }
  const nodeVersion = receipt.node?.version;
  const nodeVersionStdout = validateGate2Artifact(
    receiptDir,
    nodeVersion?.stdout,
  );
  const nodeVersionStderr = validateGate2Artifact(
    receiptDir,
    nodeVersion?.stderr,
  );
  const expectedNodeVersion = Buffer.from(`${process.version}\n`, "utf8");
  if (
    currentGate2Node.realpath !== currentGate5Node.realpath ||
    currentGate2Node.realpath_sha256 !==
      currentGate5Node.realpath_sha256 ||
    receipt.node.realpath !== currentGate2Node.realpath ||
    receipt.node.sha256 !== currentGate2Node.realpath_sha256 ||
    nodeVersion?.exit_code !== 0 ||
    canonicalJson(nodeVersion?.argv) !==
      canonicalJson([currentGate2Node.realpath, "--version"]) ||
    nodeVersionStdout.size_bytes !== expectedNodeVersion.length ||
    nodeVersionStdout.sha256 !== sha256Bytes(expectedNodeVersion) ||
    nodeVersionStderr.size_bytes !== 0 ||
    nodeVersion?.stdout_stderr_sha256 !==
      sha256Bytes(
        Buffer.concat([
          expectedNodeVersion,
          Buffer.from([0]),
        ]),
      ) ||
    canonicalJson(receipt.environment) !==
      canonicalJson(
        gate2ExpectedEnvironment({
          nodePath: currentGate2Node.realpath,
          runtimeRoot,
          uvPath,
        }),
      )
  ) {
    throw new Error("Gate 5 Gate 2 Node/environment authority mismatch");
  }
  const inventory = receipt.dependency_inventory;
  if (
    inventory?.exit_code !== 0 ||
    !Array.isArray(inventory.argv) ||
    inventory.argv.length !== 6 ||
    inventory.argv[0] !== install.argv[0] ||
    canonicalJson(inventory.argv.slice(1)) !==
      canonicalJson([
        "pip",
        "freeze",
        "--strict",
        "--python",
        path.resolve(backendPython),
      ])
  ) {
    throw new Error("Gate 5 Gate 2 inventory authority mismatch");
  }
  const python = receipt.python;
  if (
    python?.exit_code !== 0 ||
    !Array.isArray(python.argv) ||
    python.argv.length !== 5 ||
    canonicalJson(python.argv.slice(0, 3)) !==
      canonicalJson([path.resolve(backendPython), "-I", "-B"]) ||
    python.argv[3] !== "-c" ||
    typeof python.argv[4] !== "string" ||
    python.argv[4].length === 0 ||
    python.lock_sha256 !== currentInputs["uv.lock"].sha256 ||
    python.stdout?.embedded_in_receipt !== true ||
    !/^[0-9a-f]{64}$/.test(String(python.stdout?.sha256)) ||
    !Number.isInteger(python.stdout?.size_bytes) ||
    python.stdout.size_bytes <= 0 ||
    canonicalJson(gate2PythonProjection(python.identity)) !==
      canonicalJson(gate2PythonProjection(currentIdentity))
  ) {
    throw new Error("Gate 5 Gate 2 Python identity mismatch");
  }
  if (
    canonicalJson(receipt.installed_quant_system_tree_before) !==
      canonicalJson(currentInstalledTree) ||
    canonicalJson(receipt.installed_quant_system_tree_after) !==
      canonicalJson(currentInstalledTree)
  ) {
    throw new Error(
      "Gate 5 installed quant_system bytes differ from Gate 2",
    );
  }
  if (
    canonicalJson(receipt.installed_environment_tree_before) !==
      canonicalJson(currentEnvironmentTree) ||
    canonicalJson(receipt.installed_environment_tree_after) !==
      canonicalJson(currentEnvironmentTree)
  ) {
    throw new Error(
      "Gate 5 installed backend environment bytes differ from Gate 2",
    );
  }
  const environmentNormalization =
    receipt.installed_environment_normalization;
  if (
    environmentNormalization?.path !== ".lock" ||
    environmentNormalization.after_mode !== "600" ||
    !/^[0-7]{3}$/.test(
      String(environmentNormalization.before_mode),
    ) ||
    (typeof process.getuid === "function" &&
      environmentNormalization.owner_uid !== process.getuid())
  ) {
    throw new Error(
      "Gate 5 Gate 2 environment normalization authority mismatch",
    );
  }
  const testSemantics = validateGate2TestSemantics({
    backendPython,
    receipt,
    receiptDir,
    runtimeRoot,
  });

  const validatedArtifacts = {
    dependency_inventory_stderr: validateGate2Artifact(
      receiptDir,
      inventory.stderr,
    ),
    dependency_inventory_stdout: validateGate2Artifact(
      receiptDir,
      inventory.stdout,
    ),
    install_stderr: validateGate2Artifact(
      receiptDir,
      install.stderr,
    ),
    install_stdout: validateGate2Artifact(
      receiptDir,
      install.stdout,
    ),
    node_version_stderr: nodeVersionStderr,
    node_version_stdout: nodeVersionStdout,
    python_stderr: validateGate2Artifact(
      receiptDir,
      python.stderr,
    ),
    uv_version_stderr: validateGate2Artifact(
      receiptDir,
      uv.version.stderr,
    ),
    uv_version_stdout: validateGate2Artifact(
      receiptDir,
      uv.version.stdout,
    ),
    ...testSemantics.artifacts,
  };
  if (
    validatedArtifacts.dependency_inventory_stdout.size_bytes === 0 ||
    validatedArtifacts.python_stderr.size_bytes !== 0
  ) {
    throw new Error("Gate 5 Gate 2 artifact content authority mismatch");
  }
  return {
    artifacts: validatedArtifacts,
    collected_node_ids: testSemantics.collected_node_ids,
    contract: receipt.contract,
    environment_path: venv,
    install_exit_code: install.exit_code,
    installer_path: uvPath,
    junit_plan: testSemantics.junit_plan,
    helper_projection: testSemantics.helper_projection,
    node_path: currentGate2Node.realpath,
    receipt_path: canonicalReceipt,
    receipt_sha256: sha256Bytes(receiptBytes),
    receipt_size_bytes: receiptBytes.length,
    source_inputs: currentInputs,
    status: receipt.status,
    test_result: testSemantics.result,
    runtime_root: runtimeRoot,
  };
}

function collectBackendAuthority({
  backendPython,
  expectedCommit,
  gate2Receipt,
  repoRoot,
  repository,
}) {
  const canonicalPython = path.resolve(backendPython);
  assertPrivateRealAncestors(repoRoot, canonicalPython);
  const pythonInfo = fs.lstatSync(canonicalPython);
  if (
    (!pythonInfo.isFile() && !pythonInfo.isSymbolicLink()) ||
    (typeof process.getuid === "function" &&
      pythonInfo.uid !== process.getuid())
  ) {
    throw new Error("Gate 5 backend Python must be an owned file or symlink");
  }
  fs.accessSync(canonicalPython, fs.constants.X_OK);
  const pythonRealpath = fs.realpathSync(canonicalPython);
  const pythonLinkTarget = pythonInfo.isSymbolicLink()
    ? fs.readlinkSync(canonicalPython)
    : null;
  const sandboxInfo = fs.lstatSync(SANDBOX_EXEC);
  if (
    sandboxInfo.isSymbolicLink() ||
    !sandboxInfo.isFile() ||
    sandboxInfo.uid !== 0 ||
    (sandboxInfo.mode & 0o022) !== 0
  ) {
    throw new Error("Gate 5 backend probe sandbox is unsafe");
  }
  fs.accessSync(SANDBOX_EXEC, fs.constants.X_OK);
  const probe = spawnSync(
    SANDBOX_EXEC,
    [
      "-p",
      BACKEND_PROBE_SANDBOX_PROFILE,
      canonicalPython,
      "-I",
      "-B",
      "-c",
      BACKEND_IDENTITY_PROBE,
    ],
    {
      cwd: repoRoot,
      encoding: "utf8",
      env: {
        LANG: "C",
        LC_ALL: "C",
        PATH: "/usr/bin:/bin",
      },
      maxBuffer: 64 * 1024 * 1024,
      timeout: 30_000,
    },
  );
  if (
    probe.error !== undefined ||
    probe.signal !== null ||
    probe.status !== 0 ||
    typeof probe.stdout !== "string" ||
    typeof probe.stderr !== "string" ||
    probe.stderr.length !== 0 ||
    !probe.stdout.endsWith("\n")
  ) {
    throw new Error(
      `Gate 5 backend identity probe failed: status=${String(
        probe.status,
      )} signal=${String(probe.signal)} stderr=${String(probe.stderr).trim()}`,
    );
  }
  const rawDocument = probe.stdout.slice(0, -1);
  const document = parsePlaywrightJson(
    rawDocument,
    "backend-python-identity",
  );
  if (canonicalJson(document) !== rawDocument) {
    throw new Error("Gate 5 backend identity probe is not canonical JSON");
  }
  const identity = validateBackendPythonIdentity({
    backendPython: canonicalPython,
    document,
    expectedCommit,
    repoRoot,
  });
  if (
    path.resolve(identity.sys_executable_realpath) !== pythonRealpath
  ) {
    throw new Error("Gate 5 backend Python realpath identity mismatch");
  }
  const currentInputs = gate2InputIdentity(repoRoot);
  const installedModuleTree = regularTreeIdentity(
    path.dirname(identity.quant_system_file),
  );
  const installedEnvironmentTree = installedEnvironmentTreeIdentity(
    path.dirname(path.dirname(canonicalPython)),
  );
  const gate2Authority = loadGate2ReceiptAuthority({
    backendPython: canonicalPython,
    currentEnvironmentTree: installedEnvironmentTree,
    currentIdentity: identity,
    currentInputs,
    currentInstalledTree: installedModuleTree,
    expectedCommit,
    gate2Receipt,
    repoRoot,
    repository,
  });
  const gate2Helper = path.join(
    repoRoot,
    "scripts",
    "backend_non_postgres_gate.py",
  );
  const helperValidationPayload = canonicalJson({
    junit_plan: gate2Authority.junit_plan,
    node: gate2Authority.node_path,
    output: path.dirname(gate2Authority.receipt_path),
    python: canonicalPython,
    runtime_root: gate2Authority.runtime_root,
    uv: gate2Authority.installer_path,
  });
  const junitProbe = spawnSync(
    SANDBOX_EXEC,
    [
      "-p",
      BACKEND_PROBE_SANDBOX_PROFILE,
      canonicalPython,
      "-I",
      "-B",
      "-c",
      GATE2_JUNIT_VALIDATION_SOURCE,
      gate2Helper,
      helperValidationPayload,
    ],
    {
      cwd: repoRoot,
      encoding: "utf8",
      env: {
        LANG: "C",
        LC_ALL: "C",
        PATH: "/usr/bin:/bin",
      },
      maxBuffer: 64 * 1024 * 1024,
      timeout: 30_000,
    },
  );
  if (
    junitProbe.error !== undefined ||
    junitProbe.signal !== null ||
    junitProbe.status !== 0 ||
    typeof junitProbe.stdout !== "string" ||
    typeof junitProbe.stderr !== "string" ||
    junitProbe.stderr.length !== 0 ||
    !junitProbe.stdout.endsWith("\n")
  ) {
    throw new Error(
      `Gate 5 Gate 2 JUnit semantic validation failed: status=${String(
        junitProbe.status,
      )} signal=${String(junitProbe.signal)}`,
    );
  }
  const junitRaw = junitProbe.stdout.slice(0, -1);
  const helperProjection = parsePlaywrightJson(
    junitRaw,
    "gate2-helper-projection",
  );
  const expectedHelperProjection = {
    ...gate2Authority.helper_projection,
    junit_results: gate2Authority.junit_plan.map(
      (item) => item.expected_result,
    ),
  };
  if (
    canonicalJson(helperProjection) !== junitRaw ||
    canonicalJson(helperProjection) !==
      canonicalJson(expectedHelperProjection)
  ) {
    throw new Error(
      "Gate 5 Gate 2 final-helper authority mismatch",
    );
  }
  const currentCollectionCommand =
    helperProjection.pytest_commands.collection;
  const collectionProbe = spawnSync(
    currentCollectionCommand[0],
    currentCollectionCommand.slice(1),
    {
      cwd: repoRoot,
      encoding: null,
      env: helperProjection.environment.tests,
      maxBuffer: 64 * 1024 * 1024,
      timeout: 120_000,
    },
  );
  const collectionStdout = Buffer.isBuffer(
    collectionProbe.stdout,
  )
    ? collectionProbe.stdout
    : Buffer.alloc(0);
  const collectionStderr = Buffer.isBuffer(
    collectionProbe.stderr,
  )
    ? collectionProbe.stderr
    : Buffer.alloc(0);
  const collectionText = collectionStdout.toString("utf8");
  const collectionDocuments = collectionText
    .split(/\r?\n/)
    .filter((line) =>
      line.startsWith(GATE2_COLLECTION_PREFIX),
    );
  let currentCollectedNodeIds;
  try {
    currentCollectedNodeIds = parsePlaywrightJson(
      collectionDocuments[0]?.slice(
        GATE2_COLLECTION_PREFIX.length,
      ) ?? "",
      "gate2-current-collection",
    );
  } catch {
    throw new Error(
      "Gate 5 current Gate 2 collection authority is invalid",
    );
  }
  if (
    collectionProbe.error !== undefined ||
    collectionProbe.signal !== null ||
    collectionProbe.status !== 0 ||
    collectionDocuments.length !== 1 ||
    !Buffer.from(collectionText, "utf8").equals(
      collectionStdout,
    ) ||
    collectionStderr.length !== 0 ||
    canonicalJson(currentCollectedNodeIds) !==
      canonicalJson(gate2Authority.collected_node_ids)
  ) {
    throw new Error(
      "Gate 5 current Gate 2 collection differs from the receipt",
    );
  }
  const inventoryProbe = spawnSync(
    SANDBOX_EXEC,
    [
      "-p",
      BACKEND_PROBE_SANDBOX_PROFILE,
      gate2Authority.installer_path,
      "pip",
      "freeze",
      "--strict",
      "--python",
      canonicalPython,
    ],
    {
      cwd: repoRoot,
      encoding: null,
      env: {
        HOME: "/tmp",
        LANG: "C",
        LC_ALL: "C",
        PATH: "/usr/bin:/bin",
        UV_NO_CONFIG: "1",
        UV_PYTHON_DOWNLOADS: "never",
      },
      maxBuffer: 64 * 1024 * 1024,
      timeout: 30_000,
    },
  );
  const inventoryStdout = Buffer.isBuffer(inventoryProbe.stdout)
    ? inventoryProbe.stdout
    : Buffer.alloc(0);
  const inventoryStderr = Buffer.isBuffer(inventoryProbe.stderr)
    ? inventoryProbe.stderr
    : Buffer.alloc(0);
  const expectedInventory =
    gate2Authority.artifacts.dependency_inventory_stdout;
  if (
    inventoryProbe.error !== undefined ||
    inventoryProbe.signal !== null ||
    inventoryProbe.status !== 0 ||
    inventoryStdout.length !== expectedInventory.size_bytes ||
    sha256Bytes(inventoryStdout) !== expectedInventory.sha256
  ) {
    throw new Error(
      `Gate 5 current dependency inventory differs from Gate 2: status=${String(
        inventoryProbe.status,
      )} signal=${String(inventoryProbe.signal)}`,
    );
  }
  const inventoryBytes = Buffer.from(
    canonicalJson(identity.dependency_inventory),
    "utf8",
  );
  return {
    backend_python: {
      invoked_path: canonicalPython,
      invoked_sha256: sha256Bytes(fs.readFileSync(canonicalPython)),
      link_target: pythonLinkTarget,
      realpath: pythonRealpath,
      realpath_sha256: sha256Bytes(fs.readFileSync(pythonRealpath)),
    },
    command: {
      argv: [
        SANDBOX_EXEC,
        "-p",
        BACKEND_PROBE_SANDBOX_PROFILE,
        canonicalPython,
        "-I",
        "-B",
        "-c",
        "<embedded-probe>",
      ],
      cwd: repoRoot,
      database_policy: "no-write-sandbox",
      environment_names: ["LANG", "LC_ALL", "PATH"],
      network_policy: "sandbox-denied",
      provider_policy: "network-and-write-sandbox",
      sandbox: {
        path: SANDBOX_EXEC,
        profile: BACKEND_PROBE_SANDBOX_PROFILE,
        sha256: sha256Bytes(fs.readFileSync(SANDBOX_EXEC)),
      },
      trading_policy: "network-and-write-sandbox",
    },
    dependency_inventory: {
      count: identity.dependency_inventory.length,
      entries_sha256: sha256Bytes(inventoryBytes),
      gate2_freeze_recheck: {
        exit_code: inventoryProbe.status,
        stderr_sha256: sha256Bytes(inventoryStderr),
        stderr_size_bytes: inventoryStderr.length,
        stdout_sha256: sha256Bytes(inventoryStdout),
        stdout_size_bytes: inventoryStdout.length,
      },
    },
    expected_commit: expectedCommit,
    gate2: gate2Authority,
    gate2_junit_validation: {
      argv: [
        SANDBOX_EXEC,
        "-p",
        BACKEND_PROBE_SANDBOX_PROFILE,
        canonicalPython,
        "-I",
        "-B",
        "-c",
        "<embedded-gate2-junit-validator>",
        gate2Helper,
        "<canonical-validation-plan>",
      ],
      exit_code: junitProbe.status,
      result: helperProjection,
      stderr_sha256: sha256Utf8(junitProbe.stderr),
      stderr_size_bytes: Buffer.byteLength(
        junitProbe.stderr,
        "utf8",
      ),
      stdout_sha256: sha256Utf8(junitProbe.stdout),
      stdout_size_bytes: Buffer.byteLength(
        junitProbe.stdout,
        "utf8",
      ),
    },
    gate2_collection_recheck: {
      argv: currentCollectionCommand,
      exit_code: collectionProbe.status,
      node_ids_sha256: sha256Utf8(
        canonicalJson(currentCollectedNodeIds),
      ),
      stderr_sha256: sha256Bytes(collectionStderr),
      stderr_size_bytes: collectionStderr.length,
      stdout_sha256: sha256Bytes(collectionStdout),
      stdout_size_bytes: collectionStdout.length,
    },
    identity,
    installed_module_tree: installedModuleTree,
    installed_environment_tree: installedEnvironmentTree,
    inputs: {
      "pyproject.toml": fileIdentity(
        path.join(repoRoot, "pyproject.toml"),
      ),
      "scripts/backend_non_postgres_gate.py": fileIdentity(
        path.join(repoRoot, "scripts", "backend_non_postgres_gate.py"),
      ),
      "scripts/verify_backend_non_postgres.sh": fileIdentity(
        path.join(repoRoot, "scripts", "verify_backend_non_postgres.sh"),
      ),
      "src/frontend/scripts/run-hermes-gate5.mjs": fileIdentity(
        fileURLToPath(import.meta.url),
      ),
      "uv.lock": fileIdentity(path.join(repoRoot, "uv.lock")),
    },
    probe: {
      canonical_stdout: true,
      stderr_sha256: sha256Utf8(probe.stderr),
      stdout_sha256: sha256Utf8(probe.stdout),
    },
    repository,
    schema_version: "hermes-gate5-backend-authority.v1",
  };
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
    row.env.PYTHONPYCACHEPREFIX,
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
  backendAuthority,
  execute,
  frontendAuthority,
  matrix,
  now = () => new Date(),
  reportDir,
  verifyAuthority,
}) {
  if (!Array.isArray(matrix) || matrix.length === 0) {
    throw new Error("Gate 5 matrix must not be empty");
  }
  if (typeof execute !== "function") {
    throw new Error("Gate 5 row executor is required");
  }
  if (
    backendAuthority === null ||
    typeof backendAuthority !== "object" ||
    backendAuthority.schema_version !==
      "hermes-gate5-backend-authority.v1"
  ) {
    throw new Error("Gate 5 backend authority is required");
  }
  if (
    frontendAuthority === null ||
    typeof frontendAuthority !== "object" ||
    frontendAuthority.schema_version !==
      "hermes-gate5-frontend-authority.v1"
  ) {
    throw new Error("Gate 5 frontend authority is required");
  }
  if (typeof verifyAuthority !== "function") {
    throw new Error("Gate 5 final authority verifier is required");
  }
  const expectedFrontendPath = `${path.dirname(
    frontendAuthority.install.node.realpath,
  )}:/usr/bin:/bin`;
  if (
    matrix.some(
      (row) =>
        row.env?.PATH !== expectedFrontendPath ||
        !path.isAbsolute(String(row.command)),
    )
  ) {
    throw new Error(
      "Gate 5 matrix is not bound to the authorized frontend PATH",
    );
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
    backend_authority: backendAuthority,
    backend_authority_after: null,
    frontend_authority: frontendAuthority,
    frontend_authority_after: null,
    ended_at: null,
    report_dir: path.resolve(reportDir),
    repository_after: null,
    final_authority_error: null,
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
    const rowStartedAt = now().toISOString();

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
    const stderrBytes = Buffer.from(stderr, "utf8");
    const stdoutBytes = Buffer.from(capturedOutput, "utf8");
    const playwrightReportArtifact =
      playwrightReportFile === null
        ? null
        : fileIdentity(
            path.join(reportDir, playwrightReportFile),
          );
    if (result?.closeConfirmed === false) {
      retainRuntimeReasons.push(
        `${row.id}: child ${String(result.processId ?? "unknown")} did not close after SIGTERM`,
      );
    }
    summary.rows.push({
      args: [...row.args],
      artifacts: {
        playwright_report: playwrightReportArtifact,
        stderr: {
          path: stderrFile,
          sha256: sha256Bytes(stderrBytes),
          size_bytes: stderrBytes.length,
        },
        stdout:
          stdoutFile === null
            ? {
                digest_only: true,
                sha256: sha256Bytes(stdoutBytes),
                size_bytes: stdoutBytes.length,
              }
            : {
                path: stdoutFile,
                sha256: sha256Bytes(stdoutBytes),
                size_bytes: stdoutBytes.length,
              },
      },
      backend_port: row.backendPort,
      close_confirmed: result?.closeConfirmed !== false,
      command: row.command,
      completed_at: now().toISOString(),
      contract: { ...row.contract },
      environment: { ...row.env },
      environment_sha256: sha256Utf8(canonicalJson(row.env)),
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
      path: row.env.PATH,
      playwright_report: playwrightReportFile,
      process_id:
        Number.isInteger(result?.processId) ? result.processId : null,
      rollback_port: row.rollbackPort ?? null,
      run_id: row.runId,
      runtime_root: row.runtimeRoot,
      started_at: rowStartedAt,
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

  let observedAuthority = null;
  try {
    observedAuthority = verifyAuthority();
    summary.backend_authority_after = observedAuthority.backend;
    summary.frontend_authority_after = observedAuthority.frontend;
    summary.repository_after = observedAuthority.repository;
    if (
      canonicalJson(observedAuthority.backend) !==
        canonicalJson(backendAuthority) ||
      canonicalJson(observedAuthority.frontend) !==
        canonicalJson(frontendAuthority) ||
      canonicalJson(observedAuthority.repository) !==
        canonicalJson(backendAuthority.repository)
    ) {
      throw new Error(
        "repository, backend, or frontend identity changed during Gate 5",
      );
    }
  } catch (error) {
    const authorityError = `Gate 5 final authority failed: ${
      error instanceof Error ? error.message : String(error)
    }`;
    summary.final_authority_error = authorityError;
    failedRows.push("final-authority");
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
  const {
    backendPython,
    expectedCommit,
    frontendInstallReceipt,
    gate2Receipt,
    outputDir,
  } = assertSafeCliArgs(argv);
  const scriptPath = fileURLToPath(import.meta.url);
  const frontendRoot = path.dirname(path.dirname(scriptPath));
  const repoRoot = path.resolve(frontendRoot, "..", "..");
  assertEmptyOwnerOnlyOutputDir(outputDir);
  const startedAt = new Date().toISOString();
  try {
    const playwrightCli = path.join(
      frontendRoot,
      "node_modules",
      "@playwright",
      "test",
      "cli.js",
    );
    for (const [label, candidate] of [
      ["backend Python", backendPython],
      ["frontend install receipt", frontendInstallReceipt],
      ["Gate 2 receipt", gate2Receipt],
      ["Playwright CLI", playwrightCli],
    ]) {
      if (!fs.existsSync(candidate)) {
        throw new Error(`Gate 5 ${label} is missing: ${candidate}`);
      }
    }
    const repositoryAuthority = collectRepositoryAuthority(
      repoRoot,
      expectedCommit,
    );
    const playwrightBrowsersPath = resolvePlaywrightBrowsersPath(
      process.env,
    );
    const backendAuthority = collectBackendAuthority({
      backendPython,
      expectedCommit,
      gate2Receipt,
      repoRoot,
      repository: repositoryAuthority,
    });
    const frontendAuthority = collectFrontendAuthority({
      expectedCommit,
      frontendInstallReceipt,
      frontendRoot,
      playwrightBrowsersPath,
      repository: repositoryAuthority,
    });

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
        LANG: "C",
        LC_ALL: "C",
        PATH: frontendAuthority.install.environment.PATH,
        PLAYWRIGHT_BROWSERS_PATH: playwrightBrowsersPath,
      },
      frontendNode: frontendAuthority.install.node.realpath,
      frontendNpmCli: frontendAuthority.install.npm.realpath,
      outputDir,
      ports,
      runToken,
    });
    const summary = await runGate5Matrix({
      backendAuthority,
      execute: createRowExecutor(frontendRoot),
      frontendAuthority,
      matrix,
      reportDir: outputDir,
      verifyAuthority: () => {
        const repository = collectRepositoryAuthority(
          repoRoot,
          expectedCommit,
        );
        return {
          backend: collectBackendAuthority({
            backendPython,
            expectedCommit,
            gate2Receipt,
            repoRoot,
            repository,
          }),
          frontend: collectFrontendAuthority({
            expectedCommit,
            frontendInstallReceipt,
            frontendRoot,
            playwrightBrowsersPath,
            repository,
          }),
          repository,
        };
      },
    });
    process.stdout.write(
      `HERMES_GATE5_PASS ${path.join(summary.report_dir, "gate5-summary.json")}\n`,
    );
  } catch (error) {
    const summaryPath = path.join(outputDir, "gate5-summary.json");
    if (!fs.existsSync(summaryPath)) {
      writeCanonicalSummary(outputDir, {
        backend_authority: null,
        backend_authority_after: null,
        command: {
          argv: [scriptPath, ...argv],
          cwd: repoRoot,
        },
        ended_at: new Date().toISOString(),
        error: error instanceof Error ? error.message : String(error),
        failed_rows: ["preflight"],
        final_authority_error: null,
        phase: "preflight",
        report_dir: outputDir,
        repository_after: null,
        rows: [],
        runtime_cleanup: {
          error: null,
          status: "not-started",
        },
        runtime_root: null,
        schema_version: "hermes-gate5.v1",
        started_at: startedAt,
        status: "failed",
      });
    }
    throw error;
  }
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
  frontendNode = process.execPath,
  frontendNpmCli = path.join(
    path.dirname(process.execPath),
    "npm",
  ),
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
  if (
    !path.isAbsolute(frontendNode) ||
    !path.isAbsolute(frontendNpmCli)
  ) {
    throw new Error(
      "Gate 5 frontend Node/npm commands must be absolute",
    );
  }
  const boundFrontendPath = `${path.dirname(
    frontendNode,
  )}:/usr/bin:/bin`;

  const definitions = [
    {
      args: [frontendNpmCli, "run", "test:gate5-support"],
      command: frontendNode,
      contract: { expected: 44, expectedSkips: NO_SKIPS, skipped: 0 },
      id: "support",
      kind: "node-test",
      timeoutMs: 60_000,
    },
    {
      contract: { expected: 2, expectedSkips: NO_SKIPS, skipped: 0 },
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
      contract: { expected: 7, expectedSkips: NO_SKIPS, skipped: 0 },
      grep: "@lifecycle-fixture",
      id: "lifecycle",
      kind: "playwright",
      testFiles: ["tests/e2e/hermes-lifecycle.spec.ts"],
      timeoutMs: 900_000,
    },
    {
      contract: { expected: 2, expectedSkips: NO_SKIPS, skipped: 0 },
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
      PATH: boundFrontendPath,
      PW_BACKEND_PORT: String(backendPort),
      PW_E2E: "1",
      PW_E2E_RUN_ID: runId,
      PW_FRONTEND_PORT: String(frontendPort),
      PW_PYTHON: backendPython,
      PYTHONDONTWRITEBYTECODE: "1",
      PYTHONNOUSERSITE: "1",
      PYTHONPYCACHEPREFIX: path.join(runtimeRoot, "pycache"),
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
