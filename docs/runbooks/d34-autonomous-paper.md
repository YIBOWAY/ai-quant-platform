# D-34 本机自主 Paper 运维

## 状态边界

D-34 source 可以在不改正式数据库和 runtime 的情况下完成构建、测试与一次性 PostgreSQL
验收。以下三件事彼此独立：

1. purpose worktree 完成验收并 fast-forward 合入 `main`；
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

LLM JSON smoke 只从权限严格为 `0600` 的 owner-only 普通文件注入真实配置；symlink、
目录、组/其他用户可读写的文件都会 fail closed。不要把 secret 放进
命令或 Git。secret 使用 LiteLLM 原生 provider 变量（例如 `OPENAI_API_KEY`），模型选择使用
`LITELLM_CHAT_MODEL`；不要把 secret 写入 RD-Agent 的
`LITELLM_*_API_KEY` 设置，因为 pinned 上游初始化日志会展开这些设置。

```bash
docker run --rm --env-file /absolute/owner-only/d34.env \
  hqa-d34-rdagent-qlib:0.1.0 llm-smoke
```

可从 `docker/d34/.env.example` 复制变量名。本地默认由常驻 Hermes xAI OAuth 代理把
`grok-4.5` 以 OpenAI-compatible 协议提供给容器；当前研究链不依赖单独 embedding
服务。启用入口会在启动容器前验证 chat 模型为显式非空值，并拒绝
`LITELLM_*_KEY|TOKEN|SECRET|PASSWORD`；provider secret 应继续使用 LiteLLM 原生变量，
例如 `OPENAI_API_KEY`。这些检查只读取变量名和是否为空，不输出 secret。

镜像使用开放本机模式：root、bridge、Docker socket、source/workspace/cache 读写挂载。
作业运行器只提供可配置超时、失败 receipt 和精确容器清理。失败凭证位于
`workspace/jobs/<job_id>/docker_failure.json`，只记录 image/command、返回码、输出字节数与
SHA-256、容器清理结果，不把可能含 secret 的 stdout/stderr 原文写入凭证。

每次 container 前后都会读取 Platform/HQA 的 Git porcelain status 与 tracked binary diff。
如果挂载仓库在作业期间发生变化，运行器保留现场并写入
`workspace/jobs/<job_id>/repository_anomaly.json`；它不会 reset、删除或自动提交。作业开始前
已经存在且全程未变化的 dirty 也会进入 Docker receipt，但不会被误报为本次作业造成的变化。

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

## Source worktree 验收

purpose worktree 复用主 checkout 的 Python 3.11 `.venv` 时，必须显式把 worktree 的 `src`
放到 `PYTHONPATH`；否则 editable install 会静默导入主 checkout，造成假验收：

```bash
cd /Users/sunyibo/programs/.worktrees/d34/ai-quant-platform
PYTHONPATH="$PWD/src" /Users/sunyibo/programs/ai-quant-platform/.venv/bin/pytest -q
/Users/sunyibo/programs/ai-quant-platform/ai-quant/bin/ruff check src tests
```

验收解释器必须是 Python 3.11。不要在 worktree 裸跑 `uv run` 创建一个无意的 `.venv`，也
不要使用旧 `ai-quant` 环境中的 Python 3.12 运行冻结 release tests。

## 启用常驻 worker

在 runtime 的 owner-only `data/_runtime/agent-v0.2-backend.env` 中写入：

```dotenv
QS_DATABASE_AUTO_MIGRATE=false
QS_D34_WORKER_ENABLED=true
D34_IMAGE_REF=hqa-d34-rdagent-qlib:0.1.0
QS_D34_WORKER_PYTHON=/absolute/python-3.11-venv/bin/python
QS_D34_HQA_ROOT=/absolute/runtime/Hermes-quant-agent
QS_D34_ENV_FILE=/absolute/owner-only/d34.env
```

