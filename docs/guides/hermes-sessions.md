# Hermes 会话读取：运行手册与威胁模型

## 当前结论（2026-07-16）

平台已经能通过 **official Hermes API Server** 读取本机已保存的 Hermes 会话：

```text
浏览器
  -> Next 页面（127.0.0.1:3001）
    -> 平台 API/BFF（127.0.0.1:8765）
    -> server-side GET-only adapter
      -> official Hermes API Server（http://127.0.0.1:8642）
        -> Hermes 已保存会话
```

这是会话观察面，不是完整 chat bridge：

- 已开放：gateway/capability 状态、session list、session detail、经过过滤的 messages。
- 未开放：run/chat submission、SSE 执行流、approval mutation、stop、完整 Unified
  Results cutover、旧研究页 redirect/删除。
- 前端能力位：`sessionRead=true`；`chat=false`、`execution=false`、
  `approvalMutations=false`、`legacyRedirects=false`。Unified Results 只读
  preview/catalog 已可见，但 `unifiedResultsCutoverAccepted=false`。
- health、capabilities 与 session GET 不提交 prompt、不调用 Hermes provider，因而不消耗
  Hermes 当前配置的 Codex、Grok 或其他 provider 额度。
- 本切片没有新增 PostgreSQL migration，也没有把 Hermes 会话复制进平台数据库；
  页面读取的是 Hermes 自己的已保存会话。

旧的 TUI gateway capability contract 已随上游实现漂移并 fail closed。它只保留历史/
诊断价值，平台的现行主读取链路是 official API Server。

## 启用条件

1. official Hermes API Server 必须监听显式 loopback HTTP origin，默认是
   `http://127.0.0.1:8642`。
2. Hermes API Server 已配置一个独立 Bearer key。
3. 平台用同一个 key 的本地文件读取凭据；文件必须是当前进程用户拥有的普通文件，
   不能是 symlink，权限为 `0600` 或更严格，内容非空且不超过 4096 bytes。
4. 平台后端必须绑定 `127.0.0.1` 或 `::1`。当前平台 API 没有多用户认证层，启用
   Hermes 会话读取时不得以 `0.0.0.0`/LAN-public 方式暴露。

使用受支持的 `quant-system serve --host 127.0.0.1` 会同步可信 bind 声明。若直接启动
ASGI factory，则还必须显式设置 `QS_API_BIND_ADDRESS=127.0.0.1`；未声明时集成拒绝启动，
每个请求还会核验实际 ASGI server socket，不能只靠 Host header 或错误 env 声明放行。

准备专用文件（不要把真实 key 写入命令行参数、shell history、Git 或浏览器）：

```bash
cd /Users/sunyibo/programs/Hermes-quant-agent
install -d -m 700 data/_runtime
if [ ! -e data/_runtime/hermes-api.key ]; then
  install -m 600 /dev/null data/_runtime/hermes-api.key
fi
```

随后用可信的本地编辑器或密码管理器把 Hermes API Server 的 key 粘贴进
`/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/hermes-api.key`（该运行时目录已
gitignore），再确认：

```bash
chmod 600 data/_runtime/hermes-api.key
test "$(stat -f '%Lp' data/_runtime/hermes-api.key)" = 600
```

不要用 `echo <真实密钥>`，也不要把 Bearer header 放进浏览器 DevTools。轮换 key 时必须
同时更新 Hermes API Server 配置和这个文件，重启 Hermes API Server 后再做下述检查。

## 平台配置与启动

以仓库绝对路径配置 key file：

```bash
export QS_HERMES_GATEWAY_ENABLED=true
export QS_HERMES_GATEWAY_BASE_URL=http://127.0.0.1:8642
export QS_HERMES_GATEWAY_API_KEY_FILE=/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/hermes-api.key
export QS_HERMES_GATEWAY_TIMEOUT_SECONDS=2
export QS_HERMES_GATEWAY_MAX_RESPONSE_BYTES=4194304
export QS_HERMES_GATEWAY_MAX_MESSAGES=200

quant-system serve --host 127.0.0.1 --port 8765
```

