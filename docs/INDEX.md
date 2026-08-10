# 文档索引

这是整个仓库的主地图。先用下面的“当前工作”确定执行入口，再按需查架构、操作
指南和历史交付。不要从旧 phase、audit 或未勾选 checkbox 推断当前进度。

## 当前工作（2026-08-10）

| 层级 | 权威入口 | 状态 |
|---|---|---|
| 跨仓产品路线 | `/Users/sunyibo/programs/Hermes-quant-agent/docs/design/2026-07-01-roadmap-phases-0b-4.md` | Hermes 是 COO/编排层；本仓库是领域后端。 |
| 已交付跨仓计划 | `/Users/sunyibo/programs/Hermes-quant-agent/docs/superpowers/plans/2026-07-10-phase-1a-4-v2.md` | Slice 9A-9G + mini 9H 已完成。 |
| 已交付完整 9H | `/Users/sunyibo/programs/Hermes-quant-agent/docs/superpowers/plans/2026-07-12-full-9h-automation-notifications.md` | 调度、对账、周报、freshness 与通知已完成；平台只负责只读消费。 |
| 已交付候选完整性 / Gate 3 | `/Users/sunyibo/programs/Hermes-quant-agent/docs/superpowers/plans/2026-07-13-candidate-integrity-and-gate3.md` | 统一 repo-anchored candidate root、immutable manifest、HQA Scene-B Gate 1 精确源绑定、Gate 2 digest CAS、迁移工具、隔离且可恢复的 Gate 3 worktree 已交付并完成对抗性加固。Scene-B 已完成 final receipt → prepare → 人工 diff/commit → reviewed → cleanup，并以 `524e791` 合入当前分支（见下）。 |
| 已交付专业前端 / 只读壳 | `/Users/sunyibo/programs/Hermes-quant-agent/docs/superpowers/plans/2026-07-13-hermes-professional-frontend-shell.md` | F0 direction-a + F1 书面批准后，F2 Hermes 壳与可回滚默认首页已交付。Approvals 保持证据只读（`approvalMutations=false`）；official Hermes API 会话读取已接入（`sessionRead=true`）。3E-A 又交付只读 Unified Results 目录/详情，但完整切流仍关闭。设计记录见 [design/hermes-workbench/README.md](design/hermes-workbench/README.md)。 |
| 唯一运维权威 | [Agent v0.2 local-stack](runbooks/agent-v0-2-local-stack.md) | 唯一维护 migration、backup、isolated replay、readiness、restart、candidate E2E 与 pre-028 restore 的文档；其他 runbook 只解释组件。 |
| Platform 单一 main | [2026-08-10 Git 分支合并审计](audits/2026-08-10-platform-git-branch-consolidation.md) | 两个 Platform checkout 与 GitHub 已统一到受保护 `main`；旧分支先按 exact tip 建 archive tag 后删除，bundle/dirty snapshot 可恢复。此拓扑收口不授权 live、因子晋级或 migration 029。 |
| D-33 自动 paper | `/Users/sunyibo/programs/Hermes-quant-agent/docs/plans/2026-08-10-full-automation-paper-path.md` 与 `docs/runbooks/full-automation-paper.md` | 双-Flag、真实 intake/final evidence、机器 Gate、`paper_only`、本地 ff-only land、029 配额、限额 sleeve 与五分钟常驻 paper 周期；不 auto-push，live 永远人工。 |
| 029 operator window | 2026-08-10 现场执行 | backup + isolated restore rehearsal 后一次 apply；append-only promote/demote/daily quota authority。禁止重放；启动永不自动迁移。 |
| 应用前历史快照 | source/change set 016–028；live 现场只读核对 2026-07-31 | inspected 016–027 markers 存在；当时 028 marker 不存在，运行后端尚无 `/api/safety/effective`。这是保留的 pre-apply 快照，不描述当前 live 状态。 |
| 028 operator window | 2026-08-01 现场观察；详见 [Agent v0.2 local-stack](runbooks/agent-v0-2-local-stack.md) | 028 marker=1/version=1，exact two binding triggers 均为 `ENABLE ALWAYS`，schema fingerprint `e3f713ac05a1a990cfa9be45157e880e06709c425a4883736544d8f2b626f33a`；一次性 apply 后的正常重启、readiness 与 `/api/safety/effective` 通过。该快照不证明论文研究语义，也不授权重放 028。 |
| AlphaZeroBeta 重测 | `/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/Hermes-quant-agent/docs/audits/2026-07-31-alphazerobeta-paper-research-web-e2e.md` | Web/UI、Session、dispatch、provider、approval、durable Run、直接 PDF/全文读取与数据库持久化等机械生命周期通过，zero orders；但论文研究 verdict 为 **UNVERIFIED / NOT ACCEPTED**。Skill-only 约束没有形成 runtime-enforced、digest-bound `hqa.paper_intake/v1` receipt/verifier，因此 factor/backtest/Gate/result 为 **NOT EVALUATED**，不能写成正确跳过。正式候选套件 `5632 passed / 272 skipped / 0 failed`，manifest SHA-256=`eba8099bf3801927f3d93b40d1e133546d7cbcc4eece4c58b416bf52bd29a136`；candidate 已 revoke，connector=`reconcile_only`，local/public write 均关闭。 |
| 当前实现选择 | Agent v0.2 local-private managed-session write | owner session/CSRF + encrypted payload + durable connector + transcript/follow/approval/stop/result。CLI 默认 `reconcile_only`；`supervised_dispatch` 只在 exact candidate/release window。历史/外部 session 只读，继续上下文需显式 fork。local `chat_write_ready` ≠ public；public standing OFF，交易 kill switch true。 |
| 本机 Hermes 连接决策 | `/Users/sunyibo/programs/Hermes-quant-agent/docs/design/2026-07-15-local-hermes-integration-decision.md` | 采用 PostgreSQL durable command/event/outbox + deterministic worker；`LISTEN/NOTIFY` 唤醒、periodic scan 兜底，不让 Hermes/LLM cron 空轮询。 |
| 前序实现记录 | [前端渐进改造与 Hermes 集成](superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md) | Slice 0-8 与后续前端 backlog 的事实记录；不是当前可直接续写的 task list。 |
| 被替代计划 | HQA `2026-07-07-phase-1a-4-research-employees.md` | 目标保留，旧 implementation 模板不得原样执行。 |
| 历史路线 | [Phase 15 素材档案](phases/phase_15_iteration_roadmap.md) | 仅作素材，不是独立 roadmap。 |

