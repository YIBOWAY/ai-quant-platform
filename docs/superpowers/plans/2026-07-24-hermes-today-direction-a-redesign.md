# Slice UI-A：/hermes 今日页方向 A 重设计（F0 定稿 → 实施）

日期：2026-07-24　状态：**F0 定稿完成，待实施**
关联：D-31 spec §1.3/§3.1/§4.1（五秒测试、双状态、三级信息分层）；
`docs/superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md`（F0–F2 流程来源）。

---

## 1. 背景与问题

/hermes 首屏当前把 6 个 L/V 系列验收面板与 Today 内容同时堆在一个单列里
（`HermesLocalChatBoundary` 插在 `{children}` 之上），首屏 12–35 个等权信息块、
自动化状态与结果预览各重复渲染一次、无截断、无视觉锚点、tab 切换只改页面底部、
Composer 遮挡内容。用户实测"一打开不知道看什么"。

对照 D-31 spec：五秒测试 5 项中 3 项失败；§3.1 的"空闲=今日 COO 概览 /
活跃=对话+执行+结果工作区"双状态被实现成单态堆叠；§4.1"列表/表格/折叠详情
优先于大量同尺寸微卡片、同一 source 状态只出现一次"被违反。

## 2. F0 方向决策（用户已拍板，2026-07-24）

按 F0 流程产出 3 个有差异的高保真方向（1440/390 双档 + 有待处理/全部正常/部分降级/对话中四态）：

| 方向 | 定位 | 决策 |
|---|---|---|
| **A · COO 概览派** | 问候行+状态条 → 待我处理（唯一行动层）→ 运行中 → 最近结果 → Composer | ✅ **首发落地** |
| B · 交易台密度派 | 全表格化、mono 对齐、单屏尽览 | ❌ 放弃（前端表格族+断点+QA 代价最大；其"自动化 4-job 矩阵/Authority 健康表"作为后续可插拔模块备选） |
| C · 编辑叙事派 | 衬线单栏阅读流 | 🟡 保留为 `/brief` 晨报阅读体验 / "阅读模式"候选方向，不在本 slice |

定稿与设计证据：`docs/design/hermes-workbench/2026-07-24-direction-a/`
（demo 三向 HTML 可本地 `node demo/server.js` 打开；数据契约对照与三方向后端成本对比两份文档）。
方向 A 对应 `demo/index.html`；C 对应 `demo/c.html`（归档备查）；B 对应 `demo/b.html`（归档，不实施）。

## 3. 后端配合结论（合同校准后）

**零新接口、零 schema 变更、零 migration。** 全部数据来自现有 5 个 GET + workspace
脊柱（L/V 系列已验收）。逐字段映射与防漂移纪律见
`docs/design/hermes-workbench/2026-07-24-direction-a/2026-07-24-demo-data-contracts.md`。
实施期必须遵守其 §5：类型只从 `api.generated.ts` 导入；`extra=forbid` 不在前端凑合加字段；
`read_status`/`sample_or_real`/`freshness` 沿用现有 normalize fail-closed 映射；
mutation 按钮出现条件 = `mutation_enabled && status="pending"`（V7a 规约不变）。

已剔除的漂移设计：伪百分比进度条（spec §6.2 禁止）、不存在 next_run 字段
（改用 `last_success_at`）、非法 result kind（晨报不入结果列表）。

## 4. 实施切片划分

### Slice UI-1：Today 空闲态重构 + chrome 修复（本 slice）

范围（chat off 默认路径为主，chat on 时 Today 区同样生效）：

1. **页头**：问候行 + 派生摘要句（由 viewModel `state` + attention 计数派生；
   "系统正常，有 N 件事需要你处理" / 降级 / 全正常三变体）。
2. **状态条**（一行聚合）：Hermes gateway（新增消费 `GET /api/hermes/gateway`，
   并入 `page.tsx` 并行 fetch）+ artifact sources 聚合 + 自动化 healthy/total +
   （chat on 时）`authority_health.command_ledger`；右侧"系统状态 →"指向折叠的技术详情
   （现有 TechnicalDetails 保留，迁入此处）。
3. **待我处理**（唯一行动层，最高视觉权重）：candidates Gate 2 attention（现有
   candidateAttention 判定）+ 自动化 failure/stale + artifact offline/degraded，
   渲染为行动行（图标+标题+一句人话+meta+操作按钮）；chat on 且 snapshot 可用时
   并入 command approvals（V7a decide 按钮复用现有 CommandApprovals 逻辑，
   mutation off 时按钮不出现）。**无待处理时整区消失**（degraded 摘要句仍诚实）。
4. **运行中**（chat on 且有非终态 commands 时显示；chat off 诚实缺省）：
   紧凑行，state 事件文本，**无进度百分比**。
