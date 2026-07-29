import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import os from "node:os";
import path from "node:path";
import { describe, it } from "node:test";

import {
  assertSafeCliArgs,
  buildGate5Matrix,
  canonicalJson as serializeCanonicalEvidence,
  collectRepositoryAuthority,
  frontendInputIdentity,
  frontendInstallEnvironment,
  installedEnvironmentTreeIdentity,
  loadFrontendInstallAuthority,
  loadGate2ReceiptAuthority,
  parsePlaywrightJson,
  runGate5Matrix,
  runtimeExecutableIdentity,
  validateBackendPythonIdentity,
  validatePlaywrightReport,
  validateSupportTap,
} from "./run-hermes-gate5.mjs";
import {
  parseFrontendInstallArgs,
  runFrontendFreshInstall,
} from "./prepare-hermes-gate5-install.mjs";

const FRONTEND_ROOT = path.dirname(
  path.dirname(fileURLToPath(import.meta.url)),
);

function unitBackendAuthority() {
  return {
    repository: {
      branch: "unit-test",
      clean: true,
      commit: "c".repeat(40),
    },
    schema_version: "hermes-gate5-backend-authority.v1",
  };
}

function unitFrontendAuthority() {
  return {
    install: {
      node: {
        realpath: process.execPath,
      },
    },
    repository: {
      branch: "unit-test",
      clean: true,
      commit: "c".repeat(40),
    },
    schema_version: "hermes-gate5-frontend-authority.v1",
  };
}

function runGit(repository, ...args) {
  const result = spawnSync(
    "/usr/bin/git",
    ["-C", repository, ...args],
    {
      encoding: "utf8",
      env: {
        LANG: "C",
        LC_ALL: "C",
        PATH: "/usr/bin:/bin",
      },
      timeout: 30_000,
    },
  );
  assert.equal(
    result.status,
    0,
    `git ${args.join(" ")}: ${result.stderr}`,
  );
  return result.stdout.trim();
}

function canonicalJson(value) {
  const normalize = (candidate) => {
    if (Array.isArray(candidate)) {
      return candidate.map(normalize);
    }
    if (
      candidate !== null &&
      typeof candidate === "object"
    ) {
      return Object.fromEntries(
        Object.keys(candidate)
          .sort()
          .map((key) => [key, normalize(candidate[key])]),
      );
    }
    return candidate;
  };
  return JSON.stringify(normalize(value));
}

function writeArtifact(directory, name, contents) {
  const filePath = path.join(directory, name);
  fs.writeFileSync(filePath, contents, {
    encoding: "utf8",
    mode: 0o600,
  });
  return {
    path: name,
    sha256: crypto
      .createHash("sha256")
      .update(contents, "utf8")
      .digest("hex"),
    size_bytes: Buffer.byteLength(contents, "utf8"),
  };
}

function playwrightReport({
  expected = 2,
  skipped = [],
  stats = {},
} = {}) {
  const passedSpecs = Array.from({ length: expected }, (_, index) => ({
    file: "hermes-workbench.spec.ts",
    tests: [
      {
        annotations: [],
        expectedStatus: "passed",
        projectName: "chromium",
        results: [{ status: "passed" }],
        status: "expected",
      },
    ],
    title: `expected test ${index + 1}`,
  }));
  const skippedSpecs = skipped.map((entry) => ({
    file: entry.file,
    tests: [
      {
        annotations: [{ description: entry.reason, type: "skip" }],
        expectedStatus: "skipped",
        projectName: "chromium",
        results: [{ status: "skipped" }],
        status: "skipped",
      },
    ],
    title: entry.title,
  }));
  return {
    errors: [],
    stats: {
      expected,
      flaky: 0,
      skipped: skipped.length,
      unexpected: 0,
      ...stats,
    },
    suites: [
      {
        specs: [...passedSpecs, ...skippedSpecs],
        suites: [],
        title: "root",
      },
    ],
  };
}

function playwrightReportForRow(row) {
  const skipped = row.contract.expectedSkips.map(({ id, reason }) => {
    const [file, title, projectName] = id.split("::");
    assert.equal(projectName, "chromium");
    return { file, reason, title };
  });
  return playwrightReport({
    expected: row.contract.expected,
    skipped,
  });
}