下面一段保留 2026-07-11 的历史交付快照，不描述当前 live 配置。前序计划已把
`/brief`、PostgreSQL 业务事实、paper account 存储迁移、`/hermes`
只读骨架和渐进前端重设计放在同一条 expand-contract 路线上。当时已将 8765
重启到最终 9D 工作树：live `quantplatform` 的四份 migration 共 14 张表全部存在，其中
003/004 是 11 张业务表；health、brief archive、paper API reconciliation 和关键页面
smoke 均通过。该快照的 paper
mode 刻意保持默认 `file`；canonical 当时只是已验收能力。随后
Slice 9A 已把 sleeve list/detail/status 与 crash recovery 分缝：GET/`ops-status` 不写盘，
`paper strategies recover-pending` 才显式恢复。Slice 9B 已让 API、CLI 与 HQA 共用
统一 paper snapshot read-model；该快照仍保持 `file` mode。HQA Slice 9C 已只读消费
该 snapshot，产出当前敞口/集中度 artifact。Slice 9D 新增严格只读 `data prices` JSON
seam：仅 Futu/QFQ/1d，限制 25 个标的与 500 个含首尾日历日期，不允许
sample/local/Tiingo/Longbridge fallback。HQA v2 以 previous UTC date 为 `end`、
`end-400 days` 为 `start`，先做全局日期 inner join 再算收益，最少要求 60 个对齐收益；输出逐仓相对
SPY 的 beta 与持仓两两 correlation，不计算 aggregate beta、VaR 或阈值 verdict。
2026-07-11 真实验收使用 274 个对齐收益，AAPL beta 为 `0.8576599678`；平台全量
`1027 passed, 15 skipped`，20 个受观察状态/缓存文件的 bytes、mtime、hash 均未变化。
HQA Slice 9E 已复用该 seam，真实临时 prediction ledger smoke 与到期评分通过。Slice
9F 已发布严格 Futu/QFQ 证据支持、proposal-only 的 market-foresight 候选；mini 9H
通过 `GET /api/hermes/artifacts` 和真实 `/hermes` 卡片展示组合风险、预测状态和推演产物，
其交付时 Composer 仍禁用；现行 local-private composer 以本页 current row 与
local-stack 为准。Slice 9G 新增 HQA 本地 opportunity ledger，并通过平台 CLI-only
`paper strategies observations` 读取精确 signal/execution facts；平台没有新增机会账本
数据库、HTTP route 或 UI。真实 59 条 options 信号因无 paper-options route 均为
`not_actionable`，零虚假 missed。完整 9H 随后在 HQA 完成调度、prediction/opportunity
对账、周报聚合、job freshness 与通知投递。平台现在兼容 feed schema 1.0 的精确三来源
合同和 schema 1.1 的精确六来源合同；`/hermes` 展示风险、预测、推演、周报、机会与
自动化状态，whole-feed freshness budget 为 10800 秒。完整 9H 本身没有为平台新增
scheduler、outbound worker、POST route 或数据库 migration。

### 候选完整性与 Gate 3（2026-07-13 代码交付）

- 唯一 canonical candidate root 由 `resolve_agent_output_dir()` 决定：默认
  仓库锚定绝对路径 `<repo>/data/agent_run`，候选目录为
  `<repo>/data/agent_run/agent/candidates`。仅 `QS_AGENT_OUTPUT_DIR`（或显式
  injectable/CLI agent-output root）可改写；进程 CWD 与 `QS_DATA_DIR` 不迁移
  候选池。API/CLI/one-shot loader/migration/promotion 共用同一 resolver。
- 读路径互斥完整性状态：`verified` / `migration_required` / `corrupt`。
  `legacy_unbound` 无执行/批准/晋级权威。
- Gate 2：显式 `expected_manifest_digest` + `expected_status=pending` CAS；
  终态决策不可翻转。
- HQA Scene-B Gate 1：人类确认 exact source SHA-256 + note 后，HQA 才持久化
  confirmation 与 exact candidate/manifest binding；缺 binding 时 HQA list/detail 不提供
  approve command，approve 也拒绝。平台 external source 以二进制读取并原样落入
  candidate，JSON receipt 返回 verified `source_sha256` 供 HQA 强制匹配；raw
  `list-candidates` 不再输出审批命令，raw review 仅是 Gate 2 primitive。
- Gate 3：`agent promote-candidate` 需要 `--candidate-id`、`--expected-digest`、
  `--base-commit`；stdout 仅
  `{promotion_id, worktree, patch, manifest}`。status/cleanup 只认
  `--promotion-id`；破坏性 cleanup 需已审查 commit 证据或显式 `--abandon`。
  仅在隔离 managed review worktree 物化 scoped patch，永不自动 commit。active prepare 的
  `promotion-status` 会安全重读 patch，复核 manifest digest、actual 三文件 bytes/mode、
  exact dirty set 和实际 Git diff，并返回 manifest/patch/candidate/base/path provenance；
  patch 或工作区在 prepare 与 status 之间漂移会 fail closed。
- Scene-B 最终回测证据只接受 Futu/Tiingo。每次 experiment 使用微秒时间戳 + 12-hex
  随机量生成 ID，并原子预留 experiment/report 双目录；碰撞会重试，既有实验永不覆盖。
  HQA 将 persisted config、agent summary 和完整生成报告绑定到该唯一 namespace。
