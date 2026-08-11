# D-34 本机自主 Paper 运维

## 状态边界

D-34 source 可以在不改正式数据库和 runtime 的情况下完成构建、测试与一次性 PostgreSQL
验收。以下三件事彼此独立：

1. source 合入 `main`；
2. migration 030–032 经单独授权 apply 到正式库；
3. owner runtime 设置 `QS_D34_WORKER_ENABLED=true` 并重启 stack。

前两项未完成时，保持 worker flag 为 false。LaunchAgent 即使已经安装也只输出
`state=disabled code=d34_worker_disabled`，不会读取数据库、启动容器或创建订单。

## 构建固定镜像

```bash
cd /Users/sunyibo/programs/ai-quant-platform
docker build --platform linux/arm64 \
  --tag hqa-d34-rdagent-qlib:0.1.0 \
  --file docker/d34/Dockerfile .

docker run --rm hqa-d34-rdagent-qlib:0.1.0 versions
docker run --rm hqa-d34-rdagent-qlib:0.1.0 qlib-smoke
docker run --rm --add-host host.docker.internal:host-gateway \
  hqa-d34-rdagent-qlib:0.1.0 futu-smoke
docker run --rm \
  --volume /var/run/docker.sock:/var/run/docker.sock \
  --env D34_IMAGE_REF=hqa-d34-rdagent-qlib:0.1.0 \
  hqa-d34-rdagent-qlib:0.1.0 docker-smoke
```

LLM/embedding smoke 只从权限 `0600` 的 owner-only env 文件注入真实配置，不把 secret 放进
命令或 Git。secret 使用 LiteLLM 原生 provider 变量（例如 `OPENAI_API_KEY`），模型选择使用
`LITELLM_CHAT_MODEL` / `LITELLM_EMBEDDING_MODEL`；不要把 secret 写入 RD-Agent 的
`LITELLM_*_API_KEY` 设置，因为 pinned 上游初始化日志会展开这些设置。

```bash
docker run --rm --env-file /absolute/owner-only/d34.env \
  hqa-d34-rdagent-qlib:0.1.0 llm-smoke
```

镜像使用开放本机模式：root、bridge、Docker socket、source/workspace/cache 读写挂载。
作业运行器只提供可配置超时、失败 receipt 和超时后的精确容器清理。

## Migration 授权窗口

正常 backend/LaunchAgent 启动永远保留 `QS_DATABASE_AUTO_MIGRATE=false`。先在一次性 PostgreSQL
从 001 顺序 apply 到 032，并用 runtime 最小权限跑 D-34 authority 集成测试。正式 apply
必须另行授权，且一次只允许精确文件：

```bash
quant-system migrate --apply --allow 030_d34_mandate_policy.sql --yes
quant-system migrate --apply --allow 031_d34_experiment_jobs.sql --yes
quant-system migrate --apply --allow 032_d34_artifact_canary.sql --yes
```

这些命令是操作格式，不是本文件授予的 apply 权限。029 和更早 migration 不重放。

## 启用常驻 worker

在 runtime 的 owner-only `data/_runtime/agent-v0.2-backend.env` 中写入：

```dotenv
QS_DATABASE_AUTO_MIGRATE=false
QS_D34_WORKER_ENABLED=true
D34_IMAGE_REF=hqa-d34-rdagent-qlib:0.1.0
QS_D34_HQA_ROOT=/absolute/runtime/Hermes-quant-agent
QS_D34_ENV_FILE=/absolute/owner-only/d34.env
```

`QS_D34_ENV_FILE` 是 worker 传给每个 research container 的同一份 `0600` LLM/embedding
配置；未配置时 container 会 fail closed，不能用 Hermes OAuth 配置或 sample response 冒充。

然后从 Platform runtime 运行：

```bash
bash scripts/local_mac_stack.sh start
bash scripts/local_mac_stack.sh status
tail -n 100 data/_runtime/logs/d34-worker.launchd.out.log
tail -n 100 data/_runtime/logs/d34-worker.launchd.err.log
```

`com.aiquant.d34-worker` 每五分钟只跑一次 bounded cycle，不依赖 Codex、Claude 或终端。
Mandate 未创建/暂停/过期、预算耗尽或 emergency stop 时，它保留已有 canary 估值，但不启动
新研究；paper 权限关闭时不创建或执行新订单。

## 日常检查

- `/api/safety/effective/v2`：Mandate、research/paper blockers、预算、配额、风险、emergency stop。
- `/api/hermes/research/jobs`：lease、attempt、heartbeat、terminal/outcome unknown。
- `/api/hermes/d34/artifacts`：双引擎与 policy 血缘。
- `/api/hermes/canaries`：allocated cash、P&L、drawdown、status/version。
- `/zh/hermes`：owner 工作台；这里没有 live upgrade 操作。

执行前会再次读取 durable emergency stop/Mandate。即使 pending plan 早于 stop 创建，也必须
转为 blocked，不能成交。日亏 2% 或回撤 10% 时先 pause 本地 sleeve，再以版本 CAS 写入
Registry；paused/demoted/rolled-back 的 held positions 仍继续估值。

## 停止与回滚

紧急事件使用工作台 emergency stop；它停止新研究和新 paper 订单，但不自动平仓。普通
停用把 `QS_D34_WORKER_ENABLED=false` 后重新运行 stack。D-34 rollback 会停止新 job，并把
active canary 收敛到 hold；默认不 flatten。D-33 的既有 sleeve 继续由原路径监控。

卸载 job：

```bash
bash scripts/uninstall_d34_worker_launchagent.sh
```

卸载只移除调度，不删除 Mandate、job、Artifact、canary、receipt、日志或持仓。
