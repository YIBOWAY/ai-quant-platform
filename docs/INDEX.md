# 文档索引

> **公开快照（2026-10-04）**：本索引中的历史状态保留原时点含义；会话、账户明细和未公开原件不随源码发布。详见[公开范围说明](publication-20261004.md)。

这是整个仓库的主地图。先用下面的“当前工作”确定执行入口，再按需查架构、操作
指南和历史交付。不要从旧 phase、audit 或未勾选 checkbox 推断当前进度。

## 当前工作（2026-09-26）

当前执行入口仍是HQA的[唯一现行计划](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/plans/2026-09-14-alpha-research-reset.md)及[最新进度](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/handoffs/2026-09-23-research-continuation/PROGRESS.md)。Phase2与Phase3按实现、隔离验证、发布和自然运行分别验收；未找到可靠alpha或未满足资金条件时保留阻断。09-28审查续修覆盖准入断链/撤销边界、统计口径、SEC历史披露小样与组合净订单成本预检，结果与发布层见[最新收据](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/receipts/2026-09-28-review-followthrough-and-sec-pit.md)。09-26的组合、统计内核和单窗口阶段结果仍见[前批收据](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/receipts/2026-09-26-phase3-portfolio-and-window-stage.md)；原三个ETF假设保持归档，数据小样、工程资格和费用预检均不等于策略准入。

> **09-20 后续授权**：现行研发计划为HQA[alpha-research-reset v3.2](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/plans/2026-09-14-alpha-research-reset.md) §12，主人已批准继续完整Phase2。当前实施、真实数据与部署状态看[实施收据](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/receipts/2026-09-20-phase2-implementation.md)。前一轮[审查修复](receipts/2026-09-20-phase2-audit-repairs.md)及下方09-15段保留为各自历史，不将Phase1/2预先标全完。

[本地网站发布与实站验收](receipts/2026-09-15-local-web-deployment.md)是09-15历史运行记录，当时HQA接班点为§13.55。主人已确认该批发布，Platform a4fc35bf/HQA 1ed2d48当时已部署；真实页面和所选账户经济字段已核对。原导航取消在实站仍可复现，首页部分策略名称仍通用，不声明整站全绿。

[全站功能修复与完整复测](receipts/2026-09-15-functional-repairs-and-retest.md)保留发布前HQA §13.54的结果。后端4104项、前端822项、数据库238项与5项派发及备份恢复通过；浏览器213通过/1失败/24场景跳过。该轮结束时未发布，后续发布见上方收据。原失败、跳过、图像审核与最终结果均分列保存，以下9/13记录为历史首跑。

[全站功能与浏览器E2E验收](receipts/2026-09-13-full-functional-e2e.md)保留HQA §13.52时的首跑。前端781项单元测试通过，既有E2E首跑214项为85过/114失败/15跳过，补测分列；当时发现真实产品缺陷及旧fixture/测试路径失配，验收未通过。该轮只修测试隔离和确定的测试前提，不把当时未验证的停止/审批/组合启用链路写成通过。

[Longbridge备用数据与公司研究](receipts/2026-09-12-longbridge-company-research.md)记录HQA §13.51。Futu保持默认，新增公司研究、财务质量检查、真实能力状态和Hermes同源资料工具；长桥历史与期权报价权限仍部分受限，冻结策略不自动换源。入口与用法见[公司研究指南](guides/company-research.md)。下面日期段保留各自历史，不作为当前运行状态。

[Grok接入、成对评价与模拟观察修复](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/receipts/2026-09-11-intake-paper-repair.md)记录HQA §13.50。本批保留各策略的规则，冻结基线/增强共用输入并要求预声明增量目标；修复恢复身份、入金收益和日历，复用已有Grok公式。已部署，正式新协议自然投递与后续成交仍须真实记录。

[策略研究、收益复核与多因子工作流](receipts/2026-09-09-strategy-research-workflow.md)记录TopN/收益归属修复、近期Grok探索、固定策略库、真实Qlib执行和Ridge对照。当前接班点为HQA §13.46；研究与验证可用，新定义最终模拟日程仍有明确未完成边界，不能从验证通过推断已启用。操作见[我的策略指南](guides/strategy-library.md)。下面日期条目保留历史。