- 真实 legacy/canonical migration 命令默认 dry-run。Wave 2 已单独授权并执行一次
  `--apply`：`factor-momentum_20d_reversal-323b045e4b` 现为
  `integrity_state=verified`、`approval_enabled=True`，digest
  `294bbe7b846ae86384e56deae8ba8df2576ac6ffa8a5937e4f82a2352fdd8558`。后续新
  migration 冲突仍需单独授权 `--apply` + `--backup-dir`。
- Scene-B 的真实 candidate
  `factor-wave2_scene_b_smoke_v3_loadable_factor-da01df1188` 已绑定 digest
  `5ca064d597778b45f1a718047becf5b67b30cf9b24d441632b3a408cfd1c227d` 与 final
  receipt `backtest-f4da78d66b4ee6eaab6e7226740ac6ac`。Gate 3 promotion
  `promo-b7bbab8cf571a5f4ff43aa652aebf3bc` 经人工审查提交为
  `524e791e5e3e22cec12a4166ad8fc3617c735566`，状态 `reviewed` 后已 cleanup；
  `agent_candidate_wave2_sceneb_mom20_v3` 已进入 promoted registry。
- Hermes Approvals：早期 `8052fe6` 的浏览器 Gate 2 mutation 控件已回退。当前页面仅展示
  候选证据，`approvalMutations=false`；浏览器不能 re-fetch/代填 digest，也不能 POST
  review。这维持 HQA Scene-B Gate 1 精确绑定和人类 Gate 2 CAS 的权威入口，
  migration/corrupt 候选同样只读。

### Hermes 专业前端 / Wave 3 历史交付快照（2026-07-15）

本节保留当时的交付边界，不是当前 runtime 或运维状态。现行状态见顶部 current
rows；操作只看 [local-stack runbook](runbooks/agent-v0-2-local-stack.md)。

- F0：用户书面批准 `direction-a`（COO full-width trading desk）；craft 路径经 finance-crypto 重设计后与 QUANTUM_CORE 调色板对齐。
- F1：用户书面批准可点击全状态原型（含 token rebind）。
- F2 生产壳：单一全局 `SafetyStrip`；Today 以行动/异常/结论为先并压缩健康自动化；
  交付当时 `chat` / `execution` / `approvalMutations` /
  `legacyRedirects` 为 false，`sessionRead=true` 只开放已保存会话的观察面。Unified
  Results 只读 preview/catalog 可见，但完整切流门
  `unifiedResultsCutoverAccepted=false`。
- Wave 2 Approvals：页面恢复为证据只读，不提交平台 `POST .../review`。
- Wave 2 Tasks：浏览器页面只读绑定 automation / weekly_review / opportunity_summary 证据，
  **无** research task create/submit 控件；这不否认 3C.1 已代码交付的 HQA 内部
  Task/Attempt/payload authority。
- Wave 3 3E-A Results：`/hermes/results` 与 `/hermes/results/{kind}/{resource_id}`
  只读汇总平台 runs/experiments/candidates、HQA manifest 产物与 exact run links；
  缺失、损坏、降级和未知总数都显式呈现，绝不从名称/标的相似性推断 Hermes Run。
- Hermes sessions：平台后端以 server-side、固定 allowlist、GET-only adapter 连接 official
  Hermes API Server `http://127.0.0.1:8642`，BFF 提供 gateway 状态、session list/detail/
  messages；前端 `/hermes/sessions` 与会话详情只读取本地持久会话。Hermes Bearer key
  只从 owner-only key file 读取，绝不下发浏览器。health/capabilities/session reads 不执行
  prompt、不调用 provider，也不消耗 Hermes 所配置 Codex/Grok 等 provider 额度。
- Session-read 本身不复制会话进平台数据库；Wave 3 migration 005 另行新增五张
  transport-ledger 表（schema meta、commands、events、outbox、run links）。当前 live
  业务表均为 0 行，不能伪称已提交真实命令。
- 3C.1 另以 additive migration 006 source 定义独立 workflow-binding meta 与 append-only exact
  binding 表，并交付 bound-command 原子 primitive、binding-aware claim、read-only
  repeatable-read inventory 及 HQA reverse authority audit。代码/隔离 PostgreSQL 已验收，但
  migration 006/007 **已于 2026-07-21 live apply**（证据
  [audits/2026-07-21-v4-live-migrate-006-007.md](audits/2026-07-21-v4-live-migrate-006-007.md)）；
  V5 提供 dark `supervised_dispatch`；V6 本地授权后 CLI
  `--mode supervised_dispatch` 自动构建 `HttpHermesDispatchAdapter`。默认 CLI 仍
  reconcile-only。BFF mutation/composer 由 `QS_LOCAL_MUTATION_*` settings-gated（默认 OFF）。
  旧 TUI gateway capability contract 已因上游代码漂移而 fail closed，不再作为主连接。
  loopback 只构成网络暴露边界，不是 OS 用户认证；启用本地会话读取时，平台后端必须
  绑定 `127.0.0.1` 或 `::1`。运行与威胁模型见
  [Hermes 会话读取运行手册](guides/hermes-sessions.md)。
- 默认可回滚首页：`QS_HERMES_SHELL_ENABLED≠false` 时 `/` 与 locale root 进入 Hermes；`=false` 时 root/导航回到 Dashboard，直接 `/hermes` 仍可用。
- 旧四条 deep link（factor-lab / backtest / experiments / agent-studio）**仍完整保留**；
  Wave 2 仅加 soft `HermesParityBanner`（`3400659`），**无** delete / hard redirect。
  `/agent-studio` 保持只读候选检查，不挂载 task 控件；Gate 2 候选证据集中展示在
  `/hermes/approvals`，页面不提交审批 mutation。
