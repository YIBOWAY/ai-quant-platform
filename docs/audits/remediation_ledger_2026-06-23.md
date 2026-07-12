# 2026-06-23 Remediation Ledger

本台账把 2026-06-11 全项目评估报告从“历史诊断”转换为当前可执行的整改路线。它基于当前仓库 HEAD `197bc17`、`docs/` 现行文档、`.understand-anything/` code graph 资产，以及 2026-06-23 的人工裁决。

## User Decisions

- `.understand-anything/` 保留为项目资产，并可纳入版本控制；`.DS_Store` 仍属于本地系统产物，不应提交。
- 前端信息架构允许改名：`/replications` 可改为 `/strategies`，`/order-book` 可改为 `/polymarket`，但应保留兼容 redirect/alias。
- 前端 API 类型可以从 FastAPI OpenAPI schema 生成；优先采用“只生成类型，不一次性生成完整 client”的渐进方案。
- 前端继续双语，不执行中文单语化；后续 E2E 应尽量避免依赖脆弱文案定位。
- 本台账应落成文档，并作为后续整改包的当前执行入口。
- 后续每个整改包应按 coherent theme 提交并推送；阶段收口时运行 `neat-freak` 同步文档。

## Source Status

`project_assessment_2026-06-11.html` 仍然是重要的历史审计底稿，但不是实时待办清单。`docs/audits/README.md` 已说明审计目录中的文件属于历史背景资料，并记录了多项 2026-06-15/16 的后续修复状态。

当前执行应遵循 `docs/audits/remediation_goal_protocol.md`：每次只激活一个 bounded remediation package，优先级为结果可信度、安全边界、契约漂移、高频工作流、低频重构与视觉优化。

## Current Evidence Snapshot

| Area | Current evidence | Status |
|---|---|---|
| Code graph | `.understand-anything/meta.json` 记录 `analyzedFiles=581`、`gitCommitHash=197bc17...`；`knowledge-graph.json` 含 2614 nodes / 4727 edges | 保留为项目资产 |
| Worktree hygiene | 当前未跟踪顶层为 `.DS_Store`、`docs/.DS_Store`、`.understand-anything/`；可提交的 code graph 资产为 `.understandignore`、`config.json`、`meta.json`、`fingerprints.json`、`knowledge-graph.json`、`intermediate/scan-result.json` | `.DS_Store` 忽略或删除；核心 code graph 资产可提交 |
| E2E isolation | `src/frontend/playwright.config.ts` 已设置 test env、`QS_DATABASE_ENABLED=false`、sandbox data dir | 已完成 |
| Port standardization | Frontend dev 固定 `127.0.0.1:3001`；backend default `8765` | 已完成 |
| Futu env aliases | `FutuSettings` 使用 `AliasChoices` 接受 `QS_FUTU_*` 与 legacy `QS_*` | 已完成 |
| Tiingo adjusted prices | Tiingo provider 优先 adjusted OHLCV；cache coverage 要求合法 `price_adjustment` label | 部分完成，需真实拆股/分红验证 |
| API contracts | FastAPI JSON 200 responses are `$ref`-backed; `/api/backtests/run` additionally advertises `202 BacktestJobStateResponse` for async mode | Done |
| Frontend API types | `src/frontend/lib/api.generated.ts` is generated from FastAPI OpenAPI; `lib/api.ts` keeps hand-written helpers plus selected response aliases | Initial generation contract established |
| Run storage | Shared `persist_run` writes atomic `metadata.json` for backtest/factor/paper/replication; Postgres run index is an optional mirror, filesystem remains truth | Done |
| UI IA | `/strategies` and `/polymarket` are canonical; compatibility redirects/aliases preserve old `/replications` and `/order-book` paths | Done |

## Ledger

### Phase 0 Quick Wins