[真实参考回测、Qlib 滚动研究与模拟复盘](receipts/2026-09-07-qlib-research-evaluation.md)已完成实际数据计算、相关测试与源码生产构建，代码提交为 `b7d54777`。现行接班点为 HQA §13.44，部署与未完成的浏览器验收见收据；下面 §13.43 保留前一轮记录。

[策略与因子、历史对照与 Grok 502 修复](receipts/2026-09-06-collection-and-market-history.md)记录最新页面与正式数据核验：13 项源码介绍、两份真实双引擎记录、去除组合指标误分配，以及流式 Grok 修复。最新接班点为 HQA §13.43。[RD-Agent / Qlib 扩展报告](audits/2026-09-06-rdagent-qlib-opportunities.md)区分当前接线与尚未实施的建议。

[Grok 4.6、自动市场检查与真实证券目录](receipts/2026-09-05-grok46-market-assistant.md)保留上一轮模型参数、宏观指标、每日更新、FinanceDatabase 搜索和无样本替代修复；对应 HQA §13.42。下方 §13.41 为更早记录。

[市场研判、浮窗与日报措辞修订](receipts/2026-09-05-market-outlook-and-brief-copy.md)记录本轮页面、数据来源、Grok 与历史日报修订；现行计划接班点为 HQA §13.41。[个人助手实际使用评估与修复](audits/2026-09-05-personal-quant-usability.md)保留前一轮证据。新 same-chat 日线公式复现通过双引擎与既有准入后自动启用模拟运行；以下旧日期条目只代表当时行为。