- Agent Studio 已有独立、可回滚、默认关闭的页面级 redirect gate
  `QS_HERMES_AGENT_STUDIO_REDIRECT_ENABLED=true`；默认运行态不重定向，且在 exact
  digest-bound audit parity 与用户批准前不得开启。其他旧页没有 cutover 授权。
- 3B ledger 已交付 claim/lease/heartbeat primitives。3C/V5/V6 connector worker：默认
  `reconcile_only`；`supervised_dispatch` 经 CLI 自动构建 HTTP adapter（测试仍可用
  `FakeHermesDispatchAdapter`）。网络永远在 DB 事务外；timeout → durable
  `outcome_unknown`，禁止盲重试；空队列零 Hermes/provider。
  live 已 smoke：bound command → delivered / provider_call_count=1。
  `chat_write_ready` 在 local mutation + schema ready 时可 true；platform blockers 由
  `composer_readiness` 统一生成，local mutation ON 时清除 authenticated BFF/security
  permanent 码。`dark_dispatch_ready` 仅表示 research schema 就绪。
  `csrf_protection_unavailable` 已移除；在该历史快照中 ComposerDock 网络 submit
  尚未接线，现行路径见顶部 current rows。
- `/brief` 由官方本地 UI 聚合 factual v1 payload 与逐源 watermark；paper-account 权威源不可用时
  不显示虚构金额且禁用保存。后端严格校验完整 schema、日期、locale 与水位，但不会重新抓取每个
  上游来源来证明客户端 payload；因此它是本地单用户可信 UI 的事实快照，不是密码学来源证明。
  `/brief/[publicId]` 只渲染数据库快照，不以当前 live 数据覆盖历史。
- 2026-07-14 对抗修复后验证快照：平台 canonical Python gate 绿色
  （`1377 passed, 15 skipped`）；
  PostgreSQL throwaway 集成 `13 passed, 1 skipped`；frontend unit `35 files / 133 tests`；
  Ruff、lint、type-check、production build 均通过。
  真实 Chromium 对 `/zh/hermes` 及三个子路由、`/zh/brief/<publicId>` 和 locale root
  验证为 200/正确跳转，console/page/request errors 均为 0，桌面与 390px 无横向溢出；
  Hermes 视觉上只有一个“仅模拟”，当时的 composer textarea/send 均 disabled。

## 0. 界面操作指南（新，建议先读）

如果你看着研究流水线的界面"理解不了它在干什么"，先读这些基于真实代码编写的中文操作与说明文档：

| 文档 | 界面 |
|---|---|
| [guides/factor-lab.md](guides/factor-lab.md) | 因子实验室 `/factor-lab` |
| [guides/backtester.md](guides/backtester.md) | 回测器 `/backtest` |
| [guides/strategy-catalog.md](guides/strategy-catalog.md) | 策略目录 `/strategies` |
| [guides/experiments.md](guides/experiments.md) | 实验管理 `/experiments` |
| [guides/paper-trading.md](guides/paper-trading.md) | 模拟交易 `/paper-trading` |
| [guides/position-map.md](guides/position-map.md) | 持仓地图 `/position-map` |
| [guides/asia-radar.md](guides/asia-radar.md) | 亚洲雷达 `/asia-radar`（12 只 Futu 真实日线 ETF 代理；失败不回退 sample） |
| [guides/ai-news.md](guides/ai-news.md) | AI 新闻研究流 `/ai-news`（双源 Facade：AI HOT 主源 + Horizon 热备；auto failover） |
| [guides/hermes-sessions.md](guides/hermes-sessions.md) | Hermes official API 会话读取、密钥边界、故障排查与下一阶段连接架构 |
| [design/paper_trading_position_map_redesign.md](design/paper_trading_position_map_redesign.md) | 模拟交易 + 持仓地图**重设计**（设计文档 + 分阶段实现计划） |
| [design/paper_strategy_sleeves_plan.md](design/paper_strategy_sleeves_plan.md) | Paper Strategy Sleeves **MVP-1**（策略资金段/信号观察/allocated 分账设计，非历史 Phase 1） |
| [design/paper_strategy_sleeves_mvp2_plan.md](design/paper_strategy_sleeves_mvp2_plan.md) | Paper Strategy Sleeves **MVP-2**（pending execution / next-open 纸面执行计划） |
| [execution/paper_strategy_sleeves.md](execution/paper_strategy_sleeves.md) | Paper Strategy Sleeves 执行说明（手工 sleeve 保持 one-shot；D-33 为 `automation_managed` sleeve 增加独立常驻信号/计划/paper fill 周期） |
| [design/ai_news_integration_plan.md](design/ai_news_integration_plan.md) | AI News Integration **MVP-1 / MVP-2**（AI HOT 只读接入 + 可选 PG 缓存；决策日志指向 Horizon Bridge） |
| [superpowers/specs/2026-07-23-ai-news-horizon-bridge-design.md](superpowers/specs/2026-07-23-ai-news-horizon-bridge-design.md) | AI News × Horizon Bridge **Phase A 设计**（热备 failover；合同可升 Phase B；**已实现**） |
| [superpowers/plans/2026-07-23-ai-news-horizon-bridge.md](superpowers/plans/2026-07-23-ai-news-horizon-bridge.md) | AI News × Horizon Bridge **实现计划**（Tasks 1–10） |
| [execution/ai-news-horizon.md](execution/ai-news-horizon.md) | Horizon sidecar 执行 runbook（Docker、migration 009、`news horizon-ingest`、failover 演练） |

## 1. 从这里开始

