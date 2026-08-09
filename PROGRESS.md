# PROGRESS
- 2026-07-28 任务 0 完成：已读权威文档、TDD/深模块规则并核对当前 diff。
- 目标：Brief 显示真实持仓日涨跌及 Paper/SPY/QQQ 的 7d/1m/3m 可复现收益曲线。
- 顺序：Futu 日线缓存与昨收 → 账本 performance API → Brief/归档 → 全部验收。
- 最大风险：不能把交易事件曲线或不规则审计快照伪装成每日净值。
- 基线：P=86 passed/6 skipped；U=57 files/324 tests；lint 仅 1 条既有 warning；R=green。
- 已知同域红灯：Brief E2E 因 source_watermark 额外字段契约不一致失败；D 因 brief schema EOF 空行失败。
- 已知域外红灯：全量 Ruff 另有 173 个 Hermes 错误；不在本目标修复范围。
- 开工前用户脏改已由 `git status --short --branch` 与 `git diff --stat` 留证，禁止覆盖。

## 闸门 1
- RED 证据：新增日涨跌测试先报 `KeyError: previous_close`；缓存测试先报模块不存在。
- GREEN：Futu snapshot 保留昨收；持仓缺昨收返回 null；DuckDB 缓存严格绑定 provenance/window。
- 验收：P=94 passed/6 skipped；R=green。进入闸门 2。

## 闸门 2
- RED 证据：performance 路由先由 404 变为受控 422；随后分别暴露模块缺失、Paper `as_of` 错用账本时间、基准/持仓/partial warning 缺失。
- GREEN：新增只读 performance 服务与 API；以账本回放现金/仓位/佣金，以 Futu QFQ 日线收盘估值，并把 Paper/SPY/QQQ 重置到共同首日 0%。
- 失败边界：SPY/QQQ 独立降级；持仓历史价缺失时 Paper fail closed，不用成本价或 sample 补齐；账户窗口中途建立时显式 partial。
- 持久化：GET 仅可懒写 `api_runs/_cache/futu_equity_bars.duckdb` 行情缓存；账户读取继续走 repository factory 且不创建缺失账户。
- 验收：目标 P 组全绿（含 6 skipped）；目标 R=green。进入闸门 3。

## 闸门 3
- GREEN：Brief 账户表格显示语义化日涨跌；收益区支持 7d/1m/3m 和 Paper/SPY/QQQ 三线，移动端与桌面端共用真实日期轴。
- 归档：显式保存时写入 3m master 与 selected range；历史页从 snapshot 截取并重新归零，不重新调用实时行情；旧 `brief_snapshot_v1` 无 performance/null performance 均兼容。
- 独立审阅修复：已禁止持仓缺少某个交易日价格时前向填充；3m master API 请求失败时会阻止新归档，不再静默保存缺 performance 的新版 snapshot。
- 现金流：daily TWR 在外部资金事件前后以 exact common close 分段并重置基数；收盘前用上一交易日，16:00 整点用当日收盘，缺 mark fail closed。两轮旧算法分别以 20%/17.5625% 红灯，修复后为 10%/21%。
- 契约：新增字段保持 additive；公共 position `weight` 未删除；现有 archive schema version 不升级。
- 浏览器：`QS_FUTU_ENABLED=false`、隔离 8766/3002 的 Playwright 1 passed；行情来自已有严格缓存，未触发 live Futu；实际走过 7d→3m→1m，1440px 与 390px 均无 document horizontal overflow，截图已人工复核。现有 8765/3001 未重启、未作为新代码证据。

## 最终验收
- P：目标 112 项，106 passed / 6 skipped。
- R：目标 Python 路径 `All checks passed!`。
- U：57 files / 329 tests passed；TypeScript type-check passed；Brief 白名单 scoped ESLint
  通过。2026-07-28 重新执行全量 ESLint 退出 0：0 errors，仅保留 1 条既有且域外的
  Hermes hook warning。
- E：Brief isolated Playwright 1 passed。
- D：目标工作区 `git diff --check` passed。
- 文档：`docs/guides/paper-trading.md` 与 delivery record 已同步；`BLOCKED.md`
  已更新为 CLOSED。

## CLOSED
- 2026-07-28：任务 1—3 与 P/R/U/E/D 全部满足完成条件，目标正式收口。
- 部署边界：用户确认前端已同步至 launchd release worktree、构建重启并通过浏览器
  验证；本轮没有反向同步前端。后端 Python 改动尚未部署，线上 performance API
  暂时 404 并由前端 fail closed 显示 `--`；后端部署不属于本轮收口动作。