前端仍按通常方式绑定 loopback：

```bash
cd /Users/sunyibo/programs/ai-quant-platform/src/frontend
npm run dev -- --hostname 127.0.0.1 --port 3001
```

配置默认关闭。未启用、上游离线、key 错误或响应不符合合同，BFF 会返回
`read_status=unavailable` 及无秘密 warning；不会伪装成“空会话”，也不会自动切换到旧
TUI bridge。

## 验证

先只访问平台 BFF，不要把 Hermes key 交给 `curl` 或浏览器：

```bash
curl -fsS http://127.0.0.1:8765/api/hermes/gateway
curl -fsS 'http://127.0.0.1:8765/api/hermes/sessions?limit=5&offset=0'
```

gateway 正常时应看到：

- `connected=true`
- `session_api_available=true`
- `read_status=available`
- `chat_write_ready=false`
- `platform_delivery_blockers` 含 permanent cutover/security 码（如
  `authenticated_mutation_bff_unavailable`、`research_workflow_submission_unavailable`、
  `independent_security_review_unavailable`、`user_chat_cutover_approval_required`）以及
  schema 未就绪时的动态码（binding 未就绪时含 `command_dispatch_adapter_unavailable`）；
  **不含**已实现的 `csrf_protection_unavailable`；`dark_dispatch_ready` 不打开 public write
- `blockers` 仍合并 upstream 写端可靠性缺口与 platform blockers

从 sessions 响应选择一个真实 `id` 后，可以验证：

```bash
curl -fsS 'http://127.0.0.1:8765/api/hermes/sessions/<URL_ENCODED_ID>'
curl -fsS 'http://127.0.0.1:8765/api/hermes/sessions/<URL_ENCODED_ID>/messages'
```

最后用浏览器检查：

- `http://127.0.0.1:3001/zh/hermes/sessions`
- `http://127.0.0.1:3001/zh/hermes/sessions/<URL_ENCODED_ID>`

详情页只显示 `user` / `assistant` 文本消息，composer 必须保持 disabled。system/tool/
reasoning 等上游消息不会透传；消息数受 `QS_HERMES_GATEWAY_MAX_MESSAGES` 限制，响应以
`omitted_message_count` 说明被省略数量。

这里没有 DLP/秘密扫描：user/assistant 文本会按原内容限长展示。若用户曾把 key、token 或
其他敏感文本粘贴进对话，它仍可能出现在详情页；不要把会话观察面当作脱敏归档。

## BFF 固定合同

| 平台路由 | 上游读取 | 能否触发 provider |
|---|---|---|
| `GET /api/hermes/gateway` | capabilities | 否 |
| `GET /api/hermes/sessions` | persisted session list | 否 |
| `GET /api/hermes/sessions/{session_id}` | persisted session detail | 否 |
| `GET /api/hermes/sessions/{session_id}/messages` | persisted messages | 否 |

adapter 没有 generic request 或 POST 方法。它只接受显式 HTTP loopback origin，关闭
environment proxy (`trust_env=false`) 和 redirects，限制超时/响应 bytes/message count，
并拒绝包含 slash、backslash、dot-segment、drive prefix、控制字符或超长内容的 session
ID。当前会话页只经平台 API/BFF 读取，从不接触上游 URL 或 Bearer key；开发态
`3001` 与 `8765` 是两个 loopback origin，不能把它们描述为已经具备同源认证。

## 威胁模型

### 保护对象

- Hermes full-authority API Bearer key。
- 本机 Hermes 会话标题、消息与可能包含的研究信息。
- 平台只读/模拟边界，以及 Scene-B 三道人工 Gate 的来源证明。

### 信任边界

- **浏览器不是 key 信任域。** key 只存在于 Hermes server 配置和平台后端 owner-only
  文件；不得出现在 JavaScript bundle、HTML、API response、日志或截图中。
