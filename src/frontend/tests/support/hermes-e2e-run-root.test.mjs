import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import {
  E2E_RUN_PROVENANCE_FILE,
  buildE2ERunIdentity,
  cleanupE2ERunRoot,
  prepareE2ERunRoot,
} from "./hermes-e2e-run-root.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const runnerPath = path.join(__dirname, "hermes-e2e-backend-runner.mjs");

function makeBaseRoot() {
  return fs.mkdtempSync(
    path.join(fs.realpathSync(os.tmpdir()), "hermes-e2e-root-test-"),
  );
}

describe("Hermes Playwright run-root ownership", () => {
  it("derives a distinct bounded root for each process when no run id is supplied", () => {
    const baseRoot = "/tmp/hermes-e2e-data";
    const first = buildE2ERunIdentity({
      baseRoot,
      backendPort: 41_001,
      frontendPort: 42_001,
      processId: 111,
    });
    const second = buildE2ERunIdentity({
      baseRoot,
      backendPort: 41_001,
      frontendPort: 42_001,
      processId: 222,
    });

    assert.notEqual(first.runId, second.runId);
    assert.notEqual(first.dataRoot, second.dataRoot);
    assert.equal(path.dirname(first.dataRoot), path.resolve(baseRoot));
    assert.equal(path.dirname(second.dataRoot), path.resolve(baseRoot));
  });

  it("rejects run ids that could escape or alias the owned base root", () => {
    for (const rawRunId of ["../escape", "nested/id", ".", "", "two words"]) {
      assert.throws(
        () =>
          buildE2ERunIdentity({
            baseRoot: "/tmp/hermes-e2e-data",
            rawRunId,
            backendPort: 41_001,
            frontendPort: 42_001,
            processId: 111,
          }),
        /PW_E2E_RUN_ID/,
        rawRunId,
      );
    }
  });

  it("rejects a symlinked base ancestor before creating any run-root bytes", () => {
    const container = makeBaseRoot();
    const outside = path.join(container, "outside");
    const marker = path.join(outside, "must-survive.txt");
    const symlinkedAncestor = path.join(container, "base-alias");
    fs.mkdirSync(outside);
    fs.writeFileSync(marker, "untouched\n", "utf8");
    fs.symlinkSync(outside, symlinkedAncestor, "dir");
    const identity = buildE2ERunIdentity({
      baseRoot: path.join(symlinkedAncestor, "e2e-data"),
      rawRunId: "symlink-rejected-run",
      backendPort: 41_010,
      frontendPort: 42_010,
      processId: 1_010,
    });

    try {
      assert.throws(
        () =>
          prepareE2ERunRoot(identity, {
            fixture: "normal",
            ownerToken: "owner-token-symlink",
          }),
        /symbolic link|canonical/,
      );
      assert.deepEqual(fs.readdirSync(outside), ["must-survive.txt"]);
      assert.equal(fs.readFileSync(marker, "utf8"), "untouched\n");
    } finally {
      fs.rmSync(container, { recursive: true, force: true });
    }
  });

  it("refuses cleanup through a replaced symlink base chain", () => {
    const container = makeBaseRoot();
    const baseRoot = path.join(container, "base");
    const parkedBase = path.join(container, "parked-owned-base");
    const outside = path.join(container, "outside");
    const marker = path.join(outside, "must-survive.txt");
    const identity = buildE2ERunIdentity({
      baseRoot,
      rawRunId: "cleanup-symlink-rejected-run",
      backendPort: 41_011,
      frontendPort: 42_011,
      processId: 1_011,
    });

    try {
      prepareE2ERunRoot(identity, {
        fixture: "normal",
        ownerToken: "owner-token-cleanup-symlink",
      });
      fs.renameSync(baseRoot, parkedBase);
      fs.mkdirSync(outside);
      fs.writeFileSync(marker, "untouched\n", "utf8");
      fs.symlinkSync(outside, baseRoot, "dir");

      assert.throws(
        () =>
          cleanupE2ERunRoot(identity, {
            fixture: "normal",
            ownerToken: "owner-token-cleanup-symlink",
          }),
        /symbolic link|canonical/,
      );
      assert.deepEqual(fs.readdirSync(outside), ["must-survive.txt"]);
      assert.equal(fs.readFileSync(marker, "utf8"), "untouched\n");
      assert.equal(
        fs.existsSync(path.join(parkedBase, identity.runId)),
        true,
      );
    } finally {
      fs.rmSync(container, { recursive: true, force: true });
    }
  });

  it("records exact provenance and removes only the matching owned root", () => {
    const baseRoot = makeBaseRoot();
    const identity = buildE2ERunIdentity({
      baseRoot,
      rawRunId: "reviewed-run-001",
      backendPort: 41_001,
      frontendPort: 42_001,
      processId: 111,
    });
    const ownerToken = "owner-token-001";

    try {
      prepareE2ERunRoot(identity, {
        fixture: "degraded",
        ownerToken,
      });
      const provenance = JSON.parse(
        fs.readFileSync(
          path.join(identity.dataRoot, E2E_RUN_PROVENANCE_FILE),
          "utf8",
        ),
      );
      assert.deepEqual(provenance, {
        backend_port: 41_001,
        data_root: identity.dataRoot,
        fixture: "degraded",
        frontend_port: 42_001,
        owner_token: ownerToken,
        run_id: "reviewed-run-001",
        schema_version: "hermes-playwright-run-root.v1",
      });

      cleanupE2ERunRoot(identity, {
        fixture: "degraded",
        ownerToken,
      });
      assert.equal(fs.existsSync(identity.dataRoot), false);
      assert.equal(fs.existsSync(baseRoot), true);
    } finally {
      fs.rmSync(baseRoot, { recursive: true, force: true });
    }
  });

  it("fails closed instead of deleting a root with drifted provenance", () => {
    const baseRoot = makeBaseRoot();
    const identity = buildE2ERunIdentity({
      baseRoot,
      rawRunId: "reviewed-run-002",
      backendPort: 41_002,
      frontendPort: 42_002,
      processId: 222,
    });

    try {
      prepareE2ERunRoot(identity, {
        fixture: null,
        ownerToken: "owner-token-002",
      });
      const provenancePath = path.join(
        identity.dataRoot,
        E2E_RUN_PROVENANCE_FILE,
      );
      const provenance = JSON.parse(fs.readFileSync(provenancePath, "utf8"));
      provenance.data_root = path.join(baseRoot, "different-root");
      provenance.fixture = "normal";
      fs.writeFileSync(provenancePath, `${JSON.stringify(provenance)}\n`, {
        encoding: "utf8",
        mode: 0o600,
      });

      assert.throws(
        () =>
          cleanupE2ERunRoot(identity, {
            fixture: null,
            ownerToken: "owner-token-002",
          }),
        /provenance mismatch/,
      );
      assert.equal(fs.existsSync(identity.dataRoot), true);
    } finally {
      fs.rmSync(baseRoot, { recursive: true, force: true });
    }
  });

  it("supervises the backend and cleans the exact root when the child exits", () => {
    const baseRoot = makeBaseRoot();
    const payload = Buffer.from(
      JSON.stringify({
        args: ["-e", 'process.stdout.write("fixture-child-ready\\n")'],
        backendPort: 41_003,
        baseRoot,
        command: process.execPath,
        fixture: "empty",
        frontendPort: 42_003,
        runId: "supervised-run-003",
      }),
      "utf8",
    ).toString("base64url");

    try {
      const result = spawnSync(process.execPath, [runnerPath, payload], {
        encoding: "utf8",
      });
      assert.equal(result.status, 0, result.stderr);
      assert.match(result.stdout, /fixture-child-ready/);
      assert.match(result.stdout, /"run_id":"supervised-run-003"/);
      assert.equal(
        fs.existsSync(path.join(baseRoot, "supervised-run-003")),
        false,
      );
    } finally {
      fs.rmSync(baseRoot, { recursive: true, force: true });
    }
  });

  it("treats Playwright SIGTERM as a clean supervised shutdown and removes the root", async () => {
    const baseRoot = makeBaseRoot();
    const payload = Buffer.from(
      JSON.stringify({
        args: [
          "-e",
          'process.stdout.write("fixture-child-waiting\\n"); setInterval(() => {}, 1000)',
        ],
        backendPort: 41_004,
        baseRoot,
        command: process.execPath,
        fixture: "lifecycle",
        frontendPort: 42_004,
        runId: "supervised-term-run-004",
      }),
      "utf8",
    ).toString("base64url");

    const runner = spawn(process.execPath, [runnerPath, payload], {
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    runner.stdout.setEncoding("utf8");
    runner.stderr.setEncoding("utf8");
    runner.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    runner.stderr.on("data", (chunk) => {
      stderr += chunk;
    });

    try {
      await new Promise((resolve, reject) => {
        const timeout = setTimeout(
          () => reject(new Error("runner did not become ready")),
          5_000,
        );
        const onData = () => {
          if (
            stdout.includes("HERMES_E2E_RUN_ROOT_READY") &&
            stdout.includes("fixture-child-waiting")
          ) {
            clearTimeout(timeout);
            runner.stdout.off("data", onData);
            resolve();
          }
        };
        runner.stdout.on("data", onData);
        runner.once("error", reject);
        runner.once("exit", (code, signal) => {
          clearTimeout(timeout);
          reject(
            new Error(
              `runner exited before readiness code=${code} signal=${signal}`,
            ),
          );
        });
      });

      runner.kill("SIGTERM");
      const exit = await new Promise((resolve, reject) => {
        const timeout = setTimeout(
          () => reject(new Error("runner did not stop after SIGTERM")),
          5_000,
        );
        runner.once("exit", (code, signal) => {
          clearTimeout(timeout);
          resolve({ code, signal });
        });
      });
      assert.deepEqual(exit, { code: 0, signal: null }, stderr);
      assert.equal(
        fs.existsSync(path.join(baseRoot, "supervised-term-run-004")),
        false,
      );
    } finally {
      if (runner.exitCode === null && runner.signalCode === null) {
        runner.kill("SIGTERM");
      }
      fs.rmSync(baseRoot, { recursive: true, force: true });
    }
  });
});