| 文档 | 用途 |
|---|---|
| [../README.md](../README.md) | 快速项目入口与运行命令。 |
| [runbooks/agent-v0-2-local-stack.md](runbooks/agent-v0-2-local-stack.md) | **唯一 Agent v0.2 stack 运维权威**：016–029、backup/replay/apply/readiness/restart/E2E/restore；D-33 语义看 HQA 自动 paper runbook。 |
| `/Users/sunyibo/programs/Hermes-quant-agent/docs/superpowers/plans/2026-07-10-phase-1a-4-v2.md` | **已交付记录**：Slice 9A-9G + mini 9H。 |
| `/Users/sunyibo/programs/Hermes-quant-agent/docs/superpowers/plans/2026-07-12-full-9h-automation-notifications.md` | **已交付记录**：完整 9H 自动化与通知。 |
| [superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md](superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md) | Slice 0-8 实现记录与未来前端 backlog。 |
| [architecture/database_cache_plan.md](architecture/database_cache_plan.md) | 当前本地存储与 PostgreSQL 业务事实架构。 |
| [guides/hermes-sessions.md](guides/hermes-sessions.md) | official Hermes API 会话读取 BFF 的启用、威胁模型、验证与下一阶段写端边界。 |
| [audits/project_assessment_2026-06-11.html](audits/project_assessment_2026-06-11.html) | **2026-06-11 历史评估快照（HTML）**。 |
| [audits/remediation_ledger_2026-06-23.md](audits/remediation_ledger_2026-06-23.md) | **2026-06-23 整改快照**，不承担当前进度维护。 |
| [audits/remediation_goal_protocol.md](audits/remediation_goal_protocol.md) | `/goal` 长程整改执行协议：用“整改包”替代开放式优化，定义分层目标、机器验收、边界、降级、继续门禁与提交规则。 |
| [phases/phase_15_iteration_roadmap.md](phases/phase_15_iteration_roadmap.md) | **Phase 15 素材档案**：已被 HQA D-18/D-24 接管，不再是独立 active roadmap；仅保留 P0-P5 的素材价值。 |
| [OVERVIEW.md](OVERVIEW.md) | 简短的平台总览与安全摘要。 |
| [SYSTEM_DESIGN_RESEARCH.md](SYSTEM_DESIGN_RESEARCH.md) | 最初的系统设计与长期架构。 |
| [AGENTS.md](../AGENTS.md) | 本仓库中 AI 代理工作的规则。 |

## 2. 阶段地图

| 阶段 | 范围 | 架构 | 执行 | 学习 | 交付 |
|---|---|---|---|---|---|
| 0 | 项目骨架 | [架构](architecture/phase_0_architecture.md) | [执行](execution/phase_0_execution.md) | [学习](learning/phase_0_learning.md) | [交付](delivery/phase_0_delivery.md) |
| 1 | 数据层 MVP | [架构](architecture/phase_1_architecture.md) | [执行](execution/phase_1_execution.md) | [学习](learning/phase_1_learning.md) | [交付](delivery/phase_1_delivery.md) |
| 2 | 因子研究 MVP | [架构](architecture/phase_2_architecture.md) | [执行](execution/phase_2_execution.md) | [学习](learning/phase_2_learning.md) | [交付](delivery/phase_2_delivery.md) |
| 3 | 回测 MVP | [架构](architecture/phase_3_architecture.md) | [执行](execution/phase_3_execution.md) | [学习](learning/phase_3_learning.md) | [交付](delivery/phase_3_delivery.md) |
| 4 | 多因子实验 | [架构](architecture/phase_4_architecture.md) | [执行](execution/phase_4_execution.md) | [学习](learning/phase_4_learning.md) | [交付](delivery/phase_4_delivery.md) |
| 5 | 风险与模拟交易 | [架构](architecture/phase_5_architecture.md) | [执行](execution/phase_5_execution.md) | [学习](learning/phase_5_learning.md) | [交付](delivery/phase_5_delivery.md) |
| 7 | AI 研究助手 | [架构](architecture/phase_7_architecture.md) | [执行](execution/phase_7_execution.md) | [学习](learning/phase_7_learning.md) | [交付](delivery/phase_7_delivery.md) |
| 8 | 预测市场接口 | [架构](architecture/phase_8_architecture.md) | [执行](execution/phase_8_execution.md) | [学习](learning/phase_8_learning.md) | [交付](delivery/phase_8_delivery.md) |
| 9 | 本地 HTTP API | [架构](architecture/phase_9_api_architecture.md) | [执行](execution/phase_9_api_execution.md) | [学习](learning/phase_9_api_learning.md) | [交付](delivery/phase_9_api_delivery.md) |
| 10 | 前端/后端修复 | - | [执行](execution/phase_10_execution.md) | [学习](learning/phase_10_learning.md) | [交付](delivery/phase_10_fix_delivery.md) |
| 11 | 只读 Polymarket 数据 | [架构](architecture/phase_11_architecture.md) | [执行](execution/phase_11_execution.md) | [学习](learning/phase_11_learning.md) | [交付](delivery/phase_11_delivery.md) |
| 12 | Polymarket 历史回放 | [架构](architecture/phase_12_architecture.md) | [执行](execution/phase_12_execution.md) | [学习](learning/phase_12_learning.md) | [交付](delivery/phase_12_delivery.md) |
| 13 | 期权雷达 | [架构](architecture/phase_13_architecture.md) | [执行](execution/phase_13_execution.md) | [学习](learning/phase_13_learning.md) | [交付](delivery/phase_13_delivery.md) |
| 14 | 买方期权助手 | - | [执行](execution/phase_14_execution.md) | [学习](options/buyside_strategy_learning.md) | [交付](delivery/phase_14_delivery.md) |
| 15 | 历史维护素材（非活跃路线） | [素材](phases/phase_15_iteration_roadmap.md) | - | - | - |

## 3. 关键代码入口