- **loopback 是网络边界，不是 OS 用户认证。** 同一台机器上其他用户/进程是否可访问，
  取决于 OS 权限与进程隔离；不能把 `127.0.0.1` 当成应用身份认证。
- **平台 BFF 当前面向单用户本地部署。** 在没有用户认证、会话授权和 CSRF 保护前，
  不得公开绑定或反向代理到 LAN/公网。
- **Hermes 响应是不可信输入。** BFF 只投影 allowlisted 字段，过滤角色、校验 ID/类型、
  标准化 timestamp 并施加长度上限。

### 明确不提供的安全保证

- 不保证同机恶意高权限进程无法读取当前用户的会话或内存。
- 不把 upstream `run_submission=true` 等 capability 当作平台可安全写入的充分证明。
- 不以 ticker/source 相似度替代 Gate 1/2/3 的精确 candidate/digest/receipt 绑定。
- 不把 upstream 404、超时、认证失败或 malformed response 解释为健康空状态。

## 常见故障

| 表现 / warning code | 检查 |
|---|---|
| `integration_disabled` | 设置 `QS_HERMES_GATEWAY_ENABLED=true` 后重启平台后端。 |
| `invalid_endpoint` | URL 必须是带端口、无 path/query/userinfo 的 `http://127.0.0.1:...` 或 `http://[::1]:...`。 |
| `api_key_file_missing` / `api_key_file_invalid` | 使用绝对路径；确认普通文件、非 symlink、当前用户可读。 |
| `api_key_file_permissions` / `api_key_file_owner` | 修复 owner，并设置 `chmod 600`；不要放宽到 group/world readable。 |
| `upstream_auth_failed` | Hermes server 与 key file 不一致；安全轮换后重启 Hermes，再重试 BFF。 |
| `upstream_unavailable` / `upstream_timeout` | 确认 official API Server 正在 loopback:8642 监听；不要改接旧 TUI port。 |
| `session_resources_unavailable` | 当前 Hermes capability 没有明确声明 persisted session resources；保持 fail closed。 |
| 页面“读取不可用” | 先看 `/api/hermes/gateway` warning，再看后端日志；不要通过启用 composer 绕过。 |

## Wave 3 / V5–V6 底座：成熟写端连接，而不是空轮询

下图是目标链路。当前 live 已启用 PostgreSQL migration 005 transport ledger + 006/007
workflow-binding/session-registry、session BFF，以及 deterministic connector worker。
**V5（2026-07-21）** 交付 dark `supervised_dispatch` + crash matrix。
**V6 本地授权（2026-07-21）** 在纯本地单用户前提下打开了此前 OFF 的四项：真实
`HttpHermesDispatchAdapter`、CLI `--mode supervised_dispatch`、provider smoke、
settings-gated local mutation / composer 就绪位。**交易**仍 fail-closed
（`kill_switch=true` / `dry_run` / `paper` / `live_trading_enabled=false`）。

```text
Browser (QS_HERMES_CHAT_ENABLED + owner cookie/CSRF)
  -> same-origin BFF
       POST /api/agent/workspace/submit-turn  (L2a composite)
         -> HQA Intent Payload Store put (subprocess CLI)
         -> PostgreSQL command/outbox/event (conversation_turn + payload ref)
  -> connector-worker --mode supervised_dispatch
       -> bind_resolve payload -> HttpHermesDispatchAdapter POST /v1/runs
  -> Browser observe (L2b)
       GET …/snapshot + …/follow  (lifecycle; no assistant bodies)
       after delivered: GET /api/hermes/sessions/{id}/messages (preview)
```

Worker 模式：

| mode | 行为 | 默认 |
|---|---|---|
| `reconcile_only` | LISTEN/NOTIFY + periodic scan + expired-lease reconcile；**不 claim** | CLI 默认 |
| `supervised_dispatch` | reconcile → claim → gate → `mark_dispatch_started` → adapter **事务外** → delivered / rejected / `outcome_unknown` | 需 `--mode supervised_dispatch`；自动构建 HTTP adapter |

