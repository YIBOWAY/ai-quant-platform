# D-34 自主 Paper 架构

D-34 是本地单 owner 的研究与模拟执行闭环。它把一个 30 天 Mandate 转成可恢复的研究
job、双引擎证据、`paper_only` Artifact 和低额度 canary；它没有 live 注册或升级接口。

## 数据流

```text
Mandate
  -> Futu 1d QFQ Parquet snapshot + manifest + digest
  -> RD-Agent proposal / generated factor
  -> Qlib factor research + target weights + receipt
  -> Platform fill/fee/position/NAV replay + receipt
  -> deterministic comparison and policy decision
  -> Artifact Registry
  -> PaperExecutionPolicy
  -> automation-managed D-34 sleeve/canary
  -> next-open signal/fill + valuation/risk observation
```

Futu Parquet 是市场数据权威，Qlib provider URI 只是可重建缓存。派生 cache 的
`day_future.txt` 只追加一个无行情的 exclusive boundary sentinel，供 Qlib 结束最后一个
已收盘日的回测；它被 provider/receipt digest 绑定，不进入 snapshot、收益序列或 Platform
replay。两个引擎消费相同的 snapshot、universe、calendar 和 target-weight digest。Platform 不复制因子公式，而是独立
重放成交、费用、持仓和 NAV。初始 policy 要求收益相关性至少 `0.995`、期末 NAV 差不超过
`25 bps`、单标的权重差不超过 `50 bps`；阈值变化必须生成新 policy digest。

## PostgreSQL 权威

| Migration | 主要权威表 |
|---|---|
| `030_d34_mandate_policy.sql` | `d34_mandates`、`d34_mandate_events`、`d34_policy_decisions`、`d34_execution_authority_events` |
| `031_d34_experiment_jobs.sql` | `d34_experiment_jobs`、`d34_experiment_attempts`、`d34_job_events`、`d34_budget_events` |
| `032_d34_artifact_canary.sql` | `d34_engine_receipts`、`d34_comparisons`、`d34_artifacts`、`d34_artifact_events`、`d34_canaries`、`d34_canary_events` |

事件、receipt 和 budget ledger 是 append-only；mutable aggregate 使用 version/CAS。job 状态为
`queued -> leased -> running -> succeeded|rejected|outcome_unknown|cancelled`。job key、attempt、
Artifact、canary、预算和 order 都必须幂等。租约发放在锁定 Mandate 后按
`max_concurrent_jobs` 计数，避免多个 worker 越过 Mandate 并发上限。

030–032 只能在单独授权的 operator window 正式 apply。普通 backend、stack 或 LaunchAgent
启动不迁移数据库。

## 执行与恢复

五分钟 LaunchAgent 每次只运行一个 bounded cycle：

1. 估值所有 D-34 running/paused/demoted/rolled-back held positions，并写 P&L/回撤 observation。
2. 在执行前重新读取 emergency stop、Mandate 和 paper safety；旧 pending plan 不能穿透新 stop。
3. 在 next-open 窗口生成/执行 D-34 paper plan；使用实际开盘价和实际订单金额重新运行
   `PaperExecutionPolicy`，不能只依赖创建计划时的旧判断。
4. 已完成研究但尚未写完 Artifact/canary 的 terminal phase 可幂等恢复；过期 lease 收敛为
   `outcome_unknown` 并保留凭证供核对，不盲目重跑无法证明结果的研究。
5. 只有上海时区周二至周六 06:00 以后才会刷新 Futu snapshot 或启动新研究；估值、订单维护
   和 terminal recovery 不受这个研究窗口限制。
6. 容器 timeout/启动失败留下 `workspace/jobs/<job_id>/docker_failure.json`，记录 image、命令、
   return code、stdout/stderr 长度与 digest 以及精确容器清理结果，不保存可能含 secret 的原始日志。

日亏 2% 或回撤 10% 时先 pause sleeve，再以版本 CAS 更新 canary。pause/demote/rollback 默认
hold，不自动 flatten；held positions 继续估值。新 canary 先以 `paused/awaiting_registry`
持久化，Registry 记录成功后才 resume，避免进程崩溃留下未登记但已可成交的 sleeve。

`paper-execution-policy/v2` 保留 D-33 的单 sleeve 40% 分散化限制；D-34 的研究语义是
`top_k=1`，因此不套用该旧限制，而是由单 sleeve 1%、自动 sleeve 合计 10% 和账户级单标的
合计 5% 约束。所有 D-33/D-34 订单仍走同一个 policy evaluator。

## 本地 owner API

| 方法 | 路径 | 用途 |
|---|---|---|
| POST/GET | `/api/hermes/mandates` | 创建或列出 Mandate |
| GET | `/api/hermes/mandates/active` | 当前有效 Mandate |
| POST | `/api/hermes/mandates/{id}/pause|resume|revoke|renew` | version/CAS 生命周期操作 |
| GET | `/api/hermes/research/jobs` | job、lease、attempt 与 outcome |
| GET | `/api/hermes/d34/artifacts` | D-34 双引擎血缘；旧统一 Artifact API 保持不变 |
| GET | `/api/hermes/canaries` | canary、额度、P&L 与回撤 |
| POST | `/api/hermes/canaries/{id}/pause|demote` | hold 型控制 |
| POST | `/api/hermes/d34/rollback` | 停止新 job 并收敛 D-34 canary |
| GET | `/api/safety/effective/v2` | Mandate、研究/paper blockers、预算、配额和风险 |
| POST | `/api/safety/emergency-stop` | 立即阻止新研究与新 paper 订单 |

GET 和 mutation 都要求当前本地 owner session；mutation 还要求现有 CSRF 与 owner rate-limit。
这些接口不会改变 public release，也没有 live mutation。

## Source、runtime 与回退

开发只发生在主 checkout 或 purpose-named source worktree。runtime clone 只允许 fetch/ff-only。
`QS_D34_WORKER_ENABLED=false` 是部署默认值：即使 LaunchAgent 安装，也不会读取 D-34 表、启动
容器或创建订单。D-34 合回 main、030–032 获得正式 apply 授权并完成 runtime fast-forward 后，
operator 才能显式启用。

D-33 继续监控已有 sleeve。D-34 rollback 会暂停当前 Mandate、取消仍 queued 的 job、释放其
预算预留，并把 D-34 canary 变为 hold；不会删除 Artifact/receipt，也不会声称已经平仓。