| # | Item | Current status | Next action |
|---|---|---|---|
| 1 | 提交工作树 / 保护 168 项未提交变更 | 旧风险已过期；tracked worktree 干净，仅有 `.DS_Store` 与 `.understand-anything/` | 提交 code graph 资产；忽略/删除 `.DS_Store` |
| 2 | E2E 防污染 | Done | 保持隔离设置与测试 |
| 3 | 端口统一为 8765 + 3001 | Done | 保持 README/scripts/playwright 一致 |
| 4 | Futu 下单脚本红线 | Done | 保持全仓库和 `.agents` 红线测试 |
| 5 | `QS_FUTU_*` alias | Done | 无 |
| 6 | per-run DuckDB 跳写 + 清理脚本 | Done | 清理历史数据仍应由 operator 显式执行 |
| 7 | Futu options cache 过期清扫 | Done | 按需运行 prune CLI |
| 8 | 显式 provider 失败返回 400 | Done | 新 provider 家族复用同一模式 |
| 9 | benchmark source badge | Done | 无 |
| 10 | verify 脚本 + Python 指引 | Done | 无 |
| 11 | backend rotating JSONL logs | Done | 无 |
| 12 | `environment.yml` API extra | Done | 无 |
| 13 | options radar scheduler scripts | Done | 无 |
| 14 | Sidebar sole navigation authority | Partially done | 决定 TopBar mobile/settings/agent 快捷入口是否为允许例外 |
| 15 | paper account backup/recovery | Done | 无 |
| 16 | frontend template cleanup + data lifecycle docs | Partially done | 记录当前 data layout，或明确替代原五区模型 |

### Remediation Package A: Result Credibility Baseline

Package A status: guarded for fixture-based and local-storage evidence; live market validation is delivered as a reproducible operator/external gate (`scripts/verify_tiingo_adjustment.py`).

Purpose: 把结果可信度相关的 Tiingo adjusted-price 风险从“critical candidate”转为有机器证据的状态。

Current evidence:

- Tiingo adjusted/raw/mixed fixtures are covered by `tests/test_data_tiingo_provider.py`.
- LocalDataStorage preserves `price_adjustment` through Parquet and DuckDB.
- Cached Tiingo reads reject legacy cache rows with missing or invalid `price_adjustment` labels.
- Live split/dividend validation remains an external/manual gate because it requires a real Tiingo token and market-data network access.
- `scripts/verify_tiingo_adjustment.py` makes that gate reproducible: with a real token it asserts a known split window is `adjusted` and free of a split-sized discontinuity; without a token it skips. `tests/test_verify_tiingo_adjustment_script.py` guards its offline logic.

In scope:

- 复核 Tiingo adjusted/raw/mixed OHLCV 行为与 `price_adjustment` 标签。
- 确认 provider normalization/cache persistence 不会丢掉 `price_adjustment`。
- 做一次可复现的拆股/分红窗口验证方案；如无真实 token，则标记为 manual/external gate。
- 更新审计状态，避免继续把已加测试的 adjusted-price 风险当作未处理 critical。

Out of scope:

- 历史缓存迁移。
- ArtifactStore 重构。
- Job runner / cancellation / progress。
- Futu、options pricing 或前端 redesign。

Acceptance:

- Tiingo raw/adjusted/mixed fixtures 测试通过。
- 至少一个 storage/cache/schema 路径证明 `price_adjustment` 未被丢弃。
- 文档明确该风险当前是 guarded、partially guarded 还是 still open。
- 相关 pytest、ruff、`git diff --check` 通过。

### Remediation Package B: Contract Drift Baseline

Package B status: generation contract established; generated types refreshed
against the current OpenAPI schema on 2026-07-10.

Purpose: 收敛后端 OpenAPI schema 与前端 TypeScript 类型之间的漂移。

Current evidence:

- `src/frontend/lib/api.generated.ts` is generated from FastAPI OpenAPI schema.
- `src/frontend/scripts/generate-api-types.mjs` exports the local FastAPI OpenAPI schema and runs `openapi-typescript`.
- FileResponse artifact download routes are explicit OpenAPI response-model exemptions.
- Existing `apiGet` / `apiPost` client behavior remains hand-maintained.
- The generated contract includes the archived-brief and paper-account snapshot /
  reconciliation schemas and routes; focused tests guard those current seams.

In scope:

- 明确 FileResponse artifact download route 的 OpenAPI response-model 豁免。
- 引入 `openapi-typescript` 生成 `src/frontend/lib/api.generated.ts`。
- 保留现有 `apiGet` / `apiPost` client，不一次性改成生成 client。
- 将 `src/frontend/lib/api.ts` 逐步改为生成类型 alias/re-export 与少量手写 helper 类型。
- 增加生成结果一致性检查脚本或测试。

Out of scope:

