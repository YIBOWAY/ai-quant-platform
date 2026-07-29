#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  canonicalJson,
  collectRepositoryAuthority,
  frontendInstallEnvironment,
  installedEnvironmentTreeIdentity,
} from "./run-hermes-gate5.mjs";

const CONTRACT = "platform-frontend-fresh-install/v1";
const COMMIT_PATTERN = /^[0-9a-f]{40}$/;

function sha256Bytes(contents) {
  return crypto.createHash("sha256").update(contents).digest("hex");
}

function fileIdentity(filePath) {
  const canonical = path.resolve(filePath);
  const info = fs.lstatSync(canonical);
  if (
    info.isSymbolicLink() ||
    !info.isFile() ||
    info.nlink !== 1 ||
    (typeof process.getuid === "function" &&
      info.uid !== process.getuid()) ||
    (info.mode & 0o022) !== 0
  ) {
    throw new Error(
      `Frontend install authority input is unsafe: ${canonical}`,
    );
  }
  const contents = fs.readFileSync(canonical);
  return {
    mode: (info.mode & 0o777).toString(8).padStart(3, "0"),
    path: canonical,
    sha256: sha256Bytes(contents),
    size_bytes: contents.length,
  };
}

function executableIdentity(invokedPath) {
  const invoked = path.resolve(invokedPath);
  const invokedInfo = fs.lstatSync(invoked);
  if (
    (!invokedInfo.isFile() && !invokedInfo.isSymbolicLink()) ||
    (typeof process.getuid === "function" &&
      invokedInfo.uid !== process.getuid())
  ) {
    throw new Error(
      `Frontend install executable is unsafe: ${invoked}`,
    );
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
      `Frontend install executable target is unsafe: ${realpath}`,
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

function inputIdentity(frontendRoot) {
  return Object.fromEntries(
    [
      "package-lock.json",
      "package.json",
      "scripts/prepare-hermes-gate5-install.mjs",
      "scripts/run-hermes-gate5.mjs",
    ].map((relative) => {
      const identity = fileIdentity(
        path.join(frontendRoot, relative),
      );
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

function pathIsInside(parent, candidate) {
  const relative = path.relative(parent, candidate);
  return (
    relative !== "" &&
    relative !== ".." &&
    !relative.startsWith(`..${path.sep}`) &&
    !path.isAbsolute(relative)
  );
}

function prepareOutput(outputArgument, repoRoot) {
  if (!path.isAbsolute(outputArgument)) {
    throw new Error("Frontend install output must be absolute");
  }
  const output = path.resolve(outputArgument);
  if (pathIsInside(repoRoot, output)) {
    throw new Error(
      "Frontend install output must be outside the release checkout",
    );
  }
  const info = fs.lstatSync(output);
  const parentInfo = fs.lstatSync(path.dirname(output));
  if (
    info.isSymbolicLink() ||
    !info.isDirectory() ||
    parentInfo.isSymbolicLink() ||
    !parentInfo.isDirectory() ||
    fs.realpathSync(output) !== output ||
    (typeof process.getuid === "function" &&
      (info.uid !== process.getuid() ||
        parentInfo.uid !== process.getuid())) ||
    (info.mode & 0o077) !== 0 ||
    (parentInfo.mode & 0o077) !== 0 ||
    fs.readdirSync(output).length !== 0
  ) {
    throw new Error(
      "Frontend install output must be empty, canonical, and owner-only",
    );
  }
  return {
    output,
    record: {
      mode: (info.mode & 0o777).toString(8).padStart(3, "0"),
      owner_uid: info.uid,
      parent_mode: (parentInfo.mode & 0o777)
        .toString(8)
        .padStart(3, "0"),
      parent_owner_uid: parentInfo.uid,
      path: output,
    },
  };
}

function nodeModulesBeforeIdentity(frontendRoot) {
  const nodeModules = path.join(frontendRoot, "node_modules");
  let info;
  try {
    info = fs.lstatSync(nodeModules);
  } catch (error) {
    if (error?.code === "ENOENT") {
      return {
        exists: false,
        path: nodeModules,
      };
    }
    throw error;
  }
  if (
    info.isSymbolicLink() ||
    !info.isDirectory() ||
    (typeof process.getuid === "function" &&
      info.uid !== process.getuid()) ||
    (info.mode & 0o022) !== 0 ||
    fs.realpathSync(nodeModules) !== nodeModules
  ) {
    throw new Error(
      "Frontend install refuses an unsafe or cross-checkout node_modules",
    );
  }
  return {
    exists: true,
    mode: (info.mode & 0o777).toString(8).padStart(3, "0"),
    owner_uid: info.uid,
    path: nodeModules,
  };
}

function createTransientRuntime(output) {
  const root = path.join(output, ".frontend-install-runtime");
  fs.mkdirSync(root, { mode: 0o700 });
  fs.chmodSync(root, 0o700);
  const marker = path.join(root, "owner.json");
  fs.writeFileSync(
    marker,
    canonicalJson({
      root,
      schema_version: "platform-frontend-install-runtime.v1",
    }),
    {
      encoding: "utf8",
      flag: "wx",
      mode: 0o600,
    },
  );
  for (const name of ["cache", "home"]) {
    const child = path.join(root, name);
    fs.mkdirSync(child, { mode: 0o700 });
    fs.chmodSync(child, 0o700);
  }
  return {
    marker,
    root,
  };
}

function cleanupTransientRuntime(runtime) {
  const info = fs.lstatSync(runtime.root);
  const markerInfo = fs.lstatSync(runtime.marker);
  const expected = canonicalJson({
    root: runtime.root,
    schema_version: "platform-frontend-install-runtime.v1",
  });
  if (
    info.isSymbolicLink() ||
    !info.isDirectory() ||
    markerInfo.isSymbolicLink() ||
    !markerInfo.isFile() ||
    fs.readFileSync(runtime.marker, "utf8") !== expected
  ) {
    throw new Error(
      "Frontend install transient runtime ownership drifted",
    );
  }
  fs.rmSync(runtime.root, { recursive: true });
}

export function parseFrontendInstallArgs(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    let name;
    let value;
    for (const candidate of [
      "expected-commit",
      "npm-cli",
      "output-dir",
    ]) {
      if (token === `--${candidate}`) {
        name = candidate;
        value = argv[++index];
        break;
      }
      if (token.startsWith(`--${candidate}=`)) {
        name = candidate;
        value = token.slice(candidate.length + 3);
        break;
      }
    }
    if (name === undefined) {
      throw new Error(
        `Frontend install does not accept ${String(token)}`,
      );
    }
    if (
      typeof value !== "string" ||
      value.length === 0 ||
      value.startsWith("--") ||
      Object.hasOwn(values, name)
    ) {
      throw new Error(`Frontend install invalid --${name}`);
    }
    values[name] = value;
  }
  for (const name of [
    "expected-commit",
    "npm-cli",
    "output-dir",
  ]) {
    if (!Object.hasOwn(values, name)) {
      throw new Error(`Frontend install requires --${name}`);
    }
  }
  if (!COMMIT_PATTERN.test(values["expected-commit"])) {
    throw new Error(
      "Frontend install expected commit must be lowercase 40-hex",
    );
  }
  for (const name of ["npm-cli", "output-dir"]) {
    if (!path.isAbsolute(values[name])) {
      throw new Error(`Frontend install --${name} must be absolute`);
    }
  }
  return {
    expectedCommit: values["expected-commit"],
    npmCli: path.resolve(values["npm-cli"]),
    outputDir: path.resolve(values["output-dir"]),
  };
}

function runLogged({ argv, cwd, env, name, output }) {
  const startedAt = new Date().toISOString();
  const completed = spawnSync(argv[0], argv.slice(1), {
    cwd,
    encoding: null,
    env,
    maxBuffer: 64 * 1024 * 1024,
    timeout: 10 * 60 * 1000,
  });
  const stdout = Buffer.isBuffer(completed.stdout)
    ? completed.stdout
    : Buffer.alloc(0);
  const stderr = Buffer.isBuffer(completed.stderr)
    ? completed.stderr
    : Buffer.alloc(0);
  const artifacts = {};
  for (const [stream, contents] of [
    ["stdout", stdout],
    ["stderr", stderr],
  ]) {
    const artifactName = `${name}.${stream}.log`;
    const artifactPath = path.join(output, artifactName);
    fs.writeFileSync(artifactPath, contents, {
      flag: "wx",
      mode: 0o600,
    });
    artifacts[stream] = {
      path: artifactName,
      sha256: sha256Bytes(contents),
      size_bytes: contents.length,
    };
  }
  return {
    completed,
    record: {
      argv,
      completed_at: new Date().toISOString(),
      exit_code: completed.status,
      signal: completed.signal,
      started_at: startedAt,
      stderr: artifacts.stderr,
      stdout: artifacts.stdout,
    },
  };
}

export function runFrontendFreshInstall({
  expectedCommit,
  npmCli,
  outputDir,
}, dependencies = {}) {
  const collectInputs =
    dependencies.collectInputs ?? inputIdentity;
  const collectInstalledTree =
    dependencies.collectInstalledTree ??
    installedEnvironmentTreeIdentity;
  const collectRepository =
    dependencies.collectRepository ??
    collectRepositoryAuthority;
  const scriptPath = fileURLToPath(import.meta.url);
  const frontendRoot = path.dirname(path.dirname(scriptPath));
  const repoRoot = path.resolve(frontendRoot, "..", "..");
  const { output, record: evidenceDirectory } = prepareOutput(
    outputDir,
    repoRoot,
  );
  const nodeModulesBefore = nodeModulesBeforeIdentity(frontendRoot);
  const node = executableIdentity(process.execPath);
  const npm = executableIdentity(npmCli);
  const pathBin = path.dirname(node.realpath);
  const pathCommands = Object.fromEntries(
    ["node", "npm", "npx"].map((name) => [
      name,
      executableIdentity(path.join(pathBin, name)),
    ]),
  );
  const repositoryBefore = collectRepository(
    repoRoot,
    expectedCommit,
  );
  const inputsBefore = collectInputs(frontendRoot);
  const transientRuntime = createTransientRuntime(output);
  const environment = frontendInstallEnvironment(
    node,
    transientRuntime.root,
  );
  const receipt = {
    command: {
      argv: [process.execPath, scriptPath, ...process.argv.slice(2)],
      cwd: frontendRoot,
      environment_strategy: "allowlist",
      may_touch_database: false,
      may_touch_network_during_install: true,
      may_touch_provider: false,
      may_touch_runtime: false,
      may_touch_trading: false,
    },
    contract: CONTRACT,
    environment,
    evidence_directory: evidenceDirectory,
    inputs_before: inputsBefore,
    node: {
      ...node,
      version: process.version,
      versions: process.versions,
    },
    npm,
    node_modules_before: nodeModulesBefore,
    path_commands: pathCommands,
    repository_before: repositoryBefore,
    started_at: new Date().toISOString(),
    status: "running",
    transient_runtime: {
      cleanup_status: "running",
      root: transientRuntime.root,
    },
  };
  let error;
  try {
    const npmVersion = runLogged({
      argv: [node.realpath, npm.realpath, "--version"],
      cwd: frontendRoot,
      env: environment,
      name: "npm-version",
      output,
    });
    receipt.npm.version = npmVersion.record;
    if (npmVersion.completed.status !== 0) {
      throw new Error("npm version failed");
    }
    const install = runLogged({
      argv: [
        node.realpath,
        npm.realpath,
        "ci",
        "--no-audit",
        "--no-fund",
      ],
      cwd: frontendRoot,
      env: environment,
      name: "npm-ci",
      output,
    });
    receipt.install = install.record;
    if (install.completed.status !== 0) {
      throw new Error("npm ci failed");
    }
    receipt.installed_tree_after = collectInstalledTree(
      path.join(frontendRoot, "node_modules"),
    );
    receipt.inputs_after = collectInputs(frontendRoot);
    receipt.repository_after = collectRepository(
      repoRoot,
      expectedCommit,
    );
    if (
      canonicalJson(receipt.inputs_after) !==
        canonicalJson(inputsBefore) ||
      canonicalJson(receipt.repository_after) !==
        canonicalJson(repositoryBefore)
    ) {
      throw new Error(
        "Frontend install changed repository or source inputs",
      );
    }
    receipt.status = "passed";
  } catch (caught) {
    error = caught;
    receipt.status = "failed";
    receipt.error =
      caught instanceof Error ? caught.message : String(caught);
  } finally {
    try {
      cleanupTransientRuntime(transientRuntime);
      receipt.transient_runtime.cleanup_status = "removed";
    } catch (caught) {
      error =
        caught instanceof Error ? caught : new Error(String(caught));
      receipt.status = "failed";
      receipt.error = error.message;
      receipt.transient_runtime.cleanup_status = "failed";
    }
  }
  receipt.completed_at = new Date().toISOString();
  const receiptPath = path.join(
    output,
    "frontend-fresh-install-receipt.json",
  );
  fs.writeFileSync(receiptPath, canonicalJson(receipt), {
    encoding: "utf8",
    flag: "wx",
    mode: 0o600,
  });
  if (error !== undefined) {
    throw error;
  }
  return {
    receipt: receiptPath,
    status: "passed",
  };
}

const invokedPath =
  process.argv[1] === undefined
    ? ""
    : path.resolve(process.argv[1]);
if (invokedPath === fileURLToPath(import.meta.url)) {
  try {
    const result = runFrontendFreshInstall(
      parseFrontendInstallArgs(process.argv.slice(2)),
    );
    process.stdout.write(
      `FRONTEND_FRESH_INSTALL_PASS ${result.receipt}\n`,
    );
  } catch (error) {
    process.stderr.write(
      `frontend_fresh_install_error=${
        error instanceof Error ? error.message : String(error)
      }\n`,
    );
    process.exitCode = 1;
  }
}
