import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";

import {
  CANDIDATE_REQUIRED_KEYS,
  HERMES_WORKBENCH_FIXTURE_NAMES,
  createFixtureServer,
  loadFixture,
  validateCombinedFixture,
} from "./hermes-fixture-api.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "..", "..");
const repoRoot = path.resolve(frontendRoot, "..", "..");

function listenEphemeral(server) {
  return new Promise((resolve, reject) => {
    const onError = (error) => {
      server.off("error", onError);
      reject(error);
    };
    server.once("error", onError);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", onError);
      const address = server.address();
      if (!address || typeof address === "string") {
        reject(new Error("expected TCP address"));
        return;
      }
      resolve(address.port);
    });
  });
}

function closeServer(server) {
  return new Promise((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
}

function request(port, method, pathname) {
  return new Promise((resolve, reject) => {
    const req = http.request(
      {
        host: "127.0.0.1",
        port,
        path: pathname,
        method,
        headers: { accept: "application/json" },
      },
      (res) => {
        const chunks = [];
        res.on("data", (chunk) => chunks.push(chunk));
        res.on("end", () => {
          resolve({
            status: res.statusCode ?? 0,
            headers: res.headers,
            body: Buffer.concat(chunks),
          });
        });
      },
    );
    req.on("error", reject);
    req.end();
  });
}

function spawnCapture(command, args, env) {
  return new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd: frontendRoot,
      env: { ...process.env, ...env },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("close", (code) => {
      resolve({ code: code ?? 1, stdout, stderr });
    });
  });
}

describe("hermes-fixture-api", () => {
  it("loads all five exact fixture names through the shared validator", () => {
    for (const name of HERMES_WORKBENCH_FIXTURE_NAMES) {
      const fixture = loadFixture(name);
      assert.deepEqual(Object.keys(fixture).sort(), [
        "artifacts",
        "candidates",
        "health",
        "schema_version",
      ]);
      assert.equal(typeof fixture.schema_version, "string");
      assert.ok(fixture.health);
      assert.ok(fixture.artifacts);
      assert.ok(fixture.candidates);
    }
  });

  it("serves the three exact GET routes with Cache-Control no-store", async () => {
    const fixture = loadFixture("normal");
    const server = createFixtureServer(fixture);
    const port = await listenEphemeral(server);
    try {
      const health = await request(port, "GET", "/api/health");
      const artifacts = await request(port, "GET", "/api/hermes/artifacts");
      const candidates = await request(port, "GET", "/api/agent/candidates");

      assert.equal(health.status, 200);
      assert.equal(artifacts.status, 200);
      assert.equal(candidates.status, 200);
      assert.equal(health.headers["cache-control"], "no-store");
      assert.equal(artifacts.headers["cache-control"], "no-store");
      assert.equal(candidates.headers["cache-control"], "no-store");
      assert.deepEqual(JSON.parse(health.body.toString("utf8")), fixture.health);
      assert.deepEqual(
        JSON.parse(artifacts.body.toString("utf8")),
        fixture.artifacts,
      );
      assert.deepEqual(
        JSON.parse(candidates.body.toString("utf8")),
        fixture.candidates,
      );
    } finally {
      await closeServer(server);
    }
  });

  it("returns 404 for unknown GET and 405 for non-GET without mutating fixtures", async () => {
    const fixture = loadFixture("degraded");
    const before = JSON.stringify(fixture);
    const server = createFixtureServer(fixture);
    const port = await listenEphemeral(server);
    try {
      const unknown = await request(port, "GET", "/api/unknown");
      assert.equal(unknown.status, 404);

      for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
        const response = await request(port, method, "/api/health");
        assert.equal(response.status, 405, method);
      }

      const health = await request(port, "GET", "/api/health");
      assert.equal(health.status, 200);
      assert.deepEqual(JSON.parse(health.body.toString("utf8")), fixture.health);
      assert.equal(JSON.stringify(fixture), before);
    } finally {
      await closeServer(server);
    }
  });

  it("rejects an unknown fixture before listen()", () => {
    assert.throws(() => loadFixture("not-a-real-fixture"), /unknown hermes workbench fixture/);
  });

  it("rejects fixtures that omit any required candidate key", () => {
    const base = loadFixture("normal");
    for (const key of CANDIDATE_REQUIRED_KEYS) {
      const clone = structuredClone(base);
      assert.ok(clone.candidates.candidates.length > 0);
      delete clone.candidates.candidates[0][key];
      assert.throws(
        () => validateCombinedFixture(clone),
        new RegExp(`missing required key: ${key}`),
        `expected rejection when omitting ${key}`,
      );
    }

    // Explicit coverage for goal, universe, and required nullable keys.
    for (const key of [
      "goal",
      "universe",
      "manifest_digest",
      "observed_manifest_digest",
      "approval_binding",
      "artifact_type",
      "status",
      "integrity_error_code",
    ]) {
      const clone = structuredClone(base);
      delete clone.candidates.candidates[0][key];
      assert.throws(() => validateCombinedFixture(clone), /missing required key/);
    }
  });

  it("rejects unknown fixture names from createFixtureServer path via loadFixture only", () => {
    assert.throws(() => loadFixture("bogus"), /unknown hermes workbench fixture/);
  });

  it("fails playwright config load when fixture mode coexists with backend override", async () => {
    const stable = "fixture mode cannot reuse or override the backend";
    const withCommand = await spawnCapture(
      "npx",
      ["playwright", "test", "--list"],
      {
        PW_HERMES_WORKBENCH_FIXTURE: "normal",
        QUANT_API_COMMAND: "echo should-not-run",
        PW_E2E: "1",
      },
    );
    assert.notEqual(withCommand.code, 0);
    assert.match(
      `${withCommand.stdout}\n${withCommand.stderr}`,
      new RegExp(stable),
    );

    const withReuse = await spawnCapture(
      "npx",
      ["playwright", "test", "--list"],
      {
        PW_HERMES_WORKBENCH_FIXTURE: "normal",
        PW_REUSE_SERVER: "1",
        PW_E2E: "1",
      },
    );
    assert.notEqual(withReuse.code, 0);
    assert.match(
      `${withReuse.stdout}\n${withReuse.stderr}`,
      new RegExp(stable),
    );
  });
});