- 一次性重写所有 API 调用。
- 删除全部手写类型。
- UI redesign。

Acceptance:

- OpenAPI schema 可在本地生成。
- 生成文件稳定进入前端 type-check。
- 现有前端 lint/type/test 通过。
- 文档记录生成命令、文件所有权和豁免规则。

### Remediation Package C: Shared Trading Kernel

Package C status: completed; shared pure trading-kernel rules are used by backtest and paper adapters with byte-stability coverage.

Purpose: 消除 backtest 与 paper replay/order accounting 之间的规则漂移，同时保持 paper-only 安全边界。

In scope:

- 提炼目标权重到订单生成、fill、accounting 的共享纯规则层。
- backtest 与 paper replay 只做薄适配。
- 保留 no-live-trading、no broker mutating call、安全红线测试。

Out of scope:

- 实盘交易、Futu trade context、账户解锁、钱包、签名。
- 前端 IA redesign。
- ArtifactStore 大改，除非共享内核测试必须最小触碰。

### Remediation Package D: Run Artifact Store

Package D status: completed; backtest/factor/paper/replication metadata flows through shared atomic run persistence and optional index mirroring.

Purpose: 把 backtest / paper / factor / experiment / replication 的运行产物收敛到统一 artifact/run repository 抽象。

In scope:

- 统一 run kind / directory / metadata schema。
- 决定 replication 是否进入 `KIND_DIRS` 与 `/api/runs/recent`。
- 明确 Postgres 只是可选 mirror，文件系统仍是真相。

Out of scope:

- 异步 job runner。
- 大规模历史数据迁移。

### Remediation Package E: IA And Route Rename

Package E status: completed; `/strategies` and `/polymarket` are canonical while compatibility redirects preserve old paths.

Purpose: 降低页面命名、URL 与内容错位带来的认知成本。

In scope:

- `/replications` -> `/strategies`，保留 redirect/alias。
- `/order-book` -> `/polymarket`，保留 redirect/alias。
- docs、Sidebar、E2E 同步。
- 继续双语 UI。

Out of scope:

- 彻底重做视觉系统。
- 一次性合并所有 options 页面，除非另立 UI package 并使用 frontend/web design skill。

### Remediation Package F: Async Backtest Jobs

Package F status: completed; async mode is opt-in via `QS_BACKTEST_JOBS_ENABLED`, with synchronous default preserved.

Purpose: 让长回测从同步 HTTP 请求变成可轮询、可取消、可恢复的本地 job。

Current evidence:

- `BacktestJobRunner` uses a bounded local `ThreadPoolExecutor` and atomic `metadata.json` transitions (`queued` / `running` / `cancelling` / `cancelled` / `completed` / `failed`).
- `POST /api/backtests/run` still returns `200 BacktestRunResponse` by default; when async jobs are enabled it returns `202 BacktestJobStateResponse` with `poll_url` / `result_url`.
- `GET /api/backtests/jobs/{run_id}` polls state; `POST /api/backtests/jobs/{run_id}/cancel` cancels queued jobs and cooperatively cancels running jobs between pipeline stages.
- API startup marks orphaned queued/running/cancelling jobs as failed because local jobs are not distributed or resumable.
- Frontend Backtester and Strategy Catalog poll async backtest jobs before navigating to detail pages.

In scope:

- `POST /backtests/run` 或新增 endpoint 立即返回 `run_id` / job state。
- 状态轮询、取消、失败恢复。
- artifact 状态转换必须原子或可恢复。

Out of scope:

- 引入重型队列系统，除非轻量本地 job runner 不足。
- 分布式执行。

## Continue Gate

所有 packages A-F 已完成实现；后续进入收口验证、文档同步、commit/push 与回归维护。进入新 remediation package 前必须重新定义 L2 contract，并在结束时验证：

1. 机器验证通过。
2. 相关文档已同步。
3. 已按 coherent theme 提交并推送。
4. worktree 没有该 package 的遗留改动。
5. 下一个 package 不需要新的产品/安全裁决。

## Commit And Push Policy

用户已授权每完成一个合适粒度的内容进行 GitHub commit 与远程 push。默认粒度：一个 remediation package 一个 commit；大型 package 最多拆 2-3 个 coherent theme commits。不得提交 `.DS_Store` 或 unrelated dirty files。
