import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { E2E_MODES } from "./e2e-selection.mjs";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const base = path.resolve(frontend, "../../artifacts/full-e2e-2026-09-15");
function cases(suite) {
  const result = [];
  for (const spec of suite.specs || []) for (const test of spec.tests || []) {
    const last = test.results?.at(-1);
    result.push({ id: `${spec.file}:${spec.title}`, file: spec.file, title: spec.title, status: last?.status,
      expected_status: test.expectedStatus, annotations: test.annotations || [], repeat: test.repeatEachIndex || 0 });
  }
  for (const child of suite.suites || []) result.push(...cases(child));
  return result;
}
const runs = process.argv.slice(2).map(id => {
  const match = id.match(/^repair-20260915-([a-z-]+)-\d+$/);
  if (!match || !E2E_MODES.includes(match[1])) throw new Error(`Invalid run: ${id}`);
  const report = JSON.parse(fs.readFileSync(path.join(base, id, "results.json"), "utf8"));
  const summary = JSON.parse(fs.readFileSync(path.join(base, id, "run-summary.json"), "utf8"));
  return { id, mode: match[1], ...summary, cases: cases(report), metadata: report.config?.metadata };
});
if (new Set(runs.map(row => row.mode)).size !== 10 || runs.length !== 10) throw new Error("Final report requires each of the ten modes exactly once");
const normal = runs.find(row => row.mode === "normal");
const normalPassed = new Set(normal.cases.filter(row => row.status === "passed").map(row => row.id));
const skipped = new Map();
for (const run of runs) for (const test of run.cases.filter(row => row.status === "skipped")) {
  const reason = test.annotations.filter(row => row.type === "skip").map(row => row.description).filter(Boolean).join("; ");
  if (!reason || !normalPassed.has(test.id)) throw new Error(`Unexplained or uncovered skipped case: ${test.id}`);
  const previous = skipped.get(test.id) || { file: test.file, title: test.title, reason, skipped_modes: [], covered_in: normal.id };
  previous.skipped_modes.push(run.mode); skipped.set(test.id, previous);
}
const totals = runs.reduce((total, run) => ({ passed: total.passed + run.stats.expected, failed: total.failed + run.stats.unexpected,
  skipped: total.skipped + run.stats.skipped, flaky: total.flaky + run.stats.flaky }), { passed: 0, failed: 0, skipped: 0, flaky: 0 });
const selectedVariants = new Set(runs.flatMap(run => run.cases.map(test => `${run.mode}:${test.id}`))).size;
const output = { generated_at: new Date().toISOString(), verdict: totals.failed === 0 && totals.flaky === 0 && runs.every(row => row.exitCode === 0) ? "PASS" : "FAIL",
  totals, selected_variants: selectedVariants,
  modes: runs.map(({ cases: allCases, ...run }) => ({ ...run, case_instances: allCases.length })),
  skipped_unique_cases: [...skipped.values()],
  excluded: [
    { title: "@live-hermes-sessions reads real persisted sessions without opening chat writes", reason: "Real Hermes session access is excluded from the hermetic matrix." },
    { title: "@live-hermes-sessions keeps session context pinned while reading the latest messages", reason: "Real Hermes session access is excluded from the hermetic matrix." },
  ],
  boundaries: ["No real Grok/model/provider calls or natural intake/fills are certified.", "Main real mode uses isolated FastAPI, test data and explicit UI seam fixtures; lifecycle is a Node protocol fixture.", "Brief runs on a fresh real backend; production prefetch runs Next build/start on the isolated copy.", "No formal 3001/8765/11111, external network, live trading, formal database or manual paper cycle is used."],
};
fs.writeFileSync(path.join(base, "e2e-final-matrix.json"), JSON.stringify(output, null, 2));
const lines = ["# 2026-09-15 最终浏览器 E2E", "", `结论：**${output.verdict}**。实际执行 ${totals.passed + totals.failed} 次，${totals.passed} 通过、${totals.failed} 失败；另 ${totals.skipped} 次为场景适用性跳过。`,
  `合计 ${selectedVariants} 个模式/用例组合；生产导航为同一用例重复执行，实例数见表。不是这么多个独立业务功能。`, "", "| 模式 | 通过 | 失败 | 跳过 | 运行记录 |", "| --- | ---: | ---: | ---: | --- |",
  ...runs.map(run => `| ${run.mode} | ${run.stats.expected} | ${run.stats.unexpected} | ${run.stats.skipped} | [${run.id}](${run.id}/run-summary.json) |`), "", "## 跳过的唯一用例与覆盖去向", "",
  ...[...skipped.values()].map(row => `- ${row.title}：在 ${row.skipped_modes.join(" / ")} 不适用；${row.covered_in} 已执行通过。原因：${row.reason}`), "", "## 不在本次执行范围", "",
  ...output.excluded.map(row => `- ${row.title}：${row.reason}`),
  "- 实际上游权限、真实 Grok 自然投递、自然成交与长期收益不能由本轮测试替代。", "- 正式账户/数据库、真实模型及正式服务端口全部排除。", "",
  "## 证据解释", "", "- 25 张基线经根代理逐张或相同哈希复核后按精确 SHA 采纳，未降低像素/对比度/触控阈值。采纳记录见 visual-accepted-v3.json。",
  "- RSC 验收等待目标内容、API 记录数量以及导航请求真正结束；URL 变化或已触发过的 networkidle 不是完成证明。最终没有放宽 ERR_ABORTED 断言。",
  "- 早先失败、探针运行和误选 297 项后主动中止的 12126 批均保留，不混入本表通过率。",
  "- 前端复制指纹 e321f8a 与 84cf2ea 的差异已在内存替换复算，唯一差异是 v022UiHardening.test.ts 对旧负 margin 断言的修正；产品代码相同。", "",
  "完整机器可读结果、每批命令、trace、截图与跳过原因见 e2e-final-matrix.json 及对应运行目录。", ""];
fs.writeFileSync(path.join(base, "FINAL-E2E.md"), lines.join("\n"));
console.log(JSON.stringify({ verdict: output.verdict, totals, selectedVariants, uniqueSkipped: skipped.size }));
