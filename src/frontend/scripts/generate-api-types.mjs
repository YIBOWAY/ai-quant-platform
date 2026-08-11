import { appendFileSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const frontendRoot = resolve(scriptDir, "..");
const repoRoot = resolve(frontendRoot, "../..");
const openapiPath = resolve(frontendRoot, ".tmp/openapi.json");
const outputPath = resolve(frontendRoot, "lib/api.generated.ts");
const uvCacheDir = resolve(repoRoot, ".tmp/uv-cache");
const uvProjectEnvironment = resolve(repoRoot, "ai-quant");

mkdirSync(dirname(openapiPath), { recursive: true });
mkdirSync(uvCacheDir, { recursive: true });
const uvEnv = {
  ...process.env,
  UV_CACHE_DIR: process.env.UV_CACHE_DIR ?? uvCacheDir,
  UV_PROJECT_ENVIRONMENT: process.env.UV_PROJECT_ENVIRONMENT ?? uvProjectEnvironment,
  PYTHONPATH: [resolve(repoRoot, "src"), process.env.PYTHONPATH]
    .filter(Boolean)
    .join(":"),
};
const schema = execFileSync(
  "uv",
  ["run", "--extra", "api", "python", "scripts/export_openapi.py"],
  { cwd: repoRoot, encoding: "utf-8", env: uvEnv },
);
writeFileSync(openapiPath, schema, "utf-8");
execFileSync(
  resolve(frontendRoot, "node_modules/.bin/openapi-typescript"),
  [openapiPath, "-o", outputPath],
  { cwd: frontendRoot, stdio: "inherit" },
);

const responseNames = Object.keys(JSON.parse(schema).components?.schemas ?? {})
  .filter((name) => name.endsWith("Response"))
  .sort();
if (responseNames.length > 0) {
  appendFileSync(
    outputPath,
    `\n${responseNames
      .map(
        (name) =>
          `export type ${name} = components["schemas"]["${name}"];`,
      )
      .join("\n")}\n`,
    "utf-8",
  );
}
