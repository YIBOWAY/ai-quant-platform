import { execFileSync } from "node:child_process";
import {
  existsSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const frontendRoot = process.cwd();

describe("E2E frontend workspace preparer", () => {
  it("refreshes a stale copy without mutating guarded source files", () => {
    const port = 50_000 + (process.pid % 10_000);
    const workspace = path.join(
      frontendRoot,
      ".tmp",
      `e2e-frontend-${port}`,
    );
    const script = path.join(
      frontendRoot,
      "scripts",
      "prepare-e2e-workspace.mjs",
    );
    const guardedSources = ["next-env.d.ts", "tsconfig.json"];
    const before = new Map(
      guardedSources.map((relativePath) => [
        relativePath,
        readFileSync(path.join(frontendRoot, relativePath)),
      ]),
    );

    try {
      rmSync(workspace, { force: true, recursive: true });
      execFileSync(process.execPath, [script, String(port)], {
        cwd: frontendRoot,
        stdio: "pipe",
      });
      expect(existsSync(path.join(workspace, "node_modules"))).toBe(true);
      expect(existsSync(path.join(workspace, ".source-fingerprint"))).toBe(
        true,
      );

      writeFileSync(path.join(workspace, "next.config.ts"), "stale", "utf8");
      writeFileSync(
        path.join(workspace, ".source-fingerprint"),
        "stale",
        "utf8",
      );
      execFileSync(process.execPath, [script, String(port)], {
        cwd: frontendRoot,
        stdio: "pipe",
      });

      expect(readFileSync(path.join(workspace, "next.config.ts"))).toEqual(
        readFileSync(path.join(frontendRoot, "next.config.ts")),
      );
      for (const [relativePath, expected] of before) {
        expect(readFileSync(path.join(frontendRoot, relativePath))).toEqual(
          expected,
        );
      }
    } finally {
      rmSync(workspace, { force: true, recursive: true });
    }
  });
});
