# Hermes 重设计 Demo · 数据契约对照表（2026-07-24）

目的：保证三个设计方向（A 概览 / B 密度 / C 叙事）中**每一个可见字段都有真实后端来源**，
实现时不会与 API 漂移。合同依据：`src/frontend/lib/api.generated.ts`（OpenAPI 生成，与后端
Pydantic 一致）、`lib/hermes/types.ts`、`viewModel.ts`、`workspaceClient.ts`。

**结论先行：三个方向所需数据 100% 来自现有 5 个 GET 接口 + workspace 脊柱，零新增后端需求。**
仅 3 处为"派生/聚合"呈现（见 §4），均为前端 viewModel 层计算，不改接口。

---

## 1. 首屏数据来源（现有接口，无需新增）

| 接口 | 用途 | 现状 |
|---|---|---|
| `GET /api/agent/candidates` | Gate 2 待审批候选 | 已在用（Today 页） |
| `GET /api/hermes/artifacts?limit=20` | 自动化状态、组合风险、市场推演、周复盘 | 已在用 |
| `GET /api/hermes/results?limit=5` | 最近结果列表 | 已在用 |
| `GET /api/hermes/gateway` | "Hermes 在线"状态点 | 已有，Today 未消费，demo 新增消费 |
| `GET /api/workspace/{id}/snapshot`（+follow/SSE） | 审批挑战、运行中命令、Authority 健康 | chat 开启时已在用 |

## 2. UI 元素 → API 字段映射

### 2.1 "待我处理"聚合区（三方向共用）

| Demo 文案 | 来源字段 | 说明 |
|---|---|---|
| "Hermes 请求一次 Futu 只读行情调用" 标题 | 由 `WorkspaceApprovalProjection.kind="hermes.command_approval"` + 关联 command/run 语义生成 | snapshot `approvals[]`，**审批语义文案需由 command kind 映射表生成**（前端字典，非后端字段） |
| "审批 · 单次" 标签 | `decision` 枚举只可能是 `allow_once|deny` | 按钮文案与之严格对应 |
| "10:24 · 30 分钟内有效" | `expires_at` | 到期时间直接渲染 |
| "允许一次 / 拒绝" 按钮 | V7a decide：`allow_once|deny` CAS | mutation 关则按钮不出现（沿用现有规约） |
| "因子候选 mom20 v3 待评审" | `CandidateSummary.candidate_id / artifact_type / goal` | `integrity_state="verified"` 且 `approval_enabled=true` 且 `status="pending"`（即 viewModel 的 candidateAttention 判定，viewModel.ts:191-214） |
| "Gate 2" 标签 | `approval_binding="pending"` | |
| "09:51 · 提交于…" | `created_at` | 可空，空则省略该行 |

注意：demo 把 approvals（命令审批）和 candidates（Gate 2）聚合在一个"待我处理"区，
但**视觉上用不同标签区分语义**（审批/Gate 2）——符合 spec §4.2"统一展示但不合并语义"。

### 2.2 "运行中"区

| Demo 文案 | 来源字段 |
|---|---|
| "动量因子失效分析" | `WorkspaceCommandProjection.kind` → 前端 kind→标题字典 |
| "delivered / 等待回执" | `state`（终态集 `succeeded|cancelled|failed|rejected|timed_out`，其余为进行中） |
| "attempt 1" | `attempt_count` |
| "开始 10:02" | `created_at` |
| "wm_…8f2c"（B 方向会话列） | `platform_session_id`（截断显示） |

**已修正**：方向 A 初版的"60% 进度条"已删除——合同中没有进度字段，spec §6.2 禁止伪造百分比。
demo 现只展示事件流状态文本（`state` + `occurred_at`）。

### 2.3 "最近结果"区

| Demo 元素 | 来源字段 |
|---|---|
| 条目标题（如"组合风险 · 日度快照"） | `HermesResultItem.display_title` |
| kind 标签（portfolio_risk / market_foresight / weekly_review / backtest） | `kind`（12 态枚举内） |
| 状态 pill（computed/proposal/published/done） | `status`（自由文本）+ `freshness` |
| "proposal-only" 黄色标记 | market_foresight artifact 的常量 `proposal_only=true` |
| 时间 | `occurred_at` |
| 跳转 → | `detail_href` |

**已修正**：方向 A 初版的"每日晨报/期权雷达"不在 12 种 result kind 内，已替换为合法 kind。
晨报本身是 `/brief` 页面资产，demo 中仅保留 header 处"查看晨报"按钮链接，不混入结果列表。

