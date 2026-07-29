import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { describe, it } from "node:test";

import {
  assertSafeCliArgs,
  buildGate5Matrix,
  canonicalJson as serializeCanonicalEvidence,
  parsePlaywrightJson,
  runGate5Matrix,
  validatePlaywrightReport,
  validateSupportTap,
} from "./run-hermes-gate5.mjs";

const FRONTEND_ROOT = path.dirname(
  path.dirname(fileURLToPath(import.meta.url)),
);

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
    assert.deepEqual(byId.support.args, ["run", "test:gate5-support"]);
    assert.deepEqual(byId.support.contract, {
      expected: 38,
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
      assert.equal(row.env.PATH, "/safe/bin");
      assert.equal(row.env.PW_E2E, "1");
      assert.equal(row.env.PW_BACKEND_PORT, String(row.backendPort));
      assert.equal(row.env.PW_FRONTEND_PORT, String(row.frontendPort));
      assert.equal(row.env.PW_E2E_RUN_ID, row.runId);
      assert.equal(row.env.PW_PYTHON, "/release/ai-quant/bin/python");
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
    const safeArgs = [
      "--output-dir",
      "/release-evidence/gate5",
      "--backend-python=/release/ai-quant/bin/python",
    ];
    assert.deepEqual(assertSafeCliArgs(safeArgs), {
      backendPython: "/release/ai-quant/bin/python",
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
  });

  it("treats support TAP as an exact nonzero pass/skip contract", () => {
    const row = {
      contract: { expected: 38, skipped: 0 },
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

    assert.deepEqual(validateSupportTap(row, tap(38, 38, 0)), {
      expected: 38,
      skipped: 0,
      total: 38,
    });
    assert.throws(
      () => validateSupportTap(row, tap(0, 0, 0)),
      /support discovered zero tests/,
    );
    assert.throws(
      () => validateSupportTap(row, tap(38, 37, 1)),
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
1..38
# tests 38
# pass 38
# fail 0
# cancelled 0
# skipped 0
# todo 0
`;

    try {
      const summary = await runGate5Matrix({
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
        matrix,
        reportDir,
      });

      assert.deepEqual(
        seen,
        matrix.map((row) => row.id),
      );
      assert.equal(summary.status, "passed");
      assert.equal(summary.rows.length, 9);
      assert.equal(summary.rows.every((row) => row.status === "passed"), true);
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
1..38
# tests 38
# pass 38
# fail 0
# cancelled 0
# skipped 0
# todo 0
`;

    try {
      await assert.rejects(
        runGate5Matrix({
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
          matrix,
          reportDir,
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