describe("Hermes Gate 5 release authority", () => {
  it("defines the complete ordered browser matrix", () => {
    const matrix = buildGate5Matrix({
      outputDir: "/release-evidence/unit",
      ports: Array.from({ length: 19 }, (_, index) => 41_000 + index),
      runToken: "unit",
    });

    assert.deepEqual(
      matrix.map((row) => row.id),
      [
        "support",
        "real-smoke",
        "fixture-normal",
        "fixture-degraded",
        "fixture-offline",
        "fixture-empty",
        "fixture-long-content",
        "lifecycle",
        "rollback",
      ],
    );
  });

  it("assigns every row a unique port pair and run id", () => {
    const matrix = buildGate5Matrix({
      outputDir: "/release-evidence/unique",
      ports: Array.from({ length: 19 }, (_, index) => 42_000 + index),
      runToken: "unique",
    });

    assert.equal(
      new Set(matrix.flatMap((row) => [row.backendPort, row.frontendPort])).size,
      matrix.length * 2,
    );
    assert.equal(new Set(matrix.map((row) => row.runId)).size, matrix.length);

    const rollback = matrix.at(-1);
    assert.equal(typeof rollback.rollbackPort, "number");
    assert.ok(
      !matrix
        .flatMap((row) => [row.backendPort, row.frontendPort])
        .includes(rollback.rollbackPort),
    );
  });

  it("pins every browser row to one worker, JSON evidence, no snapshot writes, and no live sessions", () => {
    const matrix = buildGate5Matrix({
      outputDir: "/release-evidence/safe-argv",
      ports: Array.from({ length: 19 }, (_, index) => 43_000 + index),
      runToken: "safe-argv",
    });

    const browserRows = matrix.filter(
      (candidate) => candidate.kind === "playwright",
    );
    assert.equal(browserRows.length, 8);
    for (const row of browserRows) {
      assert.equal(Number.isInteger(row.timeoutMs), true, row.id);
      assert.ok(row.timeoutMs > 0, row.id);
      assert.ok(row.args.includes("--workers=1"), row.id);
      assert.ok(row.args.includes("--reporter=json"), row.id);
      assert.ok(row.args.includes("--project=chromium"), row.id);
      assert.ok(row.args.includes("--forbid-only"), row.id);
      assert.ok(row.args.includes("--update-snapshots=none"), row.id);
      assert.ok(
        row.args.includes("--grep-invert=@live-hermes-sessions"),
        row.id,
      );
      assert.equal(
        row.args.some(
          (arg) =>
            arg.startsWith("--update-snapshots") &&
            arg !== "--update-snapshots=none",
        ),
        false,
        row.id,
      );
    }
  });

  it("binds each browser row to the exact specs, selector, and pass/skip contract", () => {
    const matrix = buildGate5Matrix({
      outputDir: "/release-evidence/contracts",
      ports: Array.from({ length: 19 }, (_, index) => 44_000 + index),
      runToken: "contracts",
    });
    const byId = Object.fromEntries(matrix.map((row) => [row.id, row]));
    const fixtureFiles = [
      "tests/e2e/hermes-workbench.spec.ts",
      "tests/e2e/hermes-workbench-visual.spec.ts",
      "tests/e2e/hermes-closure-matrix.spec.ts",
      "tests/e2e/hermes-closure-quality.spec.ts",
    ];

    assert.equal(byId.support.kind, "node-test");
    assert.deepEqual(byId.support.args, [
      path.join(path.dirname(process.execPath), "npm"),
      "run",
      "test:gate5-support",
    ]);
    assert.equal(byId.support.command, process.execPath);
    assert.deepEqual(byId.support.contract, {
      expected: 44,
      expectedSkips: [],
      skipped: 0,
    });

    assert.deepEqual(byId["real-smoke"].testFiles, [
      "tests/e2e/hermes-workbench.spec.ts",
    ]);
    assert.equal(byId["real-smoke"].grep, "@real-backend-smoke");
    assert.deepEqual(byId["real-smoke"].contract, {
      expected: 2,
      expectedSkips: [],
      skipped: 0,
    });

    for (const [fixture, counts] of Object.entries({
      normal: { expected: 30, skipped: 0 },
      degraded: { expected: 23, skipped: 2 },
      offline: { expected: 22, skipped: 3 },
      empty: { expected: 22, skipped: 3 },
      "long-content": { expected: 22, skipped: 3 },
    })) {
      const row = byId[`fixture-${fixture}`];
      assert.deepEqual(row.testFiles, fixtureFiles);
      assert.equal(row.grep, "@combined-fixture");
      assert.equal(row.contract.expected, counts.expected);
      assert.equal(row.contract.skipped, counts.skipped);
      assert.equal(row.contract.expectedSkips.length, counts.skipped);
      for (const skip of row.contract.expectedSkips) {
        assert.match(skip.id, /^hermes-workbench\.spec\.ts::.+::chromium$/);
        assert.equal(skip.reason.length > 0, true);
      }
    }

    assert.deepEqual(byId.lifecycle.testFiles, [
      "tests/e2e/hermes-lifecycle.spec.ts",
    ]);
    assert.equal(byId.lifecycle.grep, "@lifecycle-fixture");
    assert.deepEqual(byId.lifecycle.contract, {
      expected: 7,
      expectedSkips: [],
      skipped: 0,
    });

    assert.deepEqual(byId.rollback.testFiles, [
      "tests/e2e/hermes-rollback.spec.ts",
    ]);
    assert.equal(byId.rollback.grep, "@rollback");
    assert.deepEqual(byId.rollback.contract, {
      expected: 2,
      expectedSkips: [],
      skipped: 0,
    });

    for (const row of matrix.filter(
      (candidate) => candidate.kind === "playwright",
    )) {
      for (const testFile of row.testFiles) {
        assert.ok(row.args.includes(testFile), `${row.id}: ${testFile}`);
      }
      assert.ok(row.args.includes(`--grep=${row.grep}`), row.id);
    }
  });

  it("clears provider, reuse, live-session, and custom-backend pollution before setting exact row env", () => {
    const pollutedEnv = {
      AWS_SECRET_ACCESS_KEY: "secret",
      AZURE_OPENAI_API_KEY: "secret",
      DATABASE_URL: "postgresql://operator-db",
      HOME: "/operator/home",
      LLM_API_KEY: "secret",
      PATH: "/safe/bin",
      PLAYWRIGHT_BROWSERS_PATH: "/readonly/ms-playwright",
      PW_BACKEND_PORT: "8765",
      PW_E2E_RUN_ID: "polluted",
      PW_FRONTEND_PORT: "3001",
      PW_HERMES_LIFECYCLE_FIXTURE: "1",
      PW_HERMES_LIVE_SESSIONS: "1",
      PW_HERMES_ROLLBACK_E2E: "1",
      PW_HERMES_ROLLBACK_PORT: "3003",
      PW_HERMES_WORKBENCH_FIXTURE: "normal",
      PW_PYTHON: "/tmp/wrong-python",
      PW_REUSE_SERVER: "1",
      QUANT_API_COMMAND: "unsafe backend",
      QS_DATA_PROVIDER: "futu",
      QS_FUTU_ENABLED: "true",
      TMPDIR: "/operator/tmp",
      XDG_CACHE_HOME: "/operator/cache",
      FUTU_OPEND_HOST: "provider.example",
      LONGPORT_APP_KEY: "secret",
      OPENAI_API_KEY: "secret",
      PLAYWRIGHT_JSON_OUTPUT_FILE: "/tmp/wrong-report.json",
      TIINGO_API_KEY: "secret",
    };
    const matrix = buildGate5Matrix({
      backendPython: "/release/ai-quant/bin/python",
      baseEnv: pollutedEnv,
      outputDir: "/release-evidence/gate5",
      ports: Array.from({ length: 19 }, (_, index) => 45_000 + index),
      runToken: "clean-env",
    });

    for (const row of matrix) {
      assert.equal(
        row.env.PATH,
        `${path.dirname(process.execPath)}:/usr/bin:/bin`,
      );
      assert.equal(row.env.PW_E2E, "1");
      assert.equal(row.env.PW_BACKEND_PORT, String(row.backendPort));
      assert.equal(row.env.PW_FRONTEND_PORT, String(row.frontendPort));
      assert.equal(row.env.PW_E2E_RUN_ID, row.runId);
      assert.equal(row.env.PW_PYTHON, "/release/ai-quant/bin/python");
      assert.equal(row.env.PYTHONDONTWRITEBYTECODE, "1");
      assert.equal(row.env.PYTHONNOUSERSITE, "1");
      assert.equal(
        row.env.PYTHONPYCACHEPREFIX,
        path.join(
          FRONTEND_ROOT,
          ".tmp",
          "gate5-runtime",
          "clean-env",
          row.id,
          "pycache",
        ),
      );
      assert.equal(
        row.env.HOME,
        path.join(
          FRONTEND_ROOT,
          ".tmp",
          "gate5-runtime",
          "clean-env",
          row.id,
          "home",
        ),
      );
      assert.equal(
        row.env.TMPDIR,
        path.join(
          FRONTEND_ROOT,
          ".tmp",
          "gate5-runtime",
          "clean-env",
          row.id,
          "tmp",
        ),
      );
      assert.equal(
        row.env.XDG_CACHE_HOME,
        path.join(
          FRONTEND_ROOT,
          ".tmp",
          "gate5-runtime",
          "clean-env",
          row.id,
          "cache",
        ),
      );
      assert.equal(
        row.env.PLAYWRIGHT_BROWSERS_PATH,
        "/readonly/ms-playwright",
      );
      assert.equal(row.env.QS_AIHOT_ENABLED, "false");
      assert.equal(row.env.QS_BACKTEST_JOBS_ENABLED, "false");
      assert.equal(row.env.QS_DATABASE_AUTO_MIGRATE, "false");
      assert.equal(row.env.QS_DATABASE_ENABLED, "false");
      assert.equal(
        row.env.QS_DATA_DIR,
        path.join(row.runtimeRoot, "data"),
      );
      assert.equal(row.env.QS_DEFAULT_DATA_PROVIDER, "sample");
      assert.equal(row.env.QS_DRY_RUN, "true");
      assert.equal(row.env.QS_FUTU_ENABLED, "false");
      assert.equal(row.env.QS_FUTU_OPTIONS_ENABLED, "false");
      assert.equal(row.env.QS_HERMES_GATEWAY_ENABLED, "false");
      assert.equal(row.env.QS_HORIZON_ENABLED, "false");
      assert.equal(row.env.QS_KILL_SWITCH, "true");
      assert.equal(row.env.QS_LIVE_TRADING_ENABLED, "false");
      assert.equal(row.env.QS_LLM_PROVIDER, "stub");
      assert.equal(row.env.QS_LOCAL_MUTATION_ENABLED, "false");
      assert.equal(row.env.QS_OPTIONS_RADAR_ENABLED, "false");
      assert.equal(row.env.QS_OPTIONS_RADAR_PROVIDER, "sample");
      assert.equal(
        row.env.QS_OPTIONS_RADAR_STARTUP_CATCHUP_ENABLED,
        "false",
      );
      assert.equal(
        row.env.QS_PAPER_ACCOUNT_AUTO_PROCESS_PENDING_ORDERS_ENABLED,
        "false",
      );
      assert.equal(row.env.QS_PREDICTION_MARKET_PROVIDER, "sample");
      assert.equal(row.env.QS_ALPHA_VANTAGE_API_KEY, "");
      assert.equal(row.env.QS_FINNHUB_API_KEY, "");
      assert.equal(row.env.QS_LLM_API_KEY, "");
      for (const name of [
        "PW_HERMES_LIVE_SESSIONS",
        "PW_REUSE_SERVER",
        "QUANT_API_COMMAND",
        "AWS_SECRET_ACCESS_KEY",
        "AZURE_OPENAI_API_KEY",
        "DATABASE_URL",
        "LLM_API_KEY",
        "QS_DATA_PROVIDER",
        "FUTU_OPEND_HOST",
        "LONGPORT_APP_KEY",
        "OPENAI_API_KEY",
        "PLAYWRIGHT_JSON_OUTPUT_FILE",
        "TIINGO_API_KEY",
      ]) {
        assert.equal(row.env[name], undefined, `${row.id}: ${name}`);
      }
    }

    for (const fixture of [
      "normal",
      "degraded",
      "offline",
      "empty",
      "long-content",
    ]) {
      assert.equal(
        matrix.find((row) => row.id === `fixture-${fixture}`).env
          .PW_HERMES_WORKBENCH_FIXTURE,
        fixture,
      );
    }
    assert.equal(
      matrix.find((row) => row.id === "lifecycle").env
        .PW_HERMES_LIFECYCLE_FIXTURE,
      "1",
    );
    const rollback = matrix.find((row) => row.id === "rollback");
    assert.equal(rollback.env.PW_HERMES_WORKBENCH_FIXTURE, "normal");
    assert.equal(rollback.env.PW_HERMES_ROLLBACK_E2E, "1");
    assert.equal(rollback.env.PW_HERMES_ROLLBACK_PORT, String(rollback.rollbackPort));
  });

  it("rejects a Playwright report that discovered zero tests", () => {
    assert.throws(
      () =>
        validatePlaywrightReport(
          {
            contract: { expected: 2, expectedSkips: [], skipped: 0 },
            id: "real-smoke",
          },
          {
            errors: [],
            stats: {
              expected: 0,
              flaky: 0,
              skipped: 0,
              unexpected: 0,
            },
          },
        ),
      /real-smoke discovered zero tests/,
    );
  });

  it("rejects an unexpected skip even when the discovered total is unchanged", () => {
    assert.throws(
      () =>
        validatePlaywrightReport(
          {
            contract: { expected: 23, expectedSkips: [], skipped: 2 },
            id: "fixture-degraded",
          },
          {
            errors: [],
            stats: {
              expected: 22,
              flaky: 0,
              skipped: 3,
              unexpected: 0,
            },
          },
        ),
      /fixture-degraded skip contract mismatch: expected 2, got 3/,
    );
  });

  it("rejects duplicate Playwright object keys at every nesting level before disk", () => {
    assert.equal(
      JSON.parse("{\"stats\":1,\"stats\":2}").stats,
      2,
      "native JSON.parse silently accepts the unsafe duplicate-key input",
    );
    for (const rawJson of [
      "{\"stats\":1,\"stats\":2}",
      "{\"\\u0073tats\":1,\"stats\":2}",
      "{\"items\":[{\"status\":1,\"status\":2}]}",
    ]) {
      assert.throws(
        () => parsePlaywrightJson(rawJson, "duplicate-row"),
        new Error(
          "duplicate-row Playwright JSON contains a duplicate object key",
        ),
      );
    }
    assert.deepEqual(
      parsePlaywrightJson(
        "{\"left\":{\"status\":1},\"right\":{\"status\":2}}",
        "distinct-row",
      ),
      {
        left: { status: 1 },
        right: { status: 2 },
      },
    );
    assert.throws(
      () => parsePlaywrightJson("not-json", "invalid-row"),
      new Error("invalid-row produced invalid Playwright JSON"),
    );
  });

  it("accepts only the exact pass contract with zero unexpected and flaky outcomes", () => {
    const row = {
      contract: { expected: 2, expectedSkips: [], skipped: 0 },
      id: "real-smoke",
    };
    const report = (overrides = {}) =>
      playwrightReport({ expected: 2, stats: overrides });

    assert.doesNotThrow(() => validatePlaywrightReport(row, report()));
    assert.throws(
      () => validatePlaywrightReport(row, report({ expected: 1 })),
      /real-smoke pass contract mismatch: expected 2, got 1/,
    );
    assert.throws(
      () => validatePlaywrightReport(row, report({ unexpected: 1 })),
      /real-smoke has 1 unexpected test outcomes/,
    );
    assert.throws(
      () => validatePlaywrightReport(row, report({ flaky: 1 })),
      /real-smoke has 1 flaky test outcomes/,
    );
  });

  it("rejects equal-count skip substitution by exact id and reason", () => {
    const row = {
      contract: {
        expected: 1,
        expectedSkips: [
          {
            id: "hermes-workbench.spec.ts::expected skipped test::chromium",
            reason: "Repository-authorized reason.",
          },
        ],
        skipped: 1,
      },
      id: "fixture-substitution",
    };
    const report = playwrightReport({
      expected: 1,
      skipped: [
        {
          file: "hermes-workbench.spec.ts",
          reason: "Unrelated new reason.",
          title: "unrelated newly skipped test",
        },
      ],
    });

    assert.throws(
      () => validatePlaywrightReport(row, report),
      /fixture-substitution exact skip identity\/reason mismatch/,
    );
  });

  it("rejects every snapshot-update CLI spelling before the matrix starts", () => {
    const expectedCommit = "a".repeat(40);
    const safeArgs = [
      "--output-dir",
      "/release-evidence/gate5",
      "--backend-python=/release/ai-quant/bin/python",
      "--gate2-receipt=/release-evidence/gate2/backend-non-postgres-receipt.json",
      "--frontend-install-receipt=/release-evidence/frontend-install/frontend-fresh-install-receipt.json",
      `--expected-commit=${expectedCommit}`,
    ];
    assert.deepEqual(assertSafeCliArgs(safeArgs), {
      backendPython: "/release/ai-quant/bin/python",
      expectedCommit,
      gate2Receipt:
        "/release-evidence/gate2/backend-non-postgres-receipt.json",
      frontendInstallReceipt:
        "/release-evidence/frontend-install/frontend-fresh-install-receipt.json",
      outputDir: "/release-evidence/gate5",
    });
    for (const updateArg of [
      "--update-snapshots",
      "--update-snapshots=all",
      "-u",
    ]) {
      assert.throws(
        () => assertSafeCliArgs([...safeArgs, updateArg]),
        /Gate 5 forbids snapshot updates/,
      );
    }
    assert.throws(
      () => assertSafeCliArgs([...safeArgs, "--workers=8"]),
      /Gate 5 does not accept --workers=8/,
    );
    assert.throws(
      () =>
        assertSafeCliArgs([
          "--output-dir=/release-evidence/gate5",
          "--backend-python=/release/ai-quant/bin/python",
          "--gate2-receipt=/release-evidence/gate2/backend-non-postgres-receipt.json",
          "--frontend-install-receipt=/release-evidence/frontend-install/frontend-fresh-install-receipt.json",
        ]),
      /Gate 5 requires --expected-commit/,
    );
    assert.throws(
      () =>
        assertSafeCliArgs([
          "--output-dir=/release-evidence/gate5",
          "--backend-python=/release/ai-quant/bin/python",
          "--gate2-receipt=/release-evidence/gate2/backend-non-postgres-receipt.json",
          "--frontend-install-receipt=/release-evidence/frontend-install/frontend-fresh-install-receipt.json",
          "--expected-commit=not-a-commit",
        ]),
      /Gate 5 --expected-commit must be a lowercase 40-hex commit/,
    );
    assert.throws(
      () =>
        assertSafeCliArgs([
          "--output-dir=/release-evidence/gate5",
          "--backend-python=/release/ai-quant/bin/python",
          `--expected-commit=${expectedCommit}`,
        ]),
      /Gate 5 requires --gate2-receipt/,
    );

    const temporaryBase = path.join(FRONTEND_ROOT, ".tmp");
    fs.mkdirSync(temporaryBase, { mode: 0o700, recursive: true });
    const temporaryRoot = fs.mkdtempSync(
      path.join(temporaryBase, "gate5-preflight-summary-"),
    );
    fs.chmodSync(temporaryRoot, 0o700);
    const outputDir = path.join(temporaryRoot, "evidence");
    fs.mkdirSync(outputDir, { mode: 0o700 });
    try {
      const result = spawnSync(
        process.execPath,
        [
          path.join(
            FRONTEND_ROOT,
            "scripts",
            "run-hermes-gate5.mjs",
          ),
          "--output-dir",
          outputDir,
          "--backend-python",
          path.join(temporaryRoot, "missing-python"),
          "--gate2-receipt",
          path.join(temporaryRoot, "missing-gate2-receipt.json"),
          "--frontend-install-receipt",
          path.join(
            temporaryRoot,
            "missing-frontend-install-receipt.json",
          ),
          "--expected-commit",
          expectedCommit,
        ],
        {
          cwd: FRONTEND_ROOT,
          encoding: "utf8",
          env: {
            LANG: "C",
            LC_ALL: "C",
            PATH: "/usr/bin:/bin",
          },
          timeout: 30_000,
        },
      );
      assert.equal(result.status, 1);
      assert.match(result.stderr, /Gate 5 backend Python is missing/);
      const summaryPath = path.join(
        outputDir,
        "gate5-summary.json",
      );
      const summaryText = fs.readFileSync(summaryPath, "utf8");
      assert.equal(
        summaryText,
        canonicalJson(JSON.parse(summaryText)),
      );
      const summary = JSON.parse(summaryText);
      assert.equal(summary.phase, "preflight");
      assert.equal(summary.status, "failed");
    } finally {
      fs.rmSync(temporaryRoot, { force: true, recursive: true });
    }
  });

  it("binds the exact Gate 2 fresh noneditable Python identity", () => {
    const expectedCommit = "b".repeat(40);
    const repoRoot = "/release/ai-quant-platform";
    const runtimeRoot = path.join(
      repoRoot,
      ".tmp",
      `backend-non-postgres-${expectedCommit.slice(0, 12)}-0123456789abcdef`,
    );
    const venv = path.join(runtimeRoot, "venv");
    const backendPython = path.join(venv, "bin", "python");
    const sitePackages = path.join(
      venv,
      "lib",
      "python3.11",
      "site-packages",
    );
    const document = {
      base_prefix: "/opt/python/3.11",
      dependency_inventory: [
        "pytest==8.4.2",
        "quant-system==0.1.0",
      ],
      direct_url: {
        dir_info: { editable: false },
        url: "file:///release/ai-quant-platform",
      },
      distribution_version: "0.1.0",
      prefix: venv,
      pth_files: [],
      quant_system_file: path.join(
        sitePackages,
        "quant_system",
        "__init__.py",
      ),
      site_packages: [sitePackages],
      sys_executable: backendPython,
      sys_executable_realpath: "/opt/python/3.11/bin/python3.11",
      sys_path: [sitePackages],
      version: "3.11.15",
      version_info: [3, 11, 15],
    };

    const validated = validateBackendPythonIdentity({
      backendPython,
      document,
      expectedCommit,
      repoRoot,
    });
    assert.deepEqual(validated, document);

    assert.throws(
      () =>
        validateBackendPythonIdentity({
          backendPython,
          document: {
            ...document,
            direct_url: {
              dir_info: { editable: true },
              url: "file:///release/ai-quant-platform",
            },
          },
          expectedCommit,
          repoRoot,
        }),
      /Gate 5 backend distribution is not an exact noneditable checkout install/,
    );
    assert.throws(
      () =>
        validateBackendPythonIdentity({
          backendPython: path.join(
            repoRoot,
            ".venv",
            "bin",
            "python",
          ),
          document,
          expectedCommit,
          repoRoot,
        }),
      /Gate 5 backend Python is not the exact Gate 2 fresh environment/,
    );
  });

  it("audits a real clean Git identity and rejects hidden, dirty, or push-url drift", () => {
    const temporaryBase = path.join(FRONTEND_ROOT, ".tmp");
    fs.mkdirSync(temporaryBase, { mode: 0o700, recursive: true });
    const repository = fs.mkdtempSync(
      path.join(temporaryBase, "gate5-git-authority-"),
    );
    fs.chmodSync(repository, 0o700);
    try {
      runGit(repository, "init");
      runGit(
        repository,
        "checkout",
        "-b",
        "codex/agent-v0-2-release",
      );
      runGit(repository, "config", "user.name", "Gate 5 Test");
      runGit(
        repository,
        "config",
        "user.email",
        "gate5-test@example.invalid",
      );
      fs.writeFileSync(
        path.join(repository, "tracked.txt"),
        "exact\n",
        { encoding: "utf8", mode: 0o600 },
      );
      fs.writeFileSync(
        path.join(repository, ".gitignore"),
        ".env\n",
        { encoding: "utf8", mode: 0o600 },
      );
      runGit(repository, "add", "--", ".gitignore", "tracked.txt");
      runGit(repository, "commit", "-m", "test: bind identity");
      runGit(
        repository,
        "remote",
        "add",
        "github",
        "https://github.com/YIBOWAY/ai-quant-platform.git",
      );
      const expectedCommit = runGit(
        repository,
        "rev-parse",
        "--verify",
        "HEAD",
      );

      const authority = collectRepositoryAuthority(
        repository,
        expectedCommit,
      );
      assert.equal(authority.commit, expectedCommit);
      assert.deepEqual(authority.publication_fetch_urls, [
        "https://github.com/YIBOWAY/ai-quant-platform.git",
      ]);
      assert.deepEqual(authority.publication_push_urls, [
        "https://github.com/YIBOWAY/ai-quant-platform.git",
      ]);

      runGit(
        repository,
        "update-index",
        "--assume-unchanged",
        "tracked.txt",
      );
      assert.throws(
        () => collectRepositoryAuthority(repository, expectedCommit),
        /Gate 5 release checkout has hidden index flags/,
      );
      runGit(
        repository,
        "update-index",
        "--no-assume-unchanged",
        "tracked.txt",
      );

      runGit(
        repository,
        "config",
        "--add",
        "remote.github.pushurl",
        "https://example.invalid/wrong.git",
      );
      assert.throws(
        () => collectRepositoryAuthority(repository, expectedCommit),
        /Gate 5 publication push URL mismatch/,
      );
      runGit(
        repository,
        "config",
        "--unset-all",
        "remote.github.pushurl",
      );

      runGit(
        repository,
        "remote",
        "set-url",
        "github",
        "https://example.invalid/wrong-fetch.git",
      );
      assert.throws(
        () => collectRepositoryAuthority(repository, expectedCommit),
        /Gate 5 publication remote mismatch/,
      );
      runGit(
        repository,
        "remote",
        "set-url",
        "github",
        "https://github.com/YIBOWAY/ai-quant-platform.git",
      );

      runGit(repository, "checkout", "-b", "wrong-branch");
      assert.throws(
        () => collectRepositoryAuthority(repository, expectedCommit),
        /Gate 5 release checkout branch mismatch/,
      );
      runGit(
        repository,
        "checkout",
        "codex/agent-v0-2-release",
      );

      const ignoredEnvironment = path.join(repository, ".env");
      fs.writeFileSync(
        ignoredEnvironment,
        "QS_LIVE_TRADING_ENABLED=true\n",
        { encoding: "utf8", mode: 0o600 },
      );
      assert.throws(
        () => collectRepositoryAuthority(repository, expectedCommit),
        /Gate 5 release checkout has ignored runtime configuration/,
      );
      fs.rmSync(ignoredEnvironment);
      fs.symlinkSync(
        path.join(repository, "missing-environment"),
        ignoredEnvironment,
      );
      assert.throws(
        () => collectRepositoryAuthority(repository, expectedCommit),
        /Gate 5 release checkout has ignored runtime configuration/,
      );
      fs.unlinkSync(ignoredEnvironment);
      const frontendDirectory = path.join(
        repository,
        "src",
        "frontend",
      );
      fs.mkdirSync(frontendDirectory, { recursive: true });
      const ignoredFrontendEnvironment = path.join(
        frontendDirectory,
        ".env.local",
      );
      fs.writeFileSync(
        ignoredFrontendEnvironment,
        "NEXT_PUBLIC_RELEASE_MODE=unsafe\n",
        { encoding: "utf8", mode: 0o600 },
      );
      assert.throws(
        () => collectRepositoryAuthority(repository, expectedCommit),
        /src\/frontend\/\.env\.local/,
      );
      fs.rmSync(ignoredFrontendEnvironment);
      fs.symlinkSync(
        path.join(frontendDirectory, "missing-environment"),
        ignoredFrontendEnvironment,
      );
      assert.throws(
        () => collectRepositoryAuthority(repository, expectedCommit),
        /src\/frontend\/\.env\.local/,
      );
      fs.unlinkSync(ignoredFrontendEnvironment);
      fs.rmSync(path.join(repository, "src"), {
        recursive: true,
      });

      fs.appendFileSync(
        path.join(repository, "tracked.txt"),
        "dirty\n",
        "utf8",
      );
      assert.throws(
        () => collectRepositoryAuthority(repository, expectedCommit),
        /Gate 5 release checkout is not clean/,
      );
    } finally {
      fs.rmSync(repository, { force: true, recursive: true });
    }
  });

  it("binds the complete backend environment including dependency and interpreter bytes", () => {
    const temporaryBase = path.join(FRONTEND_ROOT, ".tmp");
    fs.mkdirSync(temporaryBase, { mode: 0o700, recursive: true });
    const environment = fs.mkdtempSync(
      path.join(temporaryBase, "gate5-backend-environment-"),
    );
    fs.chmodSync(environment, 0o700);
    try {
      const dependency = path.join(
        environment,
        "lib",
        "python3.11",
        "site-packages",
        "uvicorn",
      );
      fs.mkdirSync(dependency, { mode: 0o700, recursive: true });
      for (const directory of [
        path.join(environment, "lib"),
        path.join(environment, "lib", "python3.11"),
        path.join(environment, "lib", "python3.11", "site-packages"),
        dependency,
      ]) {
        fs.chmodSync(directory, 0o700);
      }
      const dependencyEntrypoint = path.join(
        dependency,
        "__main__.py",
      );
      fs.writeFileSync(dependencyEntrypoint, "print('trusted')\n", {
        encoding: "utf8",
        mode: 0o600,
      });
      const interpreter = path.join(environment, "interpreter");
      fs.writeFileSync(interpreter, "python-runtime\n", {
        encoding: "utf8",
        mode: 0o500,
      });
      const bin = path.join(environment, "bin");
      fs.mkdirSync(bin, { mode: 0o700 });
      fs.symlinkSync(interpreter, path.join(bin, "python"));

      const first = installedEnvironmentTreeIdentity(environment);
      const repoRoot = path.resolve(FRONTEND_ROOT, "..", "..");
      const python = path.join(
        repoRoot,
        ".venv",
        "bin",
        "python",
      );
      const crossLanguage = spawnSync(
        python,
        [
          "-I",
          "-B",
          "-c",
          [
            "import importlib.util,json,pathlib,sys",
            "spec=importlib.util.spec_from_file_location('gate2_tree', pathlib.Path(sys.argv[1]))",
            "module=importlib.util.module_from_spec(spec)",
            "spec.loader.exec_module(module)",
            "print(json.dumps(module.installed_environment_tree_identity(sys.argv[2]), allow_nan=False, ensure_ascii=False, separators=(',', ':'), sort_keys=True))",
          ].join(";"),
          path.join(
            repoRoot,
            "scripts",
            "backend_non_postgres_gate.py",
          ),
          environment,
        ],
        {
          cwd: repoRoot,
          encoding: "utf8",
          env: {
            LANG: "C",
            LC_ALL: "C",
            PATH: "/usr/bin:/bin",
          },
        },
      );
      assert.equal(
        crossLanguage.status,
        0,
        crossLanguage.stderr,
      );
      assert.deepEqual(JSON.parse(crossLanguage.stdout), first);
      fs.writeFileSync(
        dependencyEntrypoint,
        "print('forged')\n",
        "utf8",
      );
      const dependencyTamper =
        installedEnvironmentTreeIdentity(environment);
      assert.notEqual(
        dependencyTamper.tree_sha256,
        first.tree_sha256,
      );

      fs.writeFileSync(
        dependencyEntrypoint,
        "print('trusted')\n",
        "utf8",
      );
      fs.chmodSync(interpreter, 0o700);
      fs.writeFileSync(interpreter, "changed-runtime\n", "utf8");
      fs.chmodSync(interpreter, 0o500);
      const interpreterTamper =
        installedEnvironmentTreeIdentity(environment);
      assert.notEqual(
        interpreterTamper.tree_sha256,
        first.tree_sha256,
      );
    } finally {
      fs.rmSync(environment, { force: true, recursive: true });
    }
  });

  it("binds fresh npm ci, exact toolchain bytes, and the complete frontend dependency tree", () => {
    const expectedCommit = "f".repeat(40);
    const npmCli = path.join(
      path.dirname(process.execPath),
      "npm",
    );
    assert.deepEqual(
      parseFrontendInstallArgs([
        "--expected-commit",
        expectedCommit,
        "--npm-cli",
        npmCli,
        "--output-dir",
        "/release-evidence/frontend-install",
      ]),
      {
        expectedCommit,
        npmCli,
        outputDir: "/release-evidence/frontend-install",
      },
    );
    assert.throws(
      () =>
        parseFrontendInstallArgs([
          "--expected-commit",
          expectedCommit,
          "--npm-cli",
          npmCli,
        ]),
      /requires --output-dir/,
    );

    const temporaryParent = fs.mkdtempSync(
      path.join(
        fs.realpathSync(os.tmpdir()),
        "gate5-frontend-install-",
      ),
    );
    fs.chmodSync(temporaryParent, 0o700);
    const receiptDir = path.join(temporaryParent, "evidence");
    fs.mkdirSync(receiptDir, { mode: 0o700 });
    fs.chmodSync(receiptDir, 0o700);
    try {
      const frontendRoot = FRONTEND_ROOT;
      const repoRoot = path.resolve(frontendRoot, "..", "..");
      const currentNode = {
        ...runtimeExecutableIdentity(process.execPath),
        version: process.version,
        versions: process.versions,
      };
      const currentNpm = runtimeExecutableIdentity(npmCli);
      const pathBin = path.dirname(currentNode.realpath);
      const pathCommands = Object.fromEntries(
        ["node", "npm", "npx"].map((name) => [
          name,
          runtimeExecutableIdentity(path.join(pathBin, name)),
        ]),
      );
      const currentInstalledTree = {
        entry_count: 1234,
        root: path.join(frontendRoot, "node_modules"),
        tree_sha256: "7".repeat(64),
      };
      const repository = {
        branch: "codex/agent-v0-2-release",
        clean: true,
        commit: expectedCommit,
        root: repoRoot,
        tree: "6".repeat(40),
      };
      const transientRoot = path.join(
        receiptDir,
        ".frontend-install-runtime",
      );
      const empty = (name) => writeArtifact(receiptDir, name, "");
      const versionStdout = writeArtifact(
        receiptDir,
        "npm-version.stdout.log",
        "10.9.8\n",
      );
      const npmVersion = {
        argv: [
          currentNode.realpath,
          currentNpm.realpath,
          "--version",
        ],
        completed_at: "2026-07-29T00:00:01Z",
        exit_code: 0,
        signal: null,
        started_at: "2026-07-29T00:00:00Z",
        stderr: empty("npm-version.stderr.log"),
        stdout: versionStdout,
      };
      const install = {
        argv: [
          currentNode.realpath,
          currentNpm.realpath,
          "ci",
          "--no-audit",
          "--no-fund",
        ],
        completed_at: "2026-07-29T00:00:03Z",
        exit_code: 0,
        signal: null,
        started_at: "2026-07-29T00:00:01Z",
        stderr: empty("npm-ci.stderr.log"),
        stdout: empty("npm-ci.stdout.log"),
      };
      const receipt = {
        command: {
          argv: [
            process.execPath,
            path.join(
              frontendRoot,
              "scripts",
              "prepare-hermes-gate5-install.mjs",
            ),
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
        },
        completed_at: "2026-07-29T00:00:04Z",
        contract: "platform-frontend-fresh-install/v1",
        environment: frontendInstallEnvironment(
          currentNode,
          transientRoot,
        ),
        evidence_directory: {
          mode: "700",
          owner_uid: fs.lstatSync(receiptDir).uid,
          parent_mode: "700",
          parent_owner_uid: fs.lstatSync(temporaryParent).uid,
          path: receiptDir,
        },
        inputs_after: frontendInputIdentity(frontendRoot),
        inputs_before: frontendInputIdentity(frontendRoot),
        install,
        installed_tree_after: currentInstalledTree,
        node: currentNode,
        node_modules_before: {
          exists: true,
          mode: (fs.lstatSync(
            path.join(frontendRoot, "node_modules"),
          ).mode & 0o777)
            .toString(8)
            .padStart(3, "0"),
          owner_uid: process.getuid(),
          path: path.join(frontendRoot, "node_modules"),
        },
        npm: {
          ...currentNpm,
          version: npmVersion,
        },
        path_commands: pathCommands,
        repository_after: repository,
        repository_before: repository,
        started_at: "2026-07-29T00:00:00Z",
        status: "passed",
        transient_runtime: {
          cleanup_status: "removed",
          root: transientRoot,
        },
      };
      const receiptPath = path.join(
        receiptDir,
        "frontend-fresh-install-receipt.json",
      );
      fs.writeFileSync(receiptPath, canonicalJson(receipt), {
        encoding: "utf8",
        mode: 0o600,
      });

      const authority = loadFrontendInstallAuthority({
        currentInstalledTree,
        expectedCommit,
        frontendInstallReceipt: receiptPath,
        frontendRoot,
        repository,
      });
      assert.equal(authority.schema_version,
        "hermes-gate5-frontend-authority.v1");
      assert.equal(authority.receipt_sha256.length, 64);

      assert.throws(
        () =>
          loadFrontendInstallAuthority({
            currentInstalledTree: {
              ...currentInstalledTree,
              tree_sha256: "0".repeat(64),
            },
            expectedCommit,
            frontendInstallReceipt: receiptPath,
            frontendRoot,
            repository,
          }),
        /current frontend dependency bytes differ from npm ci/,
      );

      fs.appendFileSync(
        path.join(receiptDir, versionStdout.path),
        "tampered\n",
        "utf8",
      );
      assert.throws(
        () =>
          loadFrontendInstallAuthority({
            currentInstalledTree,
            expectedCommit,
            frontendInstallReceipt: receiptPath,
            frontendRoot,
            repository,
          }),
        /frontend install artifact digest mismatch/,
      );
    } finally {
      fs.rmSync(temporaryParent, {
        force: true,
        recursive: true,
      });
    }
  });

  it("enters the real frontend install command and removes its private runtime", () => {
    const temporaryParent = fs.mkdtempSync(
      path.join(
        fs.realpathSync(os.tmpdir()),
        "gate5-frontend-install-flow-",
      ),
    );
    fs.chmodSync(temporaryParent, 0o700);
    const outputDir = path.join(temporaryParent, "evidence");
    fs.mkdirSync(outputDir, { mode: 0o700 });
    fs.chmodSync(outputDir, 0o700);
    const fakeNpm = path.join(temporaryParent, "npm-cli.mjs");
    fs.writeFileSync(
      fakeNpm,
      [
        "const args = process.argv.slice(2);",
        "if (args.length === 1 && args[0] === '--version') {",
        "  process.stdout.write('10.9.8\\n');",
        "} else if (JSON.stringify(args) !== JSON.stringify(['ci', '--no-audit', '--no-fund'])) {",
        "  process.exitCode = 7;",
        "}",
      ].join("\n"),
      { encoding: "utf8", mode: 0o700 },
    );
    const expectedCommit = "a".repeat(40);
    const sourceInputs = {
      "package-lock.json": {
        sha256: "b".repeat(64),
        size_bytes: 1,
      },
    };
    const repository = {
      branch: "codex/agent-v0-2-release",
      clean: true,
      commit: expectedCommit,
      tree: "c".repeat(40),
    };
    const installedTree = {
      entry_count: 1,
      root: path.join(FRONTEND_ROOT, "node_modules"),
      tree_sha256: "d".repeat(64),
    };
    try {
      const result = runFrontendFreshInstall(
        {
          expectedCommit,
          npmCli: fakeNpm,
          outputDir,
        },
        {
          collectInputs: () => sourceInputs,
          collectInstalledTree: () => installedTree,
          collectRepository: () => repository,
        },
      );
      assert.equal(result.status, "passed");
      const receipt = JSON.parse(
        fs.readFileSync(result.receipt, "utf8"),
      );
      assert.equal(receipt.status, "passed");
      assert.deepEqual(receipt.install.argv, [
        fs.realpathSync(process.execPath),
        fs.realpathSync(fakeNpm),
        "ci",
        "--no-audit",
        "--no-fund",
      ]);
      assert.equal(receipt.install.exit_code, 0);
      assert.equal(
        receipt.transient_runtime.cleanup_status,
        "removed",
      );
      assert.equal(
        fs.existsSync(receipt.transient_runtime.root),
        false,
      );
      assert.deepEqual(receipt.installed_tree_after, installedTree);
    } finally {
      fs.rmSync(temporaryParent, {
        force: true,
        recursive: true,
      });
    }
  });

  it("binds a canonical passing Gate 2 receipt and detects artifact tampering", () => {
    const expectedCommit = "d".repeat(40);
    const repoRoot = "/release/ai-quant-platform";
    const tree = "e".repeat(40);
    const temporaryBase = path.join(FRONTEND_ROOT, ".tmp");
    fs.mkdirSync(temporaryBase, { mode: 0o700, recursive: true });
    const receiptParent = fs.mkdtempSync(
      path.join(temporaryBase, "gate5-gate2-parent-"),
    );
    fs.chmodSync(receiptParent, 0o700);
    const receiptDir = path.join(receiptParent, "output");
    fs.mkdirSync(receiptDir, { mode: 0o700 });
    fs.chmodSync(receiptDir, 0o700);
    const runtimeDigest = crypto
      .createHash("sha256")
      .update(`${expectedCommit}\0${receiptDir}`, "utf8")
      .digest("hex")
      .slice(0, 16);
    const runtimeRoot = path.join(
      repoRoot,
      ".tmp",
      `backend-non-postgres-${expectedCommit.slice(0, 12)}-${runtimeDigest}`,
    );
    const venv = path.join(runtimeRoot, "venv");
    const backendPython = path.join(venv, "bin", "python");
    const sitePackages = path.join(
      venv,
      "lib",
      "python3.11",
      "site-packages",
    );
    const currentIdentity = {
      base_prefix: "/opt/python/3.11",
      dependency_inventory: [
        "pytest==8.4.2",
        "quant-system==0.1.0",
      ],
      direct_url: {
        dir_info: { editable: false },
        url: "file:///release/ai-quant-platform",
      },
      distribution_version: "0.1.0",
      prefix: venv,
      pth_files: [],
      quant_system_file: path.join(
        sitePackages,
        "quant_system",
        "__init__.py",
      ),
      site_packages: [sitePackages],
      sys_executable: backendPython,
      sys_executable_realpath: "/opt/python/3.11/bin/python3.11",
      sys_path: [sitePackages],
      version: "3.11.15",
      version_info: [3, 11, 15],
    };
    const currentInstalledTree = {
      file_count: 42,
      root: path.join(sitePackages, "quant_system"),
      tree_sha256: "9".repeat(64),
    };
    const currentEnvironmentTree = {
      entry_count: 142,
      root: venv,
      tree_sha256: "8".repeat(64),
    };
    const repository = {
      branch: "codex/agent-v0-2-release",
      clean: true,
      clean_status_sha256: crypto
        .createHash("sha256")
        .update("")
        .digest("hex"),
      commit: expectedCommit,
      git_toplevel: repoRoot,
      publication_fetch_urls: [
        "https://github.com/YIBOWAY/ai-quant-platform.git",
      ],
      publication_push_urls: [
        "https://github.com/YIBOWAY/ai-quant-platform.git",
      ],
      publication_remote: "github",
      publication_remote_url:
        "https://github.com/YIBOWAY/ai-quant-platform.git",
      replace_ref_count: 0,
      root: repoRoot,
      tracked_tree: {
        assume_unchanged_count: 0,
        conflict_entry_count: 0,
        index_matches_head: true,
        ls_files_flags_sha256: "f".repeat(64),
        skip_worktree_count: 0,
        tracked_path_count: 100,
        worktree_matches_index: true,
      },
      tree,
    };
    const inputContents = {
      "pyproject.toml": "[project]\nname='quant-system'\n",
      "scripts/backend_non_postgres_gate.py": "runner\n",
      "scripts/verify_backend_non_postgres.sh": "wrapper\n",
      "uv.lock": "version = 1\n",
    };
    const currentInputs = Object.fromEntries(
      Object.entries(inputContents).map(([name, contents]) => [
        name,
        {
          sha256: crypto
            .createHash("sha256")
            .update(contents, "utf8")
            .digest("hex"),
          size_bytes: Buffer.byteLength(contents, "utf8"),
        },
      ]),
    );
    const inventoryArtifact = writeArtifact(
      receiptDir,
      "dependency-inventory.stdout.log",
      `quant-system @ file://${repoRoot}\n`,
    );
    try {
      const emptyArtifact = (name) =>
        writeArtifact(receiptDir, name, "");
      const uvPath = path.join(receiptDir, "uv");
      const uvContents = "#!/bin/sh\nexit 0\n";
      fs.writeFileSync(uvPath, uvContents, {
        encoding: "utf8",
        mode: 0o700,
      });
      const receiptRepository = {
        branch: repository.branch,
        clean: true,
        clean_status_sha256: repository.clean_status_sha256,
        commit: expectedCommit,
        git_toplevel: repoRoot,
        publication_remote: "github",
        publication_remote_url:
          "https://github.com/YIBOWAY/ai-quant-platform.git",
        root: repoRoot,
        tracked_tree: repository.tracked_tree,
        tree,
      };
      const gate2Entrypoint =
        "scripts/verify_backend_non_postgres.sh";
      const markerExpression =
        "not pg and not futu_opend and not provider and not network";
      const outerProfile =
        "(version 1) (allow default) (deny network*)";
      const transientPaths = {
        basetemp: path.join(runtimeRoot, "basetemp"),
        home: path.join(runtimeRoot, "home"),
        pycache: path.join(runtimeRoot, "pycache"),
        sandbox_agent_data: path.join(
          runtimeRoot,
          "sandbox-agent-data",
        ),
        sandbox_data: path.join(runtimeRoot, "sandbox-data"),
        tmp: path.join(runtimeRoot, "tmp"),
        uv_cache: path.join(runtimeRoot, "uv-cache"),
        venv,
      };
      const nodeRealpath = fs.realpathSync(process.execPath);
      const nodeVersionBytes = `${process.version}\n`;
      const nodeVersionStdout = writeArtifact(
        receiptDir,
        "node-version.stdout.log",
        nodeVersionBytes,
      );
      const nodeVersionStderr = emptyArtifact(
        "node-version.stderr.log",
      );
      const networkStdout = emptyArtifact(
        "network-sandbox-denial.stdout.log",
      );
      const networkStderr = emptyArtifact(
        "network-sandbox-denial.stderr.log",
      );
      const generalNode = "tests/test_general.py::test_general";
      const innerNode = "tests/test_inner.py::test_inner";
      const collectedNodes = [generalNode, innerNode];
      const generalNodes = [generalNode];
      const innerNodes = [innerNode];
      const collectionStdout = writeArtifact(
        receiptDir,
        "pytest-backend-non-postgres-collection.stdout.log",
        `GATE2_COLLECTION_NODE_IDS=${canonicalJson(
          collectedNodes,
        )}\n`,
      );
      const collectionStderr = emptyArtifact(
        "pytest-backend-non-postgres-collection.stderr.log",
      );
      const generalStdout = emptyArtifact(
        "pytest-backend-non-postgres.stdout.log",
      );
      const generalStderr = emptyArtifact(
        "pytest-backend-non-postgres.stderr.log",
      );
      const innerStdout = emptyArtifact(
        "pytest-backend-non-postgres-inner-sandbox.stdout.log",
      );
      const innerStderr = emptyArtifact(
        "pytest-backend-non-postgres-inner-sandbox.stderr.log",
      );
      const generalJunit = writeArtifact(
        receiptDir,
        "pytest-backend-non-postgres.junit.xml",
        '<testsuite tests="1" failures="0" errors="0" skipped="0"><testcase classname="tests.test_general" name="test_general"/></testsuite>',
      );
      const innerJunit = writeArtifact(
        receiptDir,
        "pytest-backend-non-postgres-inner-sandbox.junit.xml",
        '<testsuite tests="1" failures="0" errors="0" skipped="0"><testcase classname="tests.test_inner" name="test_inner"/></testsuite>',
      );
      const onePass = {
        failed: 0,
        passed: 1,
        skip_node_ids: [],
        skipped: 0,
        total: 1,
      };
      const twoPass = {
        failed: 0,
        passed: 2,
        skip_node_ids: [],
        skipped: 0,
        total: 2,
      };
      const collectionArgv = [
        "/usr/bin/sandbox-exec",
        "-p",
        outerProfile,
        backendPython,
        "-I",
        "-B",
        "-c",
        "<collection-source>",
        "--collect-only",
        "-q",
        "--strict-config",
        "--strict-markers",
        "-p",
        "no:cacheprovider",
        "--basetemp",
        path.join(transientPaths.basetemp, "collection"),
        "-m",
        markerExpression,
        "tests",
      ];
      const generalArgv = [
        "/usr/bin/sandbox-exec",
        "-p",
        outerProfile,
        backendPython,
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
        markerExpression,
        "--basetemp",
        path.join(transientPaths.basetemp, "general"),
        `--deselect=${innerNode}`,
        "tests",
        `--junitxml=${path.join(
          receiptDir,
          "pytest-backend-non-postgres.junit.xml",
        )}`,
      ];
      const innerArgv = [
        backendPython,
        "-I",
        "-B",
        "-c",
        "<inner-source>",
        "-q",
        "-rA",
        "--strict-config",
        "--strict-markers",
        "-p",
        "no:cacheprovider",
        "-m",
        markerExpression,
        "--basetemp",
        path.join(transientPaths.basetemp, "inner-sandbox"),
        innerNode,
        `--junitxml=${path.join(
          receiptDir,
          "pytest-backend-non-postgres-inner-sandbox.junit.xml",
        )}`,
      ];
      const receipt = {
        command: {
          argv: [
            gate2Entrypoint,
            "--output-dir",
            receiptDir,
            "--expected-commit",
            expectedCommit,
          ],
          cwd: repoRoot,
          entrypoint_binding: {
            argument: gate2Entrypoint,
            expected_path: path.join(
              repoRoot,
              "scripts",
              "verify_backend_non_postgres.sh",
            ),
            resolved_path: path.join(
              repoRoot,
              "scripts",
              "verify_backend_non_postgres.sh",
            ),
          },
          environment_strategy: "allowlist",
          may_touch_database: false,
          may_touch_network_during_install: true,
          may_touch_network_during_tests: false,
          may_touch_provider: false,
          may_touch_runtime: false,
          may_touch_trading: false,
        },
        completed_at: "2026-07-29T00:01:00Z",
        contract: "quant-system-backend-non-postgres/v1",
        environment: {
          install: {
            HOME: transientPaths.home,
            LANG: "C",
            LC_ALL: "C",
            PATH: `${path.dirname(uvPath)}:/usr/bin:/bin`,
            TMPDIR: transientPaths.tmp,
            UV_CACHE_DIR: transientPaths.uv_cache,
            UV_LINK_MODE: "copy",
            UV_NO_CONFIG: "1",
            UV_PROJECT_ENVIRONMENT: venv,
            UV_PYTHON_DOWNLOADS: "never",
          },
          tests: {
            HOME: transientPaths.home,
            LANG: "C",
            LC_ALL: "C",
            PATH: [
              path.dirname(nodeRealpath),
              path.join(venv, "bin"),
              path.dirname(uvPath),
              "/usr/bin",
              "/bin",
            ].join(":"),
            PYTHONNOUSERSITE: "1",
            PYTHONPYCACHEPREFIX: transientPaths.pycache,
            PYTEST_DISABLE_PLUGIN_AUTOLOAD: "1",
            QS_AGENT_OUTPUT_DIR:
              transientPaths.sandbox_agent_data,
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
        },
        expected_skip_node_ids: [],
        dependency_inventory: {
          argv: [
            uvPath,
            "pip",
            "freeze",
            "--strict",
            "--python",
            backendPython,
          ],
          exit_code: 0,
          stderr: emptyArtifact(
            "dependency-inventory.stderr.log",
          ),
          stdout: inventoryArtifact,
        },
        evidence_directory: {
          mode: (fs.lstatSync(receiptDir).mode & 0o777)
            .toString(8)
            .padStart(3, "0"),
          owner_uid: fs.lstatSync(receiptDir).uid,
          parent_mode: (
            fs.lstatSync(path.dirname(receiptDir)).mode & 0o777
          )
            .toString(8)
            .padStart(3, "0"),
          parent_owner_uid: fs.lstatSync(
            path.dirname(receiptDir),
          ).uid,
          path: receiptDir,
        },
        fresh_environment: {
          inside_checkout: true,
          path: venv,
          preexisting: false,
        },
        inputs_after: currentInputs,
        inputs_before: currentInputs,
        installed_environment_normalization: {
          after_mode: "600",
          before_mode: "666",
          owner_uid: process.getuid(),
          path: ".lock",
        },
        installed_environment_tree_after: currentEnvironmentTree,
        installed_environment_tree_before: currentEnvironmentTree,
        installed_quant_system_tree_after: currentInstalledTree,
        installed_quant_system_tree_before: currentInstalledTree,
        install: {
          argv: [
            uvPath,
            "sync",
            "--frozen",
            "--no-editable",
            "--all-extras",
            "--python",
            "/opt/python/3.11/bin/python3.11",
          ],
          exit_code: 0,
          stderr: emptyArtifact("uv-sync.stderr.log"),
          stdout: emptyArtifact("uv-sync.stdout.log"),
        },
        marker_expression: markerExpression,
        network_sandbox: {
          argv: [
            "/usr/bin/sandbox-exec",
            "-p",
            outerProfile,
            backendPython,
            "-I",
            "-B",
            "-c",
            "<network-source>",
          ],
          executable_sha256: crypto
            .createHash("sha256")
            .update(fs.readFileSync("/usr/bin/sandbox-exec"))
            .digest("hex"),
          exit_code: 0,
          profile: outerProfile,
          stderr: networkStderr,
          stdout: networkStdout,
        },
        node: {
          argument: process.execPath,
          realpath: nodeRealpath,
          sha256: crypto
            .createHash("sha256")
            .update(fs.readFileSync(nodeRealpath))
            .digest("hex"),
          version: {
            argv: [nodeRealpath, "--version"],
            exit_code: 0,
            stderr: nodeVersionStderr,
            stdout: nodeVersionStdout,
            stdout_stderr_sha256: crypto
              .createHash("sha256")
              .update(
                Buffer.concat([
                  Buffer.from(nodeVersionBytes, "utf8"),
                  Buffer.from([0]),
                ]),
              )
              .digest("hex"),
          },
        },
        pytest: {
          collection: {
            argv: collectionArgv,
            exit_code: 0,
            stderr: collectionStderr,
            stdout: collectionStdout,
          },
          inner_sandbox_contract: {
            macos_outer_sandbox: false,
            parent_inet_audit_guard: true,
            product_child_macos_sandbox_required: true,
          },
          partition: {
            collected: {
              count: collectedNodes.length,
              node_ids_sha256: crypto
                .createHash("sha256")
                .update(canonicalJson(collectedNodes), "utf8")
                .digest("hex"),
            },
            exact_union: true,
            general: {
              count: generalNodes.length,
              node_ids_sha256: crypto
                .createHash("sha256")
                .update(canonicalJson(generalNodes), "utf8")
                .digest("hex"),
            },
            inner_sandbox: {
              count: innerNodes.length,
              node_ids: innerNodes,
              node_ids_sha256: crypto
                .createHash("sha256")
                .update(canonicalJson(innerNodes), "utf8")
                .digest("hex"),
            },
            overlap_count: 0,
          },
          result: twoPass,
          shards: {
            general: {
              argv: generalArgv,
              exit_code: 0,
              junit: generalJunit,
              result: onePass,
              stderr: generalStderr,
              stdout: generalStdout,
            },
            inner_sandbox: {
              argv: innerArgv,
              exit_code: 0,
              junit: innerJunit,
              result: onePass,
              stderr: innerStderr,
              stdout: innerStdout,
            },
          },
        },
        python: {
          argv: [
            backendPython,
            "-I",
            "-B",
            "-c",
            "<gate2-probe>",
          ],
          exit_code: 0,
          identity: {
            ...currentIdentity,
            direct_url_validation: {
              editable: false,
              expected_url:
                "file:///release/ai-quant-platform",
            },
            pth_files: [],
            sys_path: [sitePackages],
            version: "3.11.15",
          },
          lock_sha256: currentInputs["uv.lock"].sha256,
          stderr: emptyArtifact(
            "python-import-identity.stderr.log",
          ),
          stdout: {
            embedded_in_receipt: true,
            sha256: "a".repeat(64),
            size_bytes: 1,
          },
        },
        repository_after: receiptRepository,
        repository_before: receiptRepository,
        started_at: "2026-07-29T00:00:00Z",
        status: "passed",
        transient_runtime: {
          cleanup_owner: "outer_collector",
          evidence_artifact: false,
          paths: transientPaths,
          root: runtimeRoot,
          runner_recursive_cleanup: false,
        },
        uv: {
          realpath: uvPath,
          sha256: crypto
            .createHash("sha256")
            .update(uvContents, "utf8")
            .digest("hex"),
          version: {
            exit_code: 0,
            stderr: emptyArtifact("uv-version.stderr.log"),
            stdout: writeArtifact(
              receiptDir,
              "uv-version.stdout.log",
              "uv 0.11.22\n",
            ),
          },
        },
      };
      const receiptPath = path.join(
        receiptDir,
        "backend-non-postgres-receipt.json",
      );
      fs.writeFileSync(receiptPath, canonicalJson(receipt), {
        encoding: "utf8",
        mode: 0o600,
      });

      const authority = loadGate2ReceiptAuthority({
        backendPython,
        currentEnvironmentTree,
        currentIdentity,
        currentInputs,
        currentInstalledTree,
        expectedCommit,
        gate2Receipt: receiptPath,
        repoRoot,
        repository,
      });
      assert.equal(authority.status, "passed");
      assert.equal(authority.receipt_sha256.length, 64);
      assert.equal(authority.install_exit_code, 0);
      assert.equal(authority.environment_path, venv);

      const receiptHardlink = path.join(
        receiptParent,
        "receipt-hardlink.json",
      );
      fs.linkSync(receiptPath, receiptHardlink);
      assert.throws(
        () =>
          loadGate2ReceiptAuthority({
            backendPython,
            currentEnvironmentTree,
            currentIdentity,
            currentInputs,
            currentInstalledTree,
            expectedCommit,
            gate2Receipt: receiptPath,
            repoRoot,
            repository,
          }),
        /Gate 5 Gate 2 receipt ownership\/mode is unsafe/,
      );
      fs.unlinkSync(receiptHardlink);
      const artifactHardlink = path.join(
        receiptParent,
        "artifact-hardlink.log",
      );
      fs.linkSync(
        path.join(receiptDir, inventoryArtifact.path),
        artifactHardlink,
      );
      assert.throws(
        () =>
          loadGate2ReceiptAuthority({
            backendPython,
            currentEnvironmentTree,
            currentIdentity,
            currentInputs,
            currentInstalledTree,
            expectedCommit,
            gate2Receipt: receiptPath,
            repoRoot,
            repository,
          }),
        /Gate 5 Gate 2 artifact is unsafe/,
      );
      fs.unlinkSync(artifactHardlink);

      const forgedSemantics = JSON.parse(canonicalJson(receipt));
      forgedSemantics.pytest.shards.general.exit_code = 1;
      fs.writeFileSync(
        receiptPath,
        canonicalJson(forgedSemantics),
        "utf8",
      );
      assert.throws(
        () =>
          loadGate2ReceiptAuthority({
            backendPython,
            currentEnvironmentTree,
            currentIdentity,
            currentInputs,
            currentInstalledTree,
            expectedCommit,
            gate2Receipt: receiptPath,
            repoRoot,
            repository,
          }),
        /Gate 5 Gate 2 pytest shard authority is invalid/,
      );
      fs.writeFileSync(
        receiptPath,
        canonicalJson(receipt),
        "utf8",
      );

      const forgedRuntimeRoot = path.join(
        repoRoot,
        ".tmp",
        `backend-non-postgres-${expectedCommit.slice(
          0,
          12,
        )}-ffffffffffffffff`,
      );
      const forgedReceipt = JSON.parse(
        canonicalJson(receipt).replaceAll(
          runtimeRoot,
          forgedRuntimeRoot,
        ),
      );
      fs.writeFileSync(
        receiptPath,
        canonicalJson(forgedReceipt),
        "utf8",
      );
      assert.throws(
        () =>
          loadGate2ReceiptAuthority({
            backendPython: backendPython.replace(
              runtimeRoot,
              forgedRuntimeRoot,
            ),
            currentEnvironmentTree: {
              ...currentEnvironmentTree,
              root: currentEnvironmentTree.root.replace(
                runtimeRoot,
                forgedRuntimeRoot,
              ),
            },
            currentIdentity: JSON.parse(
              canonicalJson(currentIdentity).replaceAll(
                runtimeRoot,
                forgedRuntimeRoot,
              ),
            ),
            currentInputs,
            currentInstalledTree: {
              ...currentInstalledTree,
              root: currentInstalledTree.root.replace(
                runtimeRoot,
                forgedRuntimeRoot,
              ),
            },
            expectedCommit,
            gate2Receipt: receiptPath,
            repoRoot,
            repository,
          }),
        /Gate 5 Gate 2 runtime digest binding mismatch/,
      );
      fs.writeFileSync(
        receiptPath,
        canonicalJson(receipt),
        "utf8",
      );

      fs.appendFileSync(
        path.join(receiptDir, inventoryArtifact.path),
        "tampered\n",
        "utf8",
      );
      assert.throws(
        () =>
          loadGate2ReceiptAuthority({
            backendPython,
            currentEnvironmentTree,
            currentIdentity,
            currentInputs,
            currentInstalledTree,
            expectedCommit,
            gate2Receipt: receiptPath,
            repoRoot,
            repository,
          }),
        /Gate 5 Gate 2 artifact digest mismatch/,
      );
    } finally {
      fs.rmSync(receiptParent, { force: true, recursive: true });
    }
  });

  it("treats support TAP as an exact nonzero pass/skip contract", () => {
    const row = {
      contract: { expected: 44, skipped: 0 },
      id: "support",
    };
    const tap = (tests, passed, skipped) => `
TAP version 13
1..${tests}
# tests ${tests}
# pass ${passed}
# fail 0
# cancelled 0
# skipped ${skipped}
# todo 0
`;

    assert.deepEqual(validateSupportTap(row, tap(44, 44, 0)), {
      expected: 44,
      skipped: 0,
      total: 44,
    });
    assert.throws(
      () => validateSupportTap(row, tap(0, 0, 0)),
      /support discovered zero tests/,
    );
    assert.throws(
      () => validateSupportTap(row, tap(44, 43, 1)),
      /support skip contract mismatch: expected 0, got 1/,
    );
  });

  it("runs rows sequentially and seals canonical reports plus one canonical summary", async () => {
    for (const invalidValue of [
      Number.NaN,
      Number.POSITIVE_INFINITY,
      Number.NEGATIVE_INFINITY,
      undefined,
      1n,
      () => {},
      Symbol("not-json"),
    ]) {
      assert.throws(
        () =>
          serializeCanonicalEvidence({
            nested: { invalid: invalidValue },
          }),
        /Gate 5 canonical JSON forbids/,
      );
    }
    assert.throws(
      () => serializeCanonicalEvidence(new Array(1)),
      /Gate 5 canonical JSON forbids undefined array entries/,
    );
    assert.throws(
      () =>
        serializeCanonicalEvidence({
          [Symbol("hidden")]: "not-json",
          visible: true,
        }),
      /Gate 5 canonical JSON forbids symbol-keyed properties/,
    );
    const frontendRoot = path.dirname(
      path.dirname(fileURLToPath(import.meta.url)),
    );
    const temporaryBase = path.join(frontendRoot, ".tmp");
    fs.mkdirSync(temporaryBase, { mode: 0o700, recursive: true });
    const temporaryRoot = fs.mkdtempSync(
      path.join(temporaryBase, "hermes-gate5-unit-"),
    );
    const reportDir = path.join(temporaryRoot, "evidence");
    fs.mkdirSync(reportDir, { mode: 0o700 });
    const matrix = buildGate5Matrix({
      backendPython: "/release/ai-quant/bin/python",
      baseEnv: { PATH: "/safe/bin" },
      outputDir: reportDir,
      ports: Array.from({ length: 19 }, (_, index) => 46_000 + index),
      runToken: "receipt",
    });
    const seen = [];
    const supportTap = `
TAP version 13
1..44
# tests 44
# pass 44
# fail 0
# cancelled 0
# skipped 0
# todo 0
`;

    try {
      const backendAuthority = unitBackendAuthority();
      const frontendAuthority = unitFrontendAuthority();
      const summary = await runGate5Matrix({
        backendAuthority,
        execute: async (row) => {
          seen.push(row.id);
          return {
            exitCode: 0,
            reportText:
              row.kind === "playwright"
                ? JSON.stringify(playwrightReportForRow(row))
                : undefined,
            stderr: "",
            stdout: row.kind === "node-test" ? supportTap : `${row.id}\n`,
          };
        },
        frontendAuthority,
        matrix,
        reportDir,
        verifyAuthority: () => ({
          backend: backendAuthority,
          frontend: frontendAuthority,
          repository: backendAuthority.repository,
        }),
      });

      assert.deepEqual(
        seen,
        matrix.map((row) => row.id),
      );
      assert.equal(summary.status, "passed");
      assert.equal(summary.rows.length, 9);
      assert.equal(summary.rows.every((row) => row.status === "passed"), true);
      for (const [index, row] of summary.rows.entries()) {
        assert.match(row.started_at, /^\d{4}-\d{2}-\d{2}T/);
        assert.match(row.completed_at, /^\d{4}-\d{2}-\d{2}T/);
        assert.deepEqual(row.environment, matrix[index].env);
        assert.equal(
          row.environment_sha256,
          crypto
            .createHash("sha256")
            .update(canonicalJson(matrix[index].env), "utf8")
            .digest("hex"),
        );
        assert.equal(
          row.path,
          `${path.dirname(process.execPath)}:/usr/bin:/bin`,
        );
        assert.equal(row.artifacts.stderr.size_bytes, 0);
        assert.equal(
          row.artifacts.stderr.sha256,
          crypto.createHash("sha256").update("").digest("hex"),
        );
        assert.equal(
          row.artifacts.stdout.size_bytes,
          row.output_bytes,
        );
        assert.equal(
          row.artifacts.stdout.sha256,
          row.output_sha256,
        );
        assert.equal(
          row.kind === "playwright",
          row.artifacts.playwright_report !== null,
        );
      }
      assert.deepEqual(summary.runtime_cleanup, {
        error: null,
        status: "removed",
      });
      assert.equal(
        fs.existsSync(path.dirname(matrix[0].runtimeRoot)),
        false,
      );
      assert.equal(
        fs.readFileSync(path.join(reportDir, "support.stdout.tap"), "utf8"),
        supportTap,
      );
      for (const row of matrix.filter(
        (candidate) => candidate.kind === "playwright",
      )) {
        const rawReport = fs.readFileSync(
          path.join(reportDir, `${row.id}.playwright.json`),
          "utf8",
        );
        assert.equal(
          rawReport,
          canonicalJson(JSON.parse(rawReport)),
          row.id,
        );
        assert.equal(
          fs.existsSync(path.join(reportDir, `${row.id}.stdout.log`)),
          false,
          row.id,
        );
      }
      const evidenceEntries = fs.readdirSync(reportDir);
      assert.equal(evidenceEntries.includes("runtime"), false);
      for (const entry of evidenceEntries) {
        const stat = fs.lstatSync(path.join(reportDir, entry));
        assert.equal(stat.isSymbolicLink(), false, entry);
        assert.equal(stat.isFile(), true, entry);
      }
      const rawSummary = fs.readFileSync(
        path.join(reportDir, "gate5-summary.json"),
        "utf8",
      );
      assert.equal(rawSummary, canonicalJson(summary));
      assert.deepEqual(
        JSON.parse(rawSummary),
        summary,
      );

      const driftReportDir = path.join(
        temporaryRoot,
        "drift-evidence",
      );
      fs.mkdirSync(driftReportDir, { mode: 0o700 });
      const driftMatrix = buildGate5Matrix({
        backendPython: "/release/ai-quant/bin/python",
        baseEnv: { PATH: "/safe/bin" },
        outputDir: driftReportDir,
        ports: Array.from(
          { length: 19 },
          (_, index) => 47_000 + index,
        ),
        runToken: "receipt-drift",
      });
      await assert.rejects(
        runGate5Matrix({
          backendAuthority,
          execute: async (row) => ({
            exitCode: 0,
            reportText:
              row.kind === "playwright"
                ? JSON.stringify(playwrightReportForRow(row))
                : undefined,
            stderr: "",
            stdout:
              row.kind === "node-test"
                ? supportTap
                : `${row.id}\n`,
          }),
          frontendAuthority,
          matrix: driftMatrix,
          reportDir: driftReportDir,
          verifyAuthority: () => ({
            backend: {
              ...backendAuthority,
              drifted_after_rows: true,
            },
            frontend: frontendAuthority,
            repository: backendAuthority.repository,
          }),
        }),
        /Gate 5 failed rows: final-authority/,
      );
      const driftSummary = JSON.parse(
        fs.readFileSync(
          path.join(driftReportDir, "gate5-summary.json"),
          "utf8",
        ),
      );
      assert.equal(driftSummary.status, "failed");
      assert.match(
        driftSummary.final_authority_error,
        /repository, backend, or frontend identity changed during Gate 5/,
      );
    } finally {
      fs.rmSync(temporaryRoot, { force: true, recursive: true });
    }
  });

  it("continues after a red row and reports every remaining matrix mode", async () => {
    const frontendRoot = path.dirname(
      path.dirname(fileURLToPath(import.meta.url)),
    );
    const temporaryBase = path.join(frontendRoot, ".tmp");
    fs.mkdirSync(temporaryBase, { mode: 0o700, recursive: true });
    const temporaryRoot = fs.mkdtempSync(
      path.join(temporaryBase, "hermes-gate5-continue-"),
    );
    const reportDir = path.join(temporaryRoot, "evidence");
    fs.mkdirSync(reportDir, { mode: 0o700 });
    const matrix = buildGate5Matrix({
      backendPython: "/release/ai-quant/bin/python",
      baseEnv: { PATH: "/safe/bin" },
      outputDir: reportDir,
      ports: Array.from({ length: 19 }, (_, index) => 48_000 + index),
      runToken: "continue",
    });
    const seen = [];
    const duplicateRawReport =
      "{\"stats\":{},\"stats\":{\"provider_body\":\"credential-shaped invalid raw report\"}}";
    const supportTap = `
TAP version 13
1..44
# tests 44
# pass 44
# fail 0
# cancelled 0
# skipped 0
# todo 0
`;

    try {
      const backendAuthority = unitBackendAuthority();
      const frontendAuthority = unitFrontendAuthority();
      await assert.rejects(
        runGate5Matrix({
          backendAuthority,
          execute: async (row) => {
            seen.push(row.id);
            return {
              exitCode: 0,
              reportText:
                row.kind === "playwright"
                  ? row.id === "real-smoke"
                    ? duplicateRawReport
                    : JSON.stringify(playwrightReportForRow(row))
                  : undefined,
              stderr: "",
              stdout: row.kind === "node-test" ? supportTap : `${row.id}\n`,
            };
          },
          frontendAuthority,
          matrix,
          reportDir,
          verifyAuthority: () => ({
            backend: backendAuthority,
            frontend: frontendAuthority,
            repository: backendAuthority.repository,
          }),
        }),
        /Gate 5 failed rows: real-smoke/,
      );

      assert.deepEqual(
        seen,
        matrix.map((row) => row.id),
      );
      const summary = JSON.parse(
        fs.readFileSync(
          path.join(reportDir, "gate5-summary.json"),
          "utf8",
        ),
      );
      assert.equal(summary.status, "failed");
      assert.equal(summary.rows.length, matrix.length);
      assert.equal(
        summary.rows.find((row) => row.id === "real-smoke").status,
        "failed",
      );
      const failedRow = summary.rows.find(
        (row) => row.id === "real-smoke",
      );
      assert.equal(
        failedRow.error,
        "real-smoke Playwright JSON contains a duplicate object key",
      );
      assert.equal(
        failedRow.output_sha256,
        crypto
          .createHash("sha256")
          .update(duplicateRawReport, "utf8")
          .digest("hex"),
      );
      assert.equal(failedRow.playwright_report, null);
      assert.equal(failedRow.stdout, null);
      assert.equal(
        fs.existsSync(
          path.join(reportDir, "real-smoke.playwright.json"),
        ),
        false,
      );
      assert.equal(
        fs.readdirSync(reportDir).some((entry) =>
          fs
            .readFileSync(path.join(reportDir, entry), "utf8")
            .includes(duplicateRawReport),
        ),
        false,
      );
      assert.equal(
        summary.rows.find((row) => row.id === "rollback").status,
        "passed",
      );
      assert.deepEqual(summary.runtime_cleanup, {
        error: null,
        status: "removed",
      });
      assert.equal(
        fs.existsSync(path.dirname(matrix[0].runtimeRoot)),
        false,
      );
    } finally {
      fs.rmSync(temporaryRoot, { force: true, recursive: true });
    }
  });
});
