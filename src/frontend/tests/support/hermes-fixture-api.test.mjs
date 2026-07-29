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

function request(
  port,
  method,
  pathname,
  { headers = {}, body } = {},
) {
  return new Promise((resolve, reject) => {
    const req = http.request(
      {
        host: "127.0.0.1",
        port,
        path: pathname,
        method,
        headers: { accept: "application/json", ...headers },
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
    req.end(body);
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
        "factors",
        "health",
        "schema_version",
      ]);
      assert.equal(typeof fixture.schema_version, "string");
      assert.ok(fixture.health);
      assert.ok(fixture.artifacts);
      assert.ok(fixture.candidates);
      assert.ok(fixture.factors);
    }
  });

  it("exposes fixture-only readiness for every mode without claiming gateway connectivity", async () => {
    for (const name of HERMES_WORKBENCH_FIXTURE_NAMES) {
      const fixture = loadFixture(name);
      const server = createFixtureServer(fixture, {
        includePersistedSession: name === "normal",
        includeFixtureGateway: true,
      });
      const port = await listenEphemeral(server);
      try {
        const readiness = await request(
          port,
          "GET",
          "/api/hermes/fixture-ready",
        );
        const gateway = await request(port, "GET", "/api/hermes/gateway");

        assert.equal(readiness.status, 200, name);
        assert.equal(readiness.headers["cache-control"], "no-store", name);
        assert.deepEqual(
          JSON.parse(readiness.body.toString("utf8")),
          {
            ready: true,
            transport: "loopback_get_only_fixture",
          },
          name,
        );
        assert.equal(gateway.status, 200, name);
        assert.equal(
          Object.hasOwn(
            JSON.parse(readiness.body.toString("utf8")),
            "connected",
          ),
          false,
          name,
        );
      } finally {
        await closeServer(server);
      }
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

  it("serves one deterministic long persisted session through the public read interface", async () => {
    const fixture = loadFixture("normal");
    const server = createFixtureServer(fixture, { includePersistedSession: true });
    const port = await listenEphemeral(server);
    try {
      const gateway = await request(port, "GET", "/api/hermes/gateway");
      const sessions = await request(
        port,
        "GET",
        "/api/hermes/sessions?limit=50&offset=0",
      );
      const detail = await request(
        port,
        "GET",
        "/api/hermes/sessions/fixture-long-session",
      );
      const messages = await request(
        port,
        "GET",
        "/api/hermes/sessions/fixture-long-session/messages",
      );

      assert.equal(gateway.status, 200);
      assert.equal(sessions.status, 200);
      assert.equal(detail.status, 200);
      assert.equal(messages.status, 200);
      assert.equal(gateway.headers["cache-control"], "no-store");

      const gatewayBody = JSON.parse(gateway.body.toString("utf8"));
      const sessionsBody = JSON.parse(sessions.body.toString("utf8"));
      const detailBody = JSON.parse(detail.body.toString("utf8"));
      const messagesBody = JSON.parse(messages.body.toString("utf8"));
      assert.equal(gatewayBody.read_status, "available");
      assert.equal(gatewayBody.chat_write_ready, false);
      assert.deepEqual(gatewayBody.features, { session_resources: true });
      assert.equal(sessionsBody.sessions.length, 1);
      assert.equal(sessionsBody.sessions[0].id, "fixture-long-session");
      assert.equal(detailBody.session.id, "fixture-long-session");
      assert.ok(messagesBody.messages.length >= 40);
      assert.equal(messagesBody.messages.at(-1).content, "Latest fixture message");
    } finally {
      await closeServer(server);
    }
  });

  it("keeps the lifecycle fixture explicit while exercising exact local mutation receipts", async () => {
    const fixture = loadFixture("normal");
    const server = createFixtureServer(fixture, {
      includePersistedSession: true,
      includeLifecycle: true,
    });
    const port = await listenEphemeral(server);
    const csrfHeaders = {
      "content-type": "application/json",
      cookie: "qs_aw_csrf=fixture-csrf-token",
      "x-csrf-token": "fixture-csrf-token",
    };
    try {
      const readiness = await request(
        port,
        "GET",
        "/api/hermes/fixture-ready",
      );
      const gateway = await request(port, "GET", "/api/hermes/gateway");
      const owner = await request(port, "GET", "/api/auth/owner/session");
      const snapshotBefore = await request(
        port,
        "GET",
        "/api/workspace/ws-local-main/snapshot",
      );

      assert.deepEqual(
        JSON.parse(readiness.body.toString("utf8")),
        {
          ready: true,
          transport: "loopback_lifecycle_fixture",
        },
      );
      assert.equal(gateway.status, 200);
      assert.equal(
        JSON.parse(gateway.body.toString("utf8")).chat_write_ready,
        true,
      );
      assert.match(String(owner.headers["set-cookie"]), /qs_aw_csrf=/);
      const before = JSON.parse(snapshotBefore.body.toString("utf8"));
      assert.equal(before.mutation_enabled, true);
      assert.equal(before.managed_sessions.length, 1);
      assert.equal(before.commands[0].state, "delivered");
      assert.equal(before.approvals[0].status, "pending");
      assert.deepEqual(
        before.gates.map((row) => [row.gate_kind, row.status]),
        [
          ["gate1", "confirmed"],
          ["gate2", "pending"],
          ["gate3", "prepared"],
        ],
      );
      assert.equal(before.results[0].status, "completed");

      const turn = await request(
        port,
        "POST",
        "/api/agent/workspace/submit-turn",
        {
          headers: csrfHeaders,
          body: JSON.stringify({
            client_action_id: "fixture-turn-test",
            managed_session_ref: "session:wm_11111111111111111111111111111111",
            prompt: "Exact local fixture prompt",
          }),
        },
      );
      assert.equal(turn.status, 200);
      const turnBody = JSON.parse(turn.body.toString("utf8"));
      assert.equal(turnBody.status, "accepted");
      assert.equal(
        turnBody.hermes_session_id,
        `web_${"1".repeat(40)}`,
      );

      const stop = await request(
        port,
        "POST",
        "/api/workspace/ws-local-main/act",
        {
          headers: csrfHeaders,
          body: JSON.stringify({
            action: {
              kind: "run.stop.request",
              client_action_id: "fixture-stop-test",
              run_ref: "run:fixture-run-active-001",
            },
          }),
        },
      );
      assert.equal(stop.status, 200);
      assert.equal(JSON.parse(stop.body.toString("utf8")).status, "accepted");

      const snapshotAfter = await request(
        port,
        "GET",
        "/api/workspace/ws-local-main/snapshot",
      );
      const after = JSON.parse(snapshotAfter.body.toString("utf8"));
      assert.equal(
        after.commands.find(
          (row) => row.command_id === "fixture-command-active-001",
        ).state,
        "cancelled",
      );
      const audit = await request(
        port,
        "GET",
        "/api/hermes/fixture-audit",
      );
      assert.deepEqual(
        JSON.parse(audit.body.toString("utf8")).events.map((row) => row.kind),
        ["conversation.turn", "run.stop.request"],
      );
    } finally {
      await closeServer(server);
    }
  });

  it("does not let non-session fixtures masquerade as a connected Hermes gateway", async () => {
    const fixture = loadFixture("offline");
    const server = createFixtureServer(fixture);
    const port = await listenEphemeral(server);
    try {
      const gateway = await request(port, "GET", "/api/hermes/gateway");
      const sessions = await request(port, "GET", "/api/hermes/sessions");
      assert.equal(gateway.status, 404);
      assert.equal(sessions.status, 404);
    } finally {
      await closeServer(server);
    }
  });

  it("exposes truthful gateway state only for the explicit Playwright projection", async () => {
    const fixture = loadFixture("offline");
    const server = createFixtureServer(fixture, {
      includeFixtureGateway: true,
    });
    const port = await listenEphemeral(server);
    try {
      const gateway = await request(port, "GET", "/api/hermes/gateway");
      const sessions = await request(port, "GET", "/api/hermes/sessions");
      assert.equal(gateway.status, 200);
      assert.deepEqual(
        JSON.parse(gateway.body.toString("utf8")),
        {
          read_status: "unavailable",
          connected: false,
          model: "fixture-model",
          session_api_available: false,
          chat_write_ready: false,
          features: { session_resources: false },
          upstream_blockers: ["fixture_gateway_unavailable"],
          platform_delivery_blockers: ["fixture_write_disabled"],
          blockers: [
            "fixture_gateway_unavailable",
            "fixture_write_disabled",
          ],
          warnings: [],
        },
      );
      assert.equal(sessions.status, 404);
    } finally {
      await closeServer(server);
    }
  });

  it("serves a promoted factor catalog normally and a truthful registry outage when degraded", async () => {
    for (const [fixtureName, expectedStatus] of [
      ["normal", 200],
      ["degraded", 503],
    ]) {
      const fixture = loadFixture(fixtureName);
      const server = createFixtureServer(fixture);
      const port = await listenEphemeral(server);
      try {
        const response = await request(port, "GET", "/api/factors");
        assert.equal(response.status, expectedStatus, fixtureName);
        assert.equal(response.headers["cache-control"], "no-store");
        const body = JSON.parse(response.body.toString("utf8"));
        if (fixtureName === "normal") {
          assert.ok(
            body.factors.some(
              (factor) =>
                factor.factor_id === "agent_candidate_wave2_sceneb_mom20_v3" &&
                factor.origin === "promoted",
            ),
          );
        } else {
          assert.equal(body.detail, "fixture_factor_registry_unavailable");
          assert.equal(Object.hasOwn(body, "factors"), false);
        }
      } finally {
        await closeServer(server);
      }
    }
  });

  it("serves GET candidate detail synthesized from list rows (still no review POST)", async () => {
    const fixture = loadFixture("normal");
    const server = createFixtureServer(fixture);
    const port = await listenEphemeral(server);
    try {
      const id = fixture.candidates.candidates[0].candidate_id;
      const detail = await request(port, "GET", `/api/agent/candidates/${id}`);
      assert.equal(detail.status, 200);
      assert.equal(detail.headers["cache-control"], "no-store");
      const body = JSON.parse(detail.body.toString("utf8"));
      assert.equal(body.candidate_id, id);
      assert.equal(body.approval_enabled, true);
      assert.equal(body.integrity_state, "verified");
      assert.equal(body.manifest_digest, fixture.candidates.candidates[0].manifest_digest);
      assert.equal(body.status, "pending");

      const missing = await request(port, "GET", "/api/agent/candidates/no-such-id");
      assert.equal(missing.status, 404);

      const reviewPost = await request(
        port,
        "POST",
        `/api/agent/candidates/${id}/review`,
      );
      assert.equal(reviewPost.status, 405);
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

  it("rejects an oversized normal factor catalog at the fixture boundary", () => {
    const clone = structuredClone(loadFixture("normal"));
    const sample = clone.factors.body.factors[0];
    clone.factors.body.factors = Array.from({ length: 2_001 }, (_, index) => ({
      ...sample,
      factor_id: `fixture_factor_${index}`,
    }));

    assert.throws(
      () => validateCombinedFixture(clone),
      /normal factor catalog exceeds 2000 rows/,
    );
  });

  it("rejects a degraded factor fixture that masquerades as an empty catalog", () => {
    const clone = structuredClone(loadFixture("degraded"));
    clone.factors.body.factors = [];

    assert.throws(
      () => validateCombinedFixture(clone),
      /must not masquerade as a factor catalog/,
    );
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