本地开关（默认 OFF；live `.env` 可按授权打开）：

| 变量 | 作用 |
|---|---|
| `QS_HERMES_GATEWAY_ALLOW_EPHEMERAL_RUNS` | 上游无 durable 时仍允许 POST `/v1/runs` |
| `QS_HERMES_GATEWAY_DISPATCH_TIMEOUT_SECONDS` | 写端超时（默认 120s；读端仍 2s） |
| `QS_LOCAL_MUTATION_ENABLED` | 打开 authenticated local BFF mutation 门 |
| `QS_LOCAL_MUTATION_COMPOSER_OPEN` | 在 schema 就绪时表面 `chat_write_ready` / composer |
| `QS_HERMES_CHAT_ENABLED`（FE） | 解锁 composer 草稿 UI；与 API local mutation 联用后可走 L2a composite submit（仍非 public V8） |
| `QS_INTENT_PAYLOAD_*` | BFF/worker 子进程调用 HQA Intent Payload CLI（put / bind_resolve）；平台不 `import hqa` |

V5/V6 验收要点：

- `FakeHermesDispatchAdapter`：accept / recover / timeout / reject / accept_drop_ack。
- `HttpHermesDispatchAdapter`：mock transport unit + live smoke
  `ensure_bound_command` → `connector-worker --once --mode supervised_dispatch --fixed-input "Reply with exactly: pong"` → `delivered` / `provider_call_count=1`。
- 空队列：零 Hermes mutation、零 provider call。
- timeout / transport → durable `outcome_unknown`；**禁止盲重试**。
- gate deny 在 claim 后、网络前 reject。
- `composer_readiness` 现为 settings-gated：local mutation ON + research schema ready
  ⇒ `mutation_enabled` / `composer_write_ready` / `chat_write_ready` 可为 true。

最终 worker 的职责仍是确定性的队列与恢复，不是让模型担任消息队列：

1. HQA 先以稳定 request/saga 准备 Task/Attempt 与 immutable payload；平台只在一个事务中
   创建 exact-bound durable command/event/outbox，且同一请求只能产生一个逻辑 run。
2. supervised worker 用短事务和 `FOR UPDATE SKIP LOCKED` claim，记录 lease、
   attempt、heartbeat 和 recovery evidence；网络 I/O 永远在事务外。
3. PostgreSQL `LISTEN/NOTIFY` 只作低延迟唤醒；通知可能丢失，因此必须有 periodic scan
   fallback。scan 与 claim/lease/heartbeat 本身都不调用 LLM。
4. 只有 claim 到明确、已授权的 queued command 后，worker 才向 Hermes 提交 run；
   无任务时零 provider 请求、零 provider 额度。
5. upstream events 写入带稳定 event identity/cursor 的 durable ledger；重连时 replay/
   reconcile，而不是把内存队列当事实源。
6. UI 只从平台 read model 恢复状态；网络 timeout 是 unknown outcome，不能直接重试创建
   第二个 run。

不推荐“让 Hermes cron 每隔 N 秒请求平台并问有没有任务”。

**L2a/L2b（2026-07-22，本地 dark）：**

- `POST /api/agent/workspace/submit-turn`：owner CSRF + composite put + ledger turn。
- FE `workspaceClient` / `ComposerSubmitController`：same-origin cookies；poll follow
  lifecycle；delivered 后 `GET /api/hermes/sessions/{hermes_session_id}/messages` 预览
  最新 assistant（用 command/event 的 `hermes_session_id`，不要用 registry `web_`/`wm_`）。
- snapshot `commands[]` 为 public objects；follow cursor = workspace-scoped max event_id。
- ADR（HQA）：`docs/design/2026-07-22-l2a-send-thin-write-rail-adr.md`。

仍待后续：Plan-V6 完整 transcript/SSE/Task drawer、HQA Attempt observe 全链路、
approval exact binding、stop reconciliation、常驻 launchd supervised daemon 默认开启、
**public** V8 cutover。