| 区域 | 入口 |
|---|---|
| 股票数据提供方工厂 | `src/quant_system/data/provider_factory.py` |
| Futu 股票数据提供方 | `src/quant_system/data/providers/futu.py` |
| 因子流水线 | `src/quant_system/factors/pipeline.py` |
| 因子实验室仪表盘引擎 | `src/quant_system/factors/lab.py` |
| 回测流水线 | `src/quant_system/backtest/pipeline.py` |
| 回测 API job runner | `src/quant_system/api/jobs/backtest_jobs.py` |
| 策略注册表（含账户再平衡能力位） | `src/quant_system/strategies/registry.py` |
| Universe 注册表 | `src/quant_system/universe/registry.py` |
| 反转/动量论文复现 | `src/quant_system/replication/reversal_momentum.py` |
| 模拟交易历史回放流水线 | `src/quant_system/execution/pipeline.py` |
| 持久模拟账户模型 + 账本 | `src/quant_system/execution/account.py` |
| 模拟账户持久化 | `src/quant_system/execution/account_storage.py` |
| 模拟账户统一观察快照 | `src/quant_system/execution/account_snapshot.py` |
| 模拟账户取价（Futu 快照→最近收盘） | `src/quant_system/execution/price_source.py` |
| 模拟账户下单/再平衡服务 | `src/quant_system/execution/account_service.py` |
| Paper Strategy Sleeves 领域模型 / 分账基础 | `src/quant_system/execution/paper_strategy_sleeves.py` |
| Paper Strategy Sleeves 本地存储 | `src/quant_system/execution/paper_strategy_sleeve_storage.py` |
| Paper Strategy Sleeves 信号生成 | `src/quant_system/execution/paper_strategy_signal_service.py` |
| Paper Strategy Sleeves next-open 执行处理器 | `src/quant_system/execution/paper_strategy_execution_service.py` |
| Paper Strategy Sleeves 9G bounded observations | `src/quant_system/execution/paper_strategy_observations.py` |
| Paper Strategy Sleeves MVP-2 计划 | `docs/design/paper_strategy_sleeves_mvp2_plan.md` |
| 期权卖方筛选器 | `src/quant_system/options/screener.py` |
| 期权雷达 | `src/quant_system/options/radar.py` |
| 期权雷达刷新辅助 | `src/quant_system/options/data_refresh.py` |
| 本地 AlphaGBM 风格期权工具 | `src/quant_system/options/local_tools.py` |
| 本地期权研究辅助 | `src/quant_system/options/local_research.py` |
| Futu 期权 DuckDB 缓存 | `src/quant_system/storage/options_cache.py` |
| PostgreSQL 运行索引（可选） | `src/quant_system/storage/runs_repository.py` |
| 数据库连接 + 迁移 | `src/quant_system/storage/database.py` |
| Brief 业务事实 | `src/quant_system/brief/` / `src/quant_system/api/routes/brief.py` |
| AI 新闻缓存 + Horizon provider runs（可选） | `src/quant_system/news/repository.py` / `scripts/sql/002_ai_news_cache.sql` / `scripts/sql/009_ai_news_provider_runs.sql` |
| AI 新闻 Facade（双源 failover） | `src/quant_system/news/facade.py` |
| Paper repository factory | `src/quant_system/execution/account_repository_factory.py` |
| Paper PostgreSQL / mirror repository | `src/quant_system/execution/account_postgres_repository.py` / `account_dual_write_repository.py` |
| 买方指标 | `src/quant_system/options/buy_side_metrics.py` |
| 买方策略生成 | `src/quant_system/options/buy_side_strategy.py` |
| 买方场景实验室 | `src/quant_system/options/buy_side_scenarios.py` |
| 买方决策 API 逻辑 | `src/quant_system/options/buy_side_decision.py` |
| Futu 股票/期权提供方 | `src/quant_system/data/providers/futu.py` |
| AI HOT 只读新闻 client | `src/quant_system/news/aihot_client.py` |
| AI News API route/schema（中性 `/api/news/*` + aihot 别名） | `src/quant_system/api/routes/news.py` / `src/quant_system/api/schemas/news.py` |
| 预测市场提供方工厂 | `src/quant_system/prediction_market/provider_factory.py` |
| 预测市场采集器 | `src/quant_system/prediction_market/collector.py` |
| 预测市场回放回测 | `src/quant_system/prediction_market/timeseries_backtest.py` |
| API 路由 | `src/quant_system/api/routes/` |
| 前端路由 | `src/frontend/app/` |
| Factor Lab 到 Backtester 的预填链接 | `src/frontend/lib/factorLabHandoff.ts` |

## 4. 期权与 Futu 文档

| 文档 | 用途 |
|---|---|
| [futu/futu_integration_design.md](futu/futu_integration_design.md) | Futu 集成设计。 |
| [futu/futu_environment_setup.md](futu/futu_environment_setup.md) | OpenD 与 SDK 设置。 |
| [futu/futu_market_data_provider.md](futu/futu_market_data_provider.md) | Futu 股票数据提供方。 |
| [futu/futu_options_data_provider.md](futu/futu_options_data_provider.md) | Futu 期权提供方、字段、速率限制与安全失败。 |
| [futu/futu_troubleshooting.md](futu/futu_troubleshooting.md) | Futu 故障排查。 |
| [options/options_screener_api.md](options/options_screener_api.md) | 期权筛选器 API 参考。 |
| [options/options_screener_learning.md](options/options_screener_learning.md) | 卖方期权筛选器指南。 |
| [options/buyside_strategy_learning.md](options/buyside_strategy_learning.md) | 买方助手指南、场景实验室与风险披露。 |
| [options/local_alphagbm_tools.md](options/local_alphagbm_tools.md) | 本地 AlphaGBM 风格期权工具与端点。 |
| [delivery/phase_14_delivery.md](delivery/phase_14_delivery.md) | Phase 14 交付与验证记录。 |
| [audits/README.md](audits/README.md) | 历史审计笔记与现行状态指引。 |
| [audits/FRONTEND_REAL_DATA_REVIEW_2026-05-31.md](audits/FRONTEND_REAL_DATA_REVIEW_2026-05-31.md) | 现行前端真实数据与 sample 标注审查。 |
| [audits/project_assessment_2026-06-11.html](audits/project_assessment_2026-06-11.html) | 2026-06-11 全项目多智能体评估报告（现行权威，HTML）。 |