### 2.4 状态条（一行聚合）

| Demo 元素 | 来源字段 |
|---|---|
| "Hermes 在线" | `GET /api/hermes/gateway` → `read_status/connected` |
| "数据源 Futu 正常" | artifacts envelope `sources[].status`（6 源聚合） |
| "自动化 4/4" | automation_status artifact `jobs[]` 恰好 4 条，`status` 四态（viewModel AutomationSummary 已有此派生：`healthy/total=4`） |
| "数据库正常" | workspace `authority_health.command_ledger`（chat off 时可省略此项） |
| "系统状态 →" | 链接到折叠的技术详情（artifact `sources[]` + `warnings[]` + gateway `blockers[]`） |

### 2.5 自动化（B 方向 job 矩阵 / A·C 一行收敛）

| Demo 元素 | 来源字段 |
|---|---|
| 4 行 job 名 | `job_id` 固定四值：`daily_close/freshness/weekly/notification_drain` |
| "fresh/stale/failed/never_run" | `status` |
| "delivered" | `notification_status` |
| "上次成功 昨日 16:35" | `last_success_at` |

**已修正**：方向 A 初版的"下次 16:30"已删除——合同中**没有 next_run 字段**，
只有 `expected_schedule` 字符串；demo 改用 `last_success_at`。

### 2.6 对话活跃态

| Demo 元素 | 来源字段 |
|---|---|
| 用户/Hermes 消息 | `GET …/messages` → `HermesMessage{role, content, timestamp}`（SSE 只给 body-free hint，正文永远从 messages BFF 取——demo 的呈现方式与此一致） |
| "研究计划"步骤列表 | assistant `content` 结构化部分（Hermes 输出约定，非 API 字段） |
| "样本 · 非实盘"标记 | typed result `sample_or_real`（fail-closed：非 "real" 一律标 sample） |
| 结果卡指标（IC 等数字） | `summary`/`resource` 详情负载（`GET …/results/{kind}/{id}` → `resource`）；demo 数字为示例内容 |
| 限制说明 | `limitations[]` |
| 右侧"需要你的确认"卡 | 同 §2.1 approvals |
| "本次产出" | typed `results[]`（`display_title/kind/occurred_at`） |
| B 方向"系统健康/Authority"表 | `authority_health`（`command_ledger/command_approval/gate_1..3/hermes_gateway="dark"/mutation`） |

## 3. 已主动剔除的"漂移字段"清单

| 初版 demo 元素 | 问题 | 处理 |
|---|---|---|
| 运行中"60% 进度条" | 无进度字段；spec 禁止伪造百分比 | 删除，改事件状态文本 |
| "每日晨报"作为结果条目 | 不在 12 种 result kind | 替换为 portfolio_risk 等合法 kind |
| 自动化"下次 16:30" | 无 next_run 字段 | 改用 `last_success_at` |
| "Hermes 已完成源码与说明"等过程文案 | 非 API 字段 | 保留为**前端静态文案模板**（按 kind/Gate 类型查字典），实现时集中在 copy.ts，不散落 |
| 问候语"早上好 + 有 N 件事" | 派生句 | 前端由 attention 数组长度 + state 派生（viewModel 已有 state 四态） |

## 4. 仅有的 3 处"派生呈现"（前端计算，不改接口）

1. **状态条**：4 个接口 read_status 的聚合展示（viewModel 层，同现有 deriveState 逻辑）。
2. **"待我处理"计数徽章**（导航上的 "2"）：`approvals.pending 数 + candidates 满足 candidateAttention 数`。
3. **kind→中文标题/文案字典**：approval、command、result 的 kind 到人类语言的映射，集中维护在前端 copy 层。

## 5. 实现时的防漂移纪律（建议写进 slice DoD）

- 所有类型从 `api.generated.ts` 导入，不手写接口类型；
- envelope `extra=forbid`——新增字段需求必须先改后端 schema 再重新生成，不在前端"先凑合"；
- `read_status` 五态/`sample_or_real`/`freshness` 的 fail-closed 映射沿用现有 normalize 层，UI 不自行解释原始值；
- 空态/降级/unavailable 的呈现从 `read_status` + `warnings[]` 派生，永不把不可用渲染成健康空态（F2 红线）；
- mutation 按钮的出现条件 = `mutation_enabled && status="pending"`，与 V7a CAS 规约一致。
