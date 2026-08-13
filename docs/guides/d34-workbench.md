# D-34 Mandate 与 Paper Canary 使用指南

> **历史指南。** 产品身份见 HQA
> `docs/plans/2026-08-13-personal-quant-assistant.md`。
> 本文只说明已经落地的研究作业 / 试运行仓控件，不再定义「D-34 默认入口」。

这份指南面向本机唯一 owner。2026-08-12 的本地 runtime 已完成 source/main/runtime 对齐、
migration 030–032 一次性 apply、完整 preflight 和常驻 worker 启用；首个完整周期与 canary
已运行。当前自然验收为 `1/10` 周期、`1/5` 观察日，默认研究入口仍为 D-33。新的安装仍须
依次完成 source 验收、migration 授权、runtime fast-forward、preflight 与显式 worker 启用。

## 一次完整使用流程

1. 打开 `/zh/hermes`，找到“自主 Paper 研究”区。
2. 创建 Mandate。默认 30 天、`SPY/QQQ/IWM/DIA`、`1 x 3 x 3` 研究量、100 美元 LLM
   预算，并允许 paper execution；都可在创建时修改。
3. 在 Safety 区确认 research/paper blocker。emergency stop、过期/暂停 Mandate、预算耗尽或
   paper safety 失败会直接显示原因，不会再弹人工 Gate1/2/3。
4. 在 Research 区观察 job 的 queue、lease、heartbeat、attempt、预算和失败码。
5. 在 Artifact 区检查 snapshot/code/Qlib/Platform/comparison/policy 的 digest 血缘。
6. policy 通过后，Paper 区出现低额度 D-34 canary；继续观察持仓、P&L、回撤与状态。
7. “运行验收进度”同时显示当前默认研究入口。时间门达标后仍须有最终零重复/零 live
   eligibility receipt，才会从 D-33 切为 D-34；D-33 旧 sleeve 维护不会停止。
8. 异常时使用 pause、demote 或 D-34 rollback。三者默认保留持仓并继续估值，不自动平仓；
   rollback 还会一键恢复 D-33 新 intake。

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
- `outcome_unknown`：容器或进程边界无法证明结果；保留 receipt 等待核对，不盲重跑。
- `paused/awaiting_registry`：sleeve 已落库但 Registry 尚未确认；重试完成登记后才允许恢复。
- `paused`：停止新订单，持仓保留并继续估值。
- `demoted/rolled_back`：不再参与新增 D-34 执行，held positions 仍可观察。
- `research_routing.default_research_entry`：当前新研究入口；`d33` 表示尚未切换或已经回退，
  `d34` 表示时间门与最终验收 receipt 均已通过。`d33_maintenance_enabled=true` 表示旧 D-33
  sleeve 仍在五分钟维护周期内。

## 常见 blocker

| blocker | 处理 |
|---|---|
| `d34_worker_disabled` | 这是 source/部署默认状态；只在正式 migration 与 runtime 就绪后显式启用。 |
| `d34_env_file_required` | 创建 owner-only `0600` provider env，并由 `QS_D34_ENV_FILE` 指向它。 |
| `d34_env_models_required` | 显式设置非空 `LITELLM_CHAT_MODEL`。本地默认经 Hermes xAI OAuth 代理调用 Grok，不需要单独 embedding 服务。 |
| `d34_env_logged_secret_forbidden` | 将 secret 从会被 RD-Agent 展开的 `LITELLM_*` setting 移到 provider 原生变量。 |
| `runtime_preflight_failed` | 读取 preflight JSON 错误并修复 DB/live、LLM、Qlib、Futu 或 Docker seam；不得跳过后启用。 |
| Mandate missing/paused/expired | 在工作台创建、恢复或续期 Mandate。 |
| budget exhausted | 续期或创建新 Mandate；不手工改 ledger。 |
| emergency stop | 先查异常和持仓；确认后由 owner 明确解除。 |
| Futu unavailable/stale | 恢复 OpenD；系统不回退 sample/Yahoo/community dataset。 |
| Docker/LLM timeout | 查 job attempt 与 `workspace/jobs/<job_id>/docker_failure.json`；原始输出不写入 receipt。 |
| digest/comparison reject | 检查 snapshot、target weight、calendar、费用与 receipt；不要运行中放宽 policy。 |

构建、migration、LaunchAgent、日志和回滚命令见
[D-34 本机自主 Paper 运维](../runbooks/d34-autonomous-paper.md)。