## 5. 研究复现文档

| 文档 | 用途 |
|---|---|
| [replications/reversal_momentum_replication.md](replications/reversal_momentum_replication.md) | 短期反转与长期动量论文的本地复现指南。 |
| [learning/research_registry_pipeline_2026_06_02.md](learning/research_registry_pipeline_2026_06_02.md) | 策略、universe、回测与只读因子实验室注册表工作流。 |

## 6. Polymarket / 预测市场文档

| 文档 | 用途 |
|---|---|
| [polymarket/polymarket_read_only_integration.md](polymarket/polymarket_read_only_integration.md) | 只读集成指南。 |
| [polymarket/polymarket_history_collection.md](polymarket/polymarket_history_collection.md) | 历史快照采集器指南。 |
| [polymarket/polymarket_timeseries_backtest_learning.md](polymarket/polymarket_timeseries_backtest_learning.md) | 时间序列回放学习指南。 |
| [polymarket/polymarket_charts_and_metrics.md](polymarket/polymarket_charts_and_metrics.md) | 图表与指标说明。 |
| [polymarket/polymarket_troubleshooting.md](polymarket/polymarket_troubleshooting.md) | 故障排查指南。 |
| [polymarket/polymarket_safety_boundaries.md](polymarket/polymarket_safety_boundaries.md) | 安全边界与非目标。 |

## 7. 当前前端页面

| 页面 | 用途 |
|---|---|
| `/data-explorer` | 股票数据查看器。 |
| `/brief` | 当日动态晨报预览；归档入口读取 PostgreSQL 中不可变 brief snapshot。 |
| `/brief/[publicId]` | 已归档晨报的只读快照页。 |
| `/hermes` | 默认研究工作台：Today + managed-session conversation + shared follow spine + Tasks/Approvals/Results。Composer 只在 exact local candidate/release window 且全部本地门禁通过时开放；external/history session 只读，public standing OFF，不提交真实交易。 |
| `/factor-lab` | 现有只读因子健康度与单标的择时仪表盘；HQA 工作台落地后应从一级入口降级为 run/detail 分析面。 |
| `/factor-lab/[runId]` | 因子运行详情。 |
| `/backtest` | 策略、universe 与因子权重回测运行。 |
| `/backtest/[runId]` | 回测运行详情。 |
| `/strategies` | 由策略注册表支撑的策略目录。 |
| `/strategies/[runId]` | 已落盘的反转/动量研报复现运行详情。 |
| `/docs/reversal-momentum` | 前端可读的复现文档。 |
| `/experiments` | 实验扫描、可选滚动验证折、固定因子组合摘要、数据源标注与最佳运行回顾。 |
| `/paper-trading` | 持久模拟账户（手动下单 + 策略一键再平衡）＋历史回放（研究）。 |
| `/paper-trading/[runId]` | 历史回放运行详情。 |
| `/position-map` | 模拟账户实时持仓地图（净值/现金/暴露/来源归因），另含回测暴露对比块。 |
| `/options-screener` | 单标的卖方期权筛选，含质量过滤、`Avoid` 审计开关与备注列。 |
| `/options-radar` | 每日卖方期权雷达快照。 |
| `/options-radar/[symbol]` | 已保存的雷达候选，以及可选的实时期权链加载。 |
| `/options-tools` | 本地 AlphaGBM 风格期权工具箱。 |
| `/options-buyside` | 买方期权策略助手。 |
| `/asia-radar` | 亚洲雷达：12 只美国上市国家 ETF 的只读跨市场热力图/排名/动态 K 型。专用 API 强制 `provider=futu`，失败不回退 sample；Phase 1 不展示 PE/PB/ERP/拥挤度/个股风险名单。 |
| `/ai-news` | AI 新闻研究流（AI HOT 主源 + Horizon 热备 Facade），含精选动态、关键词/分类/时间窗筛选、日报、原文链接与实际 provider/served_from。 |
| `/polymarket` | 只读预测市场研究。 |
| `/agent-studio` | 过渡期只读候选池检查；展示源码与审计证据，不再提供平台 LLM task 或批准/拒绝控件，并引导返回 Hermes。 |
| `/settings` | 脱敏后的本地设置。 |

前端文档：

| 文档 | 用途 |
|---|---|
| [frontend/frontend_chinese_version.md](frontend/frontend_chinese_version.md) | 站点级 English / 中文 语言路径、切换与 cookie 回退。 |
| [frontend/design_brief.md](frontend/design_brief.md) | 前端设计简报与组件规划。 |
| [delivery/frontend_refactor_2026-06-11_delivery.md](delivery/frontend_refactor_2026-06-11_delivery.md) | 2026-06-11 前端全面重构交付记录（设计系统、布局、E2E 根因与验证、截图）。 |

## 8. 常用命令

后端：

```powershell
conda activate ai-quant
quant-system serve --host 127.0.0.1 --port 8765
```

前端：

```powershell
cd src/frontend
npm run dev -- --hostname 127.0.0.1 --port 3001
```

测试与代码检查：

```powershell
conda activate ai-quant
quant-system doctor
.\scripts\verify.ps1
# 可选：dev server 停止时再运行 .\scripts\verify.ps1 -Build
```

`quant-system doctor` 是离线本地健康摘要：不连接行情源或数据库，只读取 settings
并输出安全开关、默认数据源、Futu/OpenD 端点、数据库索引配置和
`data/_runtime/logs/backend.jsonl` 路径。

期权雷达 sample 规模的真实运行：