| 层级 | 权威入口 | 状态 |
|---|---|---|
| 唯一现行计划 | [docs/plans/2026-09-14-alpha-research-reset.md](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/plans/2026-09-14-alpha-research-reset.md) | v3.2 §12；Phase2实施与真实验收逐项记录。源码与日常运行版本分开，不能从镜像ff推断常驻服务已重载。D-31…D-34不是产品线。 |
| 期权推荐当前现场 | [期权推荐指南](guides/options-recommendations.md) | 2026-08-28 11:39 +08 浏览器触发的 2026-08-27 快照为 30/34 成功、4 失败、20 候选；这是 dated partial snapshot，不是永久运行状态。 |
| 跨仓导航 | [docs/README.md](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/README.md) | 先读这个再读下面的历史表。 |
| 跨仓产品路线（历史） | [docs/design/2026-07-01-roadmap-phases-0b-4.md](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/design/2026-07-01-roadmap-phases-0b-4.md) | Hermes 是编排层；本仓库是领域后端。D-xx 台账已停写。 |
| 已交付跨仓计划 | [docs/superpowers/plans/2026-07-10-phase-1a-4-v2.md](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/superpowers/plans/2026-07-10-phase-1a-4-v2.md) | Slice 9A-9G + mini 9H 已完成。 |
| 已交付完整 9H | [docs/superpowers/plans/2026-07-12-full-9h-automation-notifications.md](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/superpowers/plans/2026-07-12-full-9h-automation-notifications.md) | 调度、对账、周报、freshness 与通知已完成；平台只负责只读消费。 |
| 已交付候选完整性 / Gate 3 | [docs/superpowers/plans/2026-07-13-candidate-integrity-and-gate3.md](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/superpowers/plans/2026-07-13-candidate-integrity-and-gate3.md) | 统一 repo-anchored candidate root、immutable manifest、HQA Scene-B Gate 1 精确源绑定、Gate 2 digest CAS、迁移工具、隔离且可恢复的 Gate 3 worktree 已交付并完成对抗性加固。Scene-B 已完成 final receipt → prepare → 人工 diff/commit → reviewed → cleanup，并以 `524e791` 合入当前分支（见下）。 |
| 已交付专业前端 / 只读壳 | [docs/superpowers/plans/2026-07-13-hermes-professional-frontend-shell.md](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/superpowers/plans/2026-07-13-hermes-professional-frontend-shell.md) | F0 direction-a + F1 书面批准后，F2 Hermes 壳与可回滚默认首页已交付。Approvals 保持证据只读（`approvalMutations=false`）；official Hermes API 会话读取已接入（`sessionRead=true`）。3E-A 又交付只读 Unified Results 目录/详情，但完整切流仍关闭。设计记录见 [design/hermes-workbench/README.md](design/hermes-workbench/README.md)。 |
| 唯一运维权威 | [Agent v0.2 local-stack](runbooks/agent-v0-2-local-stack.md) | 唯一维护 migration、backup、isolated replay、readiness、restart、candidate E2E 与 pre-028 restore 的文档；其他 runbook 只解释组件。 |
| Platform 单一 main | [2026-08-10 Git 分支合并审计](audits/2026-08-10-platform-git-branch-consolidation.md) | 两个 Platform checkout 与 GitHub 已统一到受保护 `main`；旧分支先按 exact tip 建 archive tag 后删除，bundle/dirty snapshot 可恢复。此拓扑收口不授权 live、因子晋级或 migration 029。 |
| 论文入队机（旧称 D-33） | HQA `docs/plans/2026-08-10-full-automation-paper-path.md` | 历史实现。研究账的一个来源，不是默认入口。 |
| 双引擎研究作业（旧称 D-34） | [历史架构](architecture/d34-autonomous-paper.md) | 内部实现记录。工作台控件、owner API 与操作指南已于 2026-08-23 随 `417be6d` 退役并删除；当前链只看 HQA 现行计划。 |
| 029 operator window | 2026-08-10 现场执行 | backup + isolated restore rehearsal 后一次 apply；append-only promote/demote/daily quota authority。禁止重放；启动永不自动迁移。 |
| 应用前历史快照 | source/change set 016–028；live 现场只读核对 2026-07-31 | inspected 016–027 markers 存在；当时 028 marker 不存在，运行后端尚无 `/api/safety/effective`。这是保留的 pre-apply 快照，不描述当前 live 状态。 |
| 028 operator window | 2026-08-01 现场观察；详见 [Agent v0.2 local-stack](runbooks/agent-v0-2-local-stack.md) | 028 marker=1/version=1，exact two binding triggers 均为 `ENABLE ALWAYS`，schema fingerprint `e3f713ac05a1a990cfa9be45157e880e06709c425a4883736544d8f2b626f33a`；一次性 apply 后的正常重启、readiness 与 `/api/safety/effective` 通过。该快照不证明论文研究语义，也不授权重放 028。 |
| AlphaZeroBeta 重测 | `$HOME/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/Hermes-quant-agent/docs/audits/2026-07-31-alphazerobeta-paper-research-web-e2e.md` | Web/UI、Session、dispatch、provider、approval、durable Run、直接 PDF/全文读取与数据库持久化等机械生命周期通过，zero orders；但论文研究 verdict 为 **UNVERIFIED / NOT ACCEPTED**。Skill-only 约束没有形成 runtime-enforced、digest-bound `hqa.paper_intake/v1` receipt/verifier，因此 factor/backtest/Gate/result 为 **NOT EVALUATED**，不能写成正确跳过。正式候选套件 `5632 passed / 272 skipped / 0 failed`，manifest SHA-256=`eba8099bf3801927f3d93b40d1e133546d7cbcc4eece4c58b416bf52bd29a136`；candidate 已 revoke，connector=`reconcile_only`，local/public write 均关闭。 |
| 当前实现选择 | Agent v0.2 local-private managed-session write | owner session/CSRF + encrypted payload + durable connector + transcript/follow/approval/stop/result。安装默认仍 fail-closed；当前 `local_trust` owner 模式使用 `supervised_dispatch`，但 public/release 仍 OFF。历史/外部 session 只读，继续上下文需显式 fork。local `chat_write_ready` ≠ public，交易 kill switch true。 |
| 本机 Hermes 连接决策 | [docs/design/2026-07-15-local-hermes-integration-decision.md](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/design/2026-07-15-local-hermes-integration-decision.md) | 采用 PostgreSQL durable command/event/outbox + deterministic worker；`LISTEN/NOTIFY` 唤醒、periodic scan 兜底，不让 Hermes/LLM cron 空轮询。 |
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
| [guides/position-map.md](guides/position-map.md) | 持仓地图 `/paper-trading?view=map`（旧 `/position-map` 为 alias） |
| [guides/asia-radar.md](guides/asia-radar.md) | 亚洲雷达 `/watch?pane=radar`（旧 `/asia-radar` 为 alias；12 只 Futu 真实日线 ETF 代理） |
| [guides/market-cross-section.md](guides/market-cross-section.md) | 市场横截面 `/watch?pane=cross`（旧 `/market-cross-section` 为 alias；严格 Futu） |
| [guides/ai-news.md](guides/ai-news.md) | AI 新闻研究流 `/ai-news`（双源 Facade：AI HOT 主源 + Horizon 热备；auto failover） |
| [guides/hermes-sessions.md](guides/hermes-sessions.md) | Hermes `/hermes`、saved-session 深链、本地写路径和 034/local-trust 边界 |
| [guides/options-recommendations.md](guides/options-recommendations.md) | 期权推荐 `/options-radar`、六态、立即更新、物理 EV、IVR warming 与已知边界 |
| [design/paper_trading_position_map_redesign.md](design/paper_trading_position_map_redesign.md) | 模拟交易 + 持仓地图**重设计**（设计文档 + 分阶段实现计划） |
| [design/paper_strategy_sleeves_plan.md](design/paper_strategy_sleeves_plan.md) | Paper Strategy Sleeves **MVP-1**（策略资金段/信号观察/allocated 分账设计，非历史 Phase 1） |
| [design/paper_strategy_sleeves_mvp2_plan.md](design/paper_strategy_sleeves_mvp2_plan.md) | Paper Strategy Sleeves **MVP-2**（pending execution / next-open 纸面执行计划） |
| [execution/paper_strategy_sleeves.md](execution/paper_strategy_sleeves.md) | Paper Strategy Sleeves 执行说明（手工 sleeve 保持 one-shot；已启用模拟运行的正式观察只由 `com.aiquant.d34-paper-cycle` 在 06:15/22:25 两个日历时段触发） |
| [design/ai_news_integration_plan.md](design/ai_news_integration_plan.md) | AI News Integration **MVP-1 / MVP-2**（AI HOT 只读接入 + 可选 PG 缓存；决策日志指向 Horizon Bridge） |
| [superpowers/specs/2026-07-23-ai-news-horizon-bridge-design.md](superpowers/specs/2026-07-23-ai-news-horizon-bridge-design.md) | AI News × Horizon Bridge **Phase A 设计**（热备 failover；合同可升 Phase B；**已实现**） |
| [superpowers/plans/2026-07-23-ai-news-horizon-bridge.md](superpowers/plans/2026-07-23-ai-news-horizon-bridge.md) | AI News × Horizon Bridge **实现计划**（Tasks 1–10） |
| [execution/ai-news-horizon.md](execution/ai-news-horizon.md) | Horizon sidecar 执行 runbook（Docker、migration 009、`news horizon-ingest`、failover 演练） |

