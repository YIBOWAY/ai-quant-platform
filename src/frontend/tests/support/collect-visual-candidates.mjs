import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const artifactRoot = path.resolve(frontend, "../../artifacts/full-e2e-2026-09-15");
const hash = file => createHash("sha256").update(fs.readFileSync(file)).digest("hex");
const files = root => fs.readdirSync(root, { withFileTypes: true }).flatMap(entry => entry.isDirectory() ? files(path.join(root, entry.name)) : [path.join(root, entry.name)]);
const rows = new Map();
const arguments_ = process.argv.slice(2);
const manifest = arguments_[0]?.startsWith("--manifest=") ? arguments_.shift().slice("--manifest=".length) : "visual-candidates-v2.json";
if (!/^visual-candidates-v\d+\.json$/.test(manifest)) throw new Error("Expected a versioned candidate manifest basename");
for (const run of arguments_) {
  if (!/^repair-20260915-[a-z-]+-\d+$/.test(run)) throw new Error("Expected one explicit owned run ID");
  for (const file of files(path.join(artifactRoot, run, "test-results"))) {
    const name = path.basename(file);
    const match = name.match(/^hermes-(normal|degraded|offline|empty|long-content)-(zh|en)-(wide|desktop|tablet|mobile)-(candidate|actual)\.png$/);
    const brief = /^brief-zh-(candidate|actual)\.png$/.test(name);
    if (!match && !brief) continue;
    const stem = name.replace(/-(candidate|actual)\.png$/, "");
    if (rows.has(stem) && name.endsWith("-actual.png")) continue;
    const viewport = match ? { wide: [1440, 900], desktop: [1280, 800], tablet: [768, 1024], mobile: [390, 844] }[match[3]] : [1440, 1000];
    const target = path.join(frontend, "tests/e2e", brief ? "visual.spec.ts-snapshots" : "hermes-workbench-visual.spec.ts-snapshots", `${stem}-chromium-darwin.png`);
    rows.set(stem, { mode: match?.[1] || "brief", locale: match?.[2] || "zh", viewport,
      source_run: run, path: file, sha256: hash(file), target, previous_sha256: fs.existsSync(target) ? hash(target) : null });
  }
}
const output = { generated_at: new Date().toISOString(), status: "awaiting_visual_review", candidates: [...rows.values()].sort((a, b) => a.target.localeCompare(b.target)) };
const destination = path.join(artifactRoot, manifest);
fs.writeFileSync(destination, JSON.stringify(output, null, 2));
console.log(JSON.stringify({ destination, count: output.candidates.length }));