`QS_D34_ENV_FILE` 是 worker 传给每个 research container 的同一份 `0600` LLM
配置。默认配置指向宿主机 Hermes xAI OAuth 代理，不需要复制 OAuth token 进容器。
`QS_D34_WORKER_PYTHON` 必须精确指向 Python 3.11；runner 会拒绝显式配置的其他 minor，自动
发现时也只选择 3.11，避免 purpose worktree 验收使用 3.11、LaunchAgent 却落到旧 3.12 venv。

启用态必须先运行完整 preflight：

```bash
bash scripts/run_d34_worker.sh --check
```

当 `QS_D34_WORKER_ENABLED=true` 时，`--check` 会读取正式 D-34 authority 与
`live_execution_enabled=false`，并在同一个 pinned container 中真实执行 versions、Qlib
backtest、LLM JSON mode、Futu socket 和 Docker child smoke。它会产生少量 provider
调用成本，但不会创建 Mandate/job/Artifact/sleeve/order，也不会 apply migration。成功 receipt
原子写入 `data/_runtime/d34/preflight/latest.json`（`0600`）；任一 seam 未通过都会以
`runtime_preflight_failed` 阻止 LaunchAgent 安装或重载。worker disabled 时，`--check` 只验证
Python/source import，不接触数据库、provider 或 Docker。

然后从 Platform runtime 运行：

```bash
bash scripts/local_mac_stack.sh start
bash scripts/local_mac_stack.sh status
tail -n 100 data/_runtime/logs/d34-worker.launchd.out.log
tail -n 100 data/_runtime/logs/d34-worker.launchd.err.log
```

`com.aiquant.d34-worker` 每五分钟只跑一次 bounded cycle，不依赖 Codex、Claude 或终端。
Mandate 未创建/暂停/过期、预算耗尽或 emergency stop 时，它保留已有 canary 估值，但不启动
新研究；paper 权限关闭时不创建或执行新订单。新 snapshot/research 只在上海时区周二至
周六 06:00 以后启动；canary 估值、paper 计划维护和 terminal recovery 每轮仍会执行。

## 日常检查

- `/api/safety/effective/v2`：Mandate、research/paper blockers、预算、配额、风险、emergency stop。
- `/api/hermes/research/jobs`：lease、attempt、heartbeat、terminal/outcome unknown。
- `/api/hermes/d34/artifacts`：双引擎与 policy 血缘，并返回 correlation、NAV/weight 差异。
- `/api/hermes/canaries`：allocated cash、P&L、drawdown、status/version；持仓与现金仍以
  `/api/paper/strategy-sleeves/{sleeve_id}` 为权威来源。
- `/zh/hermes`：owner 工作台；汇总比较指标、限额、canary P&L、现金和持仓，这里没有 live
  upgrade 操作。

执行前会再次读取 durable emergency stop/Mandate。即使 pending plan 早于 stop 创建，也必须
转为 blocked，不能成交；并且会按实际 next-open 价格、实际订单金额和当前账户/其他 D-34
sleeve 暴露重新执行统一 Policy，防止多个旧计划累计越过单标的 5% 上限。日亏 2% 或回撤
10% 时先 pause 本地 sleeve，再以版本 CAS 写入 Registry；paused/demoted/rolled-back 的
held positions 仍继续估值。新 canary 在 Registry 写成功前保持 `paused/awaiting_registry`。
D-34 实际执行前的 accepted/rejected order-batch 决策会追加写入 `d34_policy_decisions`；审计
写入失败时订单保持 blocked，不能出现“成交成功但没有确定性 policy 记录”的状态。

## 停止与回滚

紧急事件使用工作台 emergency stop；它停止新研究和新 paper 订单，但不自动平仓。普通
停用把 `QS_D34_WORKER_ENABLED=false` 后重新运行 stack。D-34 rollback 会暂停当前 Mandate、
取消 queued job 并释放对应预算预留，再把 active canary 收敛到 hold；默认不 flatten。
D-33 的既有 sleeve 继续由原路径监控。

卸载 job：

```bash
bash scripts/uninstall_d34_worker_launchagent.sh
```

卸载只移除调度，不删除 Mandate、job、Artifact、canary、receipt、日志或持仓。