## 1. 从这里开始

| 文档 | 用途 |
|---|---|
| [../README.md](../README.md) | 快速项目入口与运行命令。 |
| [runbooks/agent-v0-2-local-stack.md](runbooks/agent-v0-2-local-stack.md) | **唯一 Agent v0.2 stack 运维权威**：migration、backup/replay/apply/readiness/restart/E2E/restore；当前研究语义看 HQA 现行计划。 |
| [architecture/d34-autonomous-paper.md](architecture/d34-autonomous-paper.md) | D-34 数据流、双引擎边界、030–032 数据模型、job 状态机、API 与回退。 |
| [docs/superpowers/plans/2026-07-10-phase-1a-4-v2.md](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/superpowers/plans/2026-07-10-phase-1a-4-v2.md) | **已交付记录**：Slice 9A-9G + mini 9H。 |
| [docs/superpowers/plans/2026-07-12-full-9h-automation-notifications.md](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/superpowers/plans/2026-07-12-full-9h-automation-notifications.md) | **已交付记录**：完整 9H 自动化与通知。 |
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
| 期权日任务与进度状态 | `src/quant_system/options/daily_task.py` |
| 期权 v3 generation 快照 | `src/quant_system/options/radar_storage.py` |
| ATM30 IV history / IVR warming | `src/quant_system/options/iv_history.py` |
| 物理 EV 与推荐硬条件 | `src/quant_system/options/seller_score.py` |
| 除息事件证据 | `src/quant_system/options/dividend_events.py` |
| 期权雷达刷新辅助 | `src/quant_system/options/data_refresh.py` |
| 期权推荐 API / 202/409 后台入口 | `src/quant_system/api/routes/options_radar.py` |
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
| [guides/options-recommendations.md](guides/options-recommendations.md) | 现役期权推荐页面、后台任务、状态、模型与故障边界。 |
| [futu/futu_integration_design.md](futu/futu_integration_design.md) | 2026-05 冻结的 Futu 集成设计，不是现役运行合同。 |
| [futu/futu_environment_setup.md](futu/futu_environment_setup.md) | OpenD 与 SDK 设置。 |
| [futu/futu_market_data_provider.md](futu/futu_market_data_provider.md) | Futu 股票数据提供方。 |
| [futu/futu_options_data_provider.md](futu/futu_options_data_provider.md) | Futu 期权提供方、字段、速率限制与安全失败。 |
| [futu/futu_troubleshooting.md](futu/futu_troubleshooting.md) | Futu 故障排查。 |
| [options/options_screener_api.md](options/options_screener_api.md) | 期权筛选器 API 参考。 |
| [options/options_screener_learning.md](options/options_screener_learning.md) | 卖方期权筛选器指南。 |
| [options/buyside_strategy_learning.md](options/buyside_strategy_learning.md) | 买方助手指南、场景实验室与风险披露。 |
| [options/local_alphagbm_tools.md](options/local_alphagbm_tools.md) | 本地 AlphaGBM 风格期权工具与端点。 |
| [delivery/phase_14_delivery.md](delivery/phase_14_delivery.md) | Phase 14 交付与验证记录。 |
| [audits/README.md](audits/README.md) | 历史审计索引；当前状态只看本页顶部入口。 |
| [audits/FRONTEND_REAL_DATA_REVIEW_2026-05-31.md](audits/FRONTEND_REAL_DATA_REVIEW_2026-05-31.md) | 2026-05-31 前端真实数据与 sample 标注历史快照。 |
| [audits/project_assessment_2026-06-11.html](audits/project_assessment_2026-06-11.html) | 2026-06-11 全项目多智能体历史评估（HTML）。 |

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
| `/` | Hermes shell 启用时进入助手首页；关闭时显示旧 dashboard。 |
| `/watch` | 盯盘主面：quotes/cross/radar 三 pane。 |
| `/brief` | 当日动态晨报预览；归档入口读取 PostgreSQL 中不可变 brief snapshot。 |
| `/brief/[publicId]` | 已归档晨报的只读快照页。 |
| `/brief/rollup/[publicId]` | 不可变周/月 brief rollup 与同类前后导航。 |
| `/hermes` | Hermes 助手：今日/研究/模拟三本账、唯一 managed-session composer、可拖拽侧栏、对话内 lifecycle progress、recent sessions 与明确标源的 Platform result。缺材料同聊追问且 0 job，充分材料 1 job 并只到 verified candidate。 |
| `/hermes/sessions/[sessionId]` | GET-only 已保存会话详情与显式 fork 深链。 |
| `/hermes/results` | 平台/HQA 统一结果目录与详情。 |
| `/hermes/results/[kind]/[resourceId]` | 一个 exact 统一结果 identity 的只读详情。 |
| `/collection` | 策略目录与因子注册表的只读翻转卡片集；指标绑定完成的 backtest receipt。 |
| `/library` | candidate-only 研究验证库；页面与轮询只读 remote book。只有 unbound + 64hex source digest 且 DSR/相关性/成本门通过的候选显示 owner/CSRF、digest-bound「启用模拟运行」动作；其他候选保留研究复核原因。 |
| `/factor-lab` | 现有只读因子健康度与单标的择时仪表盘；HQA 工作台落地后应从一级入口降级为 run/detail 分析面。 |
| `/factor-lab/[runId]` | 因子运行详情。 |
| `/backtest` | 策略、universe 与因子权重回测运行。 |
| `/backtest/[runId]` | 回测运行详情。 |
| `/strategies` | 由策略注册表支撑的策略目录。 |
| `/strategies/[runId]` | 已落盘的反转/动量研报复现运行详情。 |
| `/docs/reversal-momentum` | 前端可读的复现文档。 |
| `/experiments` | 实验扫描、可选滚动验证折、固定因子组合摘要、数据源标注与最佳运行回顾。 |
| `/paper-trading` | 持久模拟账户、`view=map` 持仓/暴露账、策略仓与历史回放。 |
| `/paper-trading/[runId]` | 历史回放运行详情。 |
| `/options-screener` | 单标的卖方期权筛选，含质量过滤、`Avoid` 审计开关与备注列。 |
| `/options-radar` | 每日卖方期权推荐；22:00 自动更新，也可立即启动后台更新并查看进度。 |
| `/options-radar/[symbol]` | 已保存的雷达候选，以及可选的实时期权链加载。 |
| `/options-tools` | 本地 AlphaGBM 风格期权工具箱。 |
| `/options-buyside` | 买方期权策略助手。 |
| `/ai-news` | AI 新闻研究流深页，保留在 Settings 实验室；晨报承载默认 AI News 产品入口。 |
| `/polymarket` | 只读预测市场研究。 |
| `/agent-studio` | 过渡期只读候选池检查；展示源码与审计证据，不再提供平台 LLM task 或批准/拒绝控件，并引导返回 Hermes。 |
| `/settings` | 脱敏后的本地设置。 |

