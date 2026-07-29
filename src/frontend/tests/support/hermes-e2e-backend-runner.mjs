#!/usr/bin/env node
import { spawn } from "node:child_process";
import crypto from "node:crypto";

import {
  buildE2ERunIdentity,
  cleanupE2ERunRoot,
  prepareE2ERunRoot,
} from "./hermes-e2e-run-root.mjs";

function readPayload(raw) {
  if (!raw) {
    throw new Error("encoded backend-runner payload is required");
  }
  let payload;
  try {
    payload = JSON.parse(Buffer.from(raw, "base64url").toString("utf8"));
  } catch (error) {
    throw new Error(
      `invalid backend-runner payload: ${
        error instanceof Error ? error.message : String(error)
      }`,
    );
  }
  if (
    payload === null ||
    typeof payload !== "object" ||
    Array.isArray(payload) ||
    typeof payload.command !== "string" ||
    payload.command.length === 0 ||
    !Array.isArray(payload.args) ||
    !payload.args.every((value) => typeof value === "string")
  ) {
    throw new Error("backend-runner payload has an invalid command");
  }
  return payload;
}

async function main(argv) {
  const payload = readPayload(argv[2]);
  const identity = buildE2ERunIdentity({
    baseRoot: payload.baseRoot,
    rawRunId: payload.runId,
    backendPort: payload.backendPort,
    frontendPort: payload.frontendPort,
    processId: process.pid,
  });
  const ownerToken = crypto.randomBytes(32).toString("hex");
  prepareE2ERunRoot(identity, {
    fixture: payload.fixture ?? null,
    ownerToken,
  });

  const publicProvenance = {
    backend_port: identity.backendPort,
    data_root: identity.dataRoot,
    fixture: payload.fixture ?? null,
    frontend_port: identity.frontendPort,
    run_id: identity.runId,
    schema_version: "hermes-playwright-run.v1",
  };
  process.stdout.write(
    `HERMES_E2E_RUN_ROOT_READY ${JSON.stringify(publicProvenance)}\n`,
  );

  let cleanupDone = false;
  const cleanup = () => {
    if (cleanupDone) return;
    cleanupE2ERunRoot(identity, {
      fixture: payload.fixture ?? null,
      ownerToken,
    });
    cleanupDone = true;
  };

  const child = spawn(payload.command, payload.args, {
    env: process.env,
    stdio: "inherit",
  });
  let forwardedShutdownSignal = null;
  const forwardSignal = (signal) => {
    forwardedShutdownSignal = signal;
    if (!child.killed) {
      child.kill(signal);
    }
  };
  const forwardSigint = () => forwardSignal("SIGINT");
  const forwardSigterm = () => forwardSignal("SIGTERM");
  process.on("SIGINT", forwardSigint);
  process.on("SIGTERM", forwardSigterm);

  let result;
  try {
    result = await new Promise((resolve, reject) => {
      child.once("error", reject);
      child.once("exit", (code, signal) => resolve({ code, signal }));
    });
  } finally {
    process.off("SIGINT", forwardSigint);
    process.off("SIGTERM", forwardSigterm);
    cleanup();
  }

  if (result.code !== null) {
    process.exitCode = result.code;
    return;
  }
  if (result.signal === forwardedShutdownSignal) {
    // Playwright intentionally terminated the supervised backend. Cleanup
    // already completed in finally, so this is a successful lifecycle end.
    return;
  }
  throw new Error(`backend child exited by signal ${result.signal ?? "unknown"}`);
}

main(process.argv).catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