```powershell
conda activate ai-quant
quant-system options daily-scan --top 10
```

期权雷达调度任务（刷新标的池、财报、VIX 后再扫描）：

```powershell
conda activate ai-quant
quant-system options daily-task --top 100 --universe-source public --earnings-source public --vix-source public
```

买方助手调试运行：

```powershell
conda activate ai-quant
quant-system options buyside-screen --ticker AAPL --view long_term_aggressive_bullish --target-price 220 --target-date 2026-12-31
```

## 9. 安全检查清单

1. `/api/health` 显示 `live_trading_enabled=false`。
2. `/api/orders/submit` 返回 404。
3. `/api/settings` 对密钥脱敏。
4. `/api/agent/llm-config` 不返回 API 密钥。
5. 携带 `polymarket_api_key` 的预测市场请求返回 400。
6. 不存在任何钱包、签名、券商或**实盘**下单路由（`/api/paper/account/orders` 等仅为本地模拟账户，不触达真实券商）。
7. Futu 代码只使用行情/数据上下文。
8. 前端页面清晰标注仅研究 / 只读输出。

## 10. 缓存层状态

已实现五类本地存储能力：

- DuckDB 缓存本地 Futu 期权报价窗口
  （`storage/options_cache.py`）。
- 一个可选的 PostgreSQL **运行索引**（`storage/database.py`、
  `storage/runs_repository.py`、`scripts/sql/001_runs_index.sql`）镜像
  基于文件的 backtest/factor/paper/replication 运行以便快速列出。它默认关闭
  （`QS_DATABASE_ENABLED`），在启动时于后台与文件系统对账，当数据库
  关闭、缓慢或不可达时，API 回退到扫描文件。
- 一个可选的 PostgreSQL **AI 新闻缓存 + Horizon provider runs**（`news/repository.py`、
  `news/facade.py`、`scripts/sql/002_ai_news_cache.sql`、
  `scripts/sql/009_ai_news_provider_runs.sql`）：镜像 AI HOT 只读条目/日报，并承接
  Horizon sidecar inbox ingest（`provider=horizon`）。`preference=auto` 顺序为
  aihot live → horizon PG fresh → aihot cache → unavailable；中性路由
  `GET /api/news/*`，`/api/news/aihot/*` 为兼容别名。LLM key 仅在 Horizon 容器
  env_file。见 [guides/ai-news.md](guides/ai-news.md) 与
  [execution/ai-news-horizon.md](execution/ai-news-horizon.md)。
- PostgreSQL **brief / AI daily 业务事实**（migration 003）：root owner、不可变
  brief issue/snapshot/source 和 owner-scoped AI 日报。
- PostgreSQL **paper account repository**（migration 004）：`file` 默认、
  file-authoritative `mirror`、DB-authoritative `canonical` 三种模式；API additive
  返回 `storage_mode/stale/warnings/reconciliation`。reconciliation 对账 raw、账户
  物化列、完整 ledger、positions、pending orders 和 snapshot state/integrity/freshness，
  不自动切换模式；canonical 缺账户时要求显式 backfill，不由普通 GET 创建。

延伸阅读：

- [architecture/database_cache_plan.md](architecture/database_cache_plan.md)

当前状态与后续决策：

- DuckDB 现用于本地 Futu 期权报价窗口。
- PostgreSQL 现（可选）用于 backtest/factor/paper/replication 运行索引。
- PostgreSQL 现（可选）也用于 AI HOT 只读新闻条目缓存。
- 四份 migration 的 14 张表（其中 003/004 为 11 张业务表）、brief archive 与 paper repository 已在代码、
  throwaway DB 和重启后的 live 库验证。
- paper account 的通用代码默认是 `file`；Agent v0.2 candidate local stack 则显式
  要求 canonical。默认值和旧快照都不证明 live 模式；现场事实以顶部 dated check
  与 local-stack readiness 为准。
- `quant-system data prices` 现为只读 Futu/QFQ/1d JSON seam；不读取 local cache，也不
  回退到 sample、Tiingo 或 Longbridge。
- HQA 9A-9G、mini/full 9H 与 D-31 第一批三份计划（Wave 1）均已交付到各自明确边界。
- Agent v0.2 source 当前含 016–028。2026-07-31 “live 有 016–027、没有 028”只是
  pre-apply 历史快照；2026-08-01 窗口已完成一次 028 apply，随后 AlphaZeroBeta 重测仅
  证明 private candidate 的机械生命周期。论文 intake verdict 未被运行时合同验证或接受，
  factor/backtest/Gate/result 均未评价；P1 仍需 digest-bound `hqa.paper_intake/v1`
  receipt/verifier。当前保持 candidate revoked、connector `reconcile_only`、public OFF，
  禁止重放 028；未来只能用全新 candidate 补齐剩余 DoD，不能从历史 D-31 状态推导执行顺序。
- 写端使用 PostgreSQL durable command/outbox/event ledger + deterministic connector；
  `LISTEN/NOTIFY` 只作唤醒、periodic scan 补偿。`reconcile_only` 是默认安装姿态；
  `supervised_dispatch` 只在 exact local candidate/release window 内运行。空队列零
  provider/Hermes mutation，不采用 LLM cron 空轮询。
- Agent v0.2 candidate safety 需要 canonical root-owner 唯一 `default` account，
  materialized/raw `account_id` 与 JSON boolean `kill_switch=true` 一致。
  `GET /api/safety/effective` 仅观察；candidate `status|open|revoke` 由操作者控制；
  HQA Keychain 先做 non-creating `probe`，只有操作者可执行 `initialize-key`。
- 剩余的 PostgreSQL 目标：雷达运行、请求日志，以及更丰富的
  API 可见快照。
- 对大型 OHLCV 与分析型时间序列数据集采用 Parquet / DuckDB。
- 若 PostgreSQL 后续成为主要时间序列存储，可选引入 TimescaleDB。