兼容跳转另列如下；`/en` 与 `/zh` 前缀同样适用。合并入口显式返回 301，
`replications`/`order-book` 改名入口使用 Next.js permanent redirect（当前响应为 308）：

| 旧路径 | 现役目的地 |
|---|---|
| `/data-explorer` | `/watch?pane=quotes` |
| `/market-cross-section` | `/watch?pane=cross` |
| `/asia-radar` | `/watch?pane=radar` |
| `/position-map` | `/paper-trading?view=map` |
| `/hermes/sessions` | `/hermes` |
| `/replications` / `/replications/[runId]` | `/strategies` / `/strategies/[runId]` |
| `/order-book` | `/polymarket` |

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

期权推荐正式 exact-34 任务：

```bash
./ai-quant/bin/quant-system options daily-task \
  --provider futu --top 34 --universe-source existing \
  --earnings-source public --dividend-source public --vix-source public
```

`daily-scan` 只可写隔离的非正式输出目录；sample 的所有输入、输出和 IV history 也必须
完全隔离。完整命令见[期权推荐执行指南](execution/phase_13_execution.md)。

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

现役存储速查：

- 本机 Agent 栈使用 PostgreSQL canonical `default` 模拟账户；数据库不可用时不回退
  文件账户。普通开发配置仍可显式选择 `file|mirror|canonical`，但默认值不能证明 live。
- 正式 migration 已到 034，startup 固定不自动迁移；任何已应用 migration 都不得重放。
- PostgreSQL 还承载运行索引、brief/news 缓存和 Agent durable ledger；DuckDB/Parquet
  承载本地期权报价窗口与大型分析型时间序列。
- `quant-system data prices` 是只读 Futu/QFQ/1d JSON seam，不从 local cache 或 sample
  静默补位。
- 当前本机聊天姿态是 `local_trust + supervised_dispatch`；public/release/live 仍关闭。
  运行态以顶部 current 入口和 local-stack readiness 现场重查，不从旧 candidate 审计推断。

016–028 apply、AlphaZeroBeta candidate、`reconcile_only` 和早期 PostgreSQL 待办只属于
2026-07/08 的历史演进，详见 [database_cache_plan.md](architecture/database_cache_plan.md)
与 `docs/audits/`；它们不是当前 NEXT、migration 队列或 connector 姿态。