5. **最近结果**：合并现有 UnifiedResultsPreview + RecentResults 为一个区，
   `GET /api/hermes/results?limit=5`，紧凑行（display_title + kind 标签 + status pill
   + occurred_at + detail_href），"查看全部 →"链 `/hermes/results`。
   **删除 FocusedArtifactCard 的 automation 重复渲染**（同一 source 只出现一次）。
6. **自动化**：healthy 时一行收敛（"4/4 fresh · 上次成功 …"）；有异常时展开 4-job
   列表（status + reason_code + last_success_at）。
7. **Capability notice**：常驻大卡折叠为状态条下一行小字（delivery state 语义保留，
   不删除信息）。
8. **Composer 遮挡修复**：主内容区加 `padding-bottom ≥ composer 高度`；
   chat off 禁用态保留但视觉降权。
9. **加载态**：`page.tsx` 各区块拆 `<Suspense>` 边界 + 分块骨架，
   消除"空白 → 整页倾泻"；路由级 loading.tsx 保留为兜底。
10. **i18n**：遵循现有 copy={en,zh} 字典模式；视觉稿为中文，英文案同交。

明确不做（保持 dark/规约不变）：

- 不动 6 个 L/V 面板的数据源、spine、markers（`data-hermes-*` 全部保留）与 chat on 时
  面板的存在性；仅 UI-2 才调整其布局位置。
- 不动 public write / composer_readiness / mutation flags / kill_switch 任何语义。
- 不新增后端 endpoint；不动 `api.generated.ts`。
- 不动 Tasks/Approvals/Results/Sessions 子路由页面本体。
- 机器 ID 不外露原则：digest/candidate_id 继续只出现在详情/技术折叠内。

### Slice UI-2：活跃态双栏工作区（后续 slice，本 slice 不含）

chat on 时 6 面板从"堆在 Today 之上"改为"transcript 主栏 + 320px 上下文 rail
（当前任务/待确认/本次产出/系统）"，宽屏双栏、<1100px 单列；tab 切换滚动定位修复。
需先与 L3a–L5c 已验收 markers 对账（布局变更不动 marker 语义）。

### Slice UI-3：C 方向阅读模式（候选，仅登记）

将 `demo/c.html` 的编辑叙事方向应用于 `/brief` 晨报阅读体验；是否启动另立项。

## 5. DoD（Slice UI-1）

- [ ] 五秒测试可过：打开 /hermes 5 秒内能回答 安全/待处理/在跑/最近结果/从哪对话（chat off 与 on 各验一遍）。
- [ ] 四档视口 1440/1280/768/390 无横向溢出、无遮挡（Playwright 截图归档）。
- [ ] 四数据态渲染正确：normal / degraded（自动化 stale + sources degraded）/ unavailable（artifact feed 离线 → 聚合一行 + 技术详情，不出现错误墙）/ empty。
- [ ] 同一 source 状态只出现一次（自动化不再双渲染；结果不再双预览）。
- [ ] `data-hermes-*` markers 与现有 vitest 全绿；新增 UI 带对应测试（viewModel 派生 + 渲染契约）。
- [ ] `npm run build` 通过；console 0 error（fail-closed 路径的 500 仅在后端离线时由 BFF envelope 表达，不裸抛）。
- [ ] i18n 中英文案齐全；长文本/长 ID 不撑破布局。
- [ ] 诚实性红线：read_status 五态 fail-closed 呈现；sample/real 标记保留；无伪造进度；mutation off 时无任何决定按钮。

## 6. 测试计划

- 单测：`lib/hermes/viewModel.ts` 派生（状态条聚合、待我处理合并列表、自动化一行/展开判定）；
  组件渲染契约（vitest + Testing Library，沿用现有 `*.test.ts/tsx` 模式）。
- 视觉：Playwright 四档 × chat on/off × normal/degraded/unavailable 截图对比
  （对照 `docs/design/hermes-workbench/2026-07-24-direction-a/demo/index.html`）。
- 回归：现有 hermes 相关 vitest 套件 + 前端 build。

## 7. 回滚

纯 FE 展示层重构，无 schema/flag 变更；回滚 = revert 对应 commit。
不改 `featureFlags.ts` 任何默认值。

## 8. 当前阻塞（2026-07-24 记录）

平台工作树存在进行中的合并：`src/frontend/lib/hermes/workspaceFollowSpine.test.ts`
处于 `UU` 未解决冲突，且 ComposerDock/ComposerSubmitController/workspaceClient 等
有 staged 改动（他人/他会话在途工作）。**UI-1 实施前必须先确认工作树策略**：
建议新开独立 worktree/branch 实施，或待在途合并完成后再动手；
不得把 UI 改动混入未解决的合并状态。
