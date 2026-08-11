# D-34 Mandate 与 Paper Canary 使用指南

这份指南面向本机唯一 owner。当前 source 分支可测试完整界面与 API；只有 migration 030–032
正式 apply、runtime fast-forward 且 `QS_D34_WORKER_ENABLED=true` 后，才是常驻运行态。

## 一次完整使用流程

1. 打开 `/zh/hermes`，找到“自主 Paper 研究”区。
2. 创建 Mandate。默认 30 天、`SPY/QQQ/IWM/DIA`、`1 x 3 x 3` 研究量、100 美元 LLM
   预算，并允许 paper execution；都可在创建时修改。
3. 在 Safety 区确认 research/paper blocker。emergency stop、过期/暂停 Mandate、预算耗尽或
   paper safety 失败会直接显示原因，不会再弹人工 Gate1/2/3。
4. 在 Research 区观察 job 的 queue、lease、heartbeat、attempt、预算和失败码。
5. 在 Artifact 区检查 snapshot/code/Qlib/Platform/comparison/policy 的 digest 血缘。
6. policy 通过后，Paper 区出现低额度 D-34 canary；继续观察持仓、P&L、回撤与状态。
7. 异常时使用 pause、demote 或 D-34 rollback。三者默认保留持仓并继续估值，不自动平仓。

## Owner API 观察

已有本地 owner cookie 的浏览器最方便；命令行观察可复用同一 cookie 文件：

```bash
curl --fail --cookie /absolute/owner-cookie.txt \
  'http://127.0.0.1:8765/api/safety/effective/v2?workspace_id=default'
curl --fail --cookie /absolute/owner-cookie.txt \
  'http://127.0.0.1:8765/api/hermes/research/jobs?workspace_id=default&limit=20'
curl --fail --cookie /absolute/owner-cookie.txt \
  'http://127.0.0.1:8765/api/hermes/d34/artifacts?workspace_id=default&limit=20'
curl --fail --cookie /absolute/owner-cookie.txt \
  'http://127.0.0.1:8765/api/hermes/canaries?workspace_id=default&limit=20'
```

不要把 owner cookie、CSRF token 或 LLM key 写进仓库。mutation 应优先从工作台执行；若用
API，必须同时携带现有 owner session 与 CSRF header，且 body 中提供当前 `expected_version`。

## 状态怎么理解

- `queued/leased/running`：研究仍在进行；重启由 durable lease/attempt 恢复。
- `succeeded`：研究、双引擎比较和 Registry 写入完成；不表示 live 资格。
- `rejected`：机器 policy 或不可恢复输入失败；不会创建 canary。
- `outcome_unknown`：容器或进程边界无法证明结果；恢复逻辑先对账，不盲重跑。
- `paused`：停止新订单，持仓保留并继续估值。
- `demoted/rolled_back`：不再参与新增 D-34 执行，held positions 仍可观察。

## 常见 blocker

| blocker | 处理 |
|---|---|
| `d34_worker_disabled` | 这是 source/部署默认状态；只在正式 migration 与 runtime 就绪后显式启用。 |
| Mandate missing/paused/expired | 在工作台创建、恢复或续期 Mandate。 |
| budget exhausted | 续期或创建新 Mandate；不手工改 ledger。 |
| emergency stop | 先查异常和持仓；确认后由 owner 明确解除。 |
| Futu unavailable/stale | 恢复 OpenD；系统不回退 sample/Yahoo/community dataset。 |
| Docker/LLM timeout | 查 job attempt 与 workspace receipt；恢复器会基于 lease/outcome 对账。 |
| digest/comparison reject | 检查 snapshot、target weight、calendar、费用与 receipt；不要运行中放宽 policy。 |

构建、migration、LaunchAgent、日志和回滚命令见
[D-34 本机自主 Paper 运维](../runbooks/d34-autonomous-paper.md)。
