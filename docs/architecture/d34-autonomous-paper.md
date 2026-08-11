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
Artifact、canary、预算和 order 都必须幂等。

030–032 只能在单独授权的 operator window 正式 apply。普通 backend、stack 或 LaunchAgent
启动不迁移数据库。

## 执行与恢复

五分钟 LaunchAgent 每次只运行一个 bounded cycle：

1. 估值所有 D-34 running/paused/demoted/rolled-back held positions，并写 P&L/回撤 observation。
2. 在执行前重新读取 emergency stop、Mandate 和 paper safety；旧 pending plan 不能穿透新 stop。
3. 在 next-open 窗口生成/执行 D-34 paper plan。
4. 恢复 expired lease/outcome-unknown job，或创建下一次 Futu snapshot/research job。
5. 容器 timeout 留下精确 receipt 并只清理本次容器；不会 reset、删除或提交 repo dirty。

日亏 2% 或回撤 10% 时先 pause sleeve，再以版本 CAS 更新 canary。pause/demote/rollback 默认
hold，不自动 flatten；held positions 继续估值。

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

D-33 继续监控已有 sleeve。D-34 rollback 停止新 job、把 D-34 canary 变为 hold；不会删除
Artifact/receipt，也不会声称已经平仓。
