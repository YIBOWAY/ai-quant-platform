# Hermes 助手（现役入口：`/hermes`）、会话与本地写入边界

## 当前结论（2026-09-05）

平台已经能通过 **official Hermes API Server** 读取本机已保存的 Hermes 会话：

```text
浏览器
  -> Next 页面（127.0.0.1:3001）
    -> 平台 API/BFF（127.0.0.1:8765）
    -> server-side GET-only adapter
      -> official Hermes API Server（http://127.0.0.1:8642）
        -> Hermes 已保存会话
```

读取面与写入面必须分开理解：

- gateway/capability、session list/detail/messages 是 server-side GET-only；
- Discord、外部导入和历史会话在 Web 中始终只读。仅当当前接口支持从指定消息
  建立独立分支、且保留原会话时才展示分支操作。`official-http-v1` 当前不支持这项
  精确分支能力，页面说明原因并保留历史阅读；可另开「新对话」自行补充背景；
- 新 managed Session 的 composer/submit-turn 已有本地单用户 `local_trust` 路径。
  它仍要求 local mutation/composer、owner cookie/CSRF、完整 034 schema/resource
  envelope、Keychain、paper safety 与 supervised connector liveness；local trust
  只省去 candidate identity ceremony，不放松其余条件；
- 同聊研究缺 note、可执行 formula 或 ordered universe 时只追问且零入队；材料充分的
  同一 operation 最多创建一个 job。当前支持日线 OHLCV Qlib 表达式，公式结构化传到容器后固定复现一次，Platform独立回放同源权重；不能表达的复杂策略明确返回不支持。
  新完成研究通过现有 DSR/相关性/成本/资金检查后自动分配一个 $10,000 模拟策略仓。
  `paper_running` 表示已启用，不代表已成交；拒绝保留候选，部分写入走现有对账恢复。
  `/library` 保留旧候选手动启用；不会扫描启用全部旧候选。
- `chat_write_ready` 与 `admission_mode=local_trust` 表示本地 readiness，不表示
  `public_chat_write_ready`、`public_write_authorized` 或
  `release_authorized`；public standing 继续 OFF；
- Unified Results preview/catalog 可见，但 legacy redirect/retirement 仍需独立授权。
- health、capabilities 与 session GET 不提交 prompt、不调用 Hermes provider，因而不消耗
  Hermes 当前配置的 Codex、Grok 或其他 provider 额度。
- 会话 GET 不把 Hermes 会话复制进平台数据库；写端只持久化 Platform 的
  managed-session/command/evidence 权威。
- `/hermes` 的聊天栏在 Hermes 头像后的对话流中，把当前 managed Session 命令映射为
  排队、处理中、分析、使用工具、生成回复与终态，并用不确定进度条表示正在工作。
  桌面对话位于主区左侧，可在 320–860px 范围（受视窗宽度约束）拖拽，也可以用左右方向键调整；移动端仍使用抽屉。该状态来自
  durable command、Hermes Run status 和有限事件快照，不是模型思维链或 token stream。
  工具名、参数、输出、错误正文与 reasoning 文本不会下发浏览器。
- 会话列表的标题和预览会清理 Discord 传输前缀和敏感片段；空会话与内部 `web_`
  识别符不出现在侧栏。
- 未指明数据源的“我的持仓/资金/模拟仓”和个性化标的问题，Hermes 先读 Platform
  canonical `default` 模拟账户；installed HQA wrapper 直接读 Platform loopback
  snapshot，不使用源码 checkout 的 file account。只有用户明确指定 Longbridge 时才改用 Longbridge，并分别标明账户换算
  币种和 `cash_infos` 原始币种。
- workspace 同源请求固定 30 秒截止。GET 超时显示 `workspace_request_timeout`，可检查
  本机服务后重新读取；POST 超时显示 `outcome_unknown`，保留原 `client_action_id`，
  只能使用“重试同一次发送”，不创建第二条逻辑消息。

2026-10-04 修复合同：点击「新对话」后，路由切换及新会话写入资格检查期间锁定发送，
仍可保留草稿；旧路由不得把当前会话恢复为旧 ID。风险等结果若已有合法的失败原件，
统一详情会保留 `unavailable` 并显示当时的失败原因，而不是把原件当作格式错误丢弃；
身份失配、超大载荷和损坏原件仍按原校验处理。这些是源码合同，发布状态以该批收据为准。

旧的 TUI gateway capability contract 已随上游实现漂移并 fail closed。它只保留历史/
诊断价值，平台的现行主读取链路是 official API Server。

数据库迁移、readiness、服务重启、受控 E2E 与 restore 只以
[Agent v0.2 local-stack runbook](../runbooks/agent-v0-2-local-stack.md) 为准。
正式 migration 034 已在备份与 restored-sibling rehearsal 后唯一一次应用；当前
local-trust composer 与 research resource envelope 依赖它。不要重放 034，也不要把
本地 readiness 投影成 public/release 授权。

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
cd $HOME/programs/Hermes-quant-agent
install -d -m 700 data/_runtime
if [ ! -e data/_runtime/hermes-api.key ]; then
  install -m 600 /dev/null data/_runtime/hermes-api.key
fi
```

随后用可信的本地编辑器或密码管理器把 Hermes API Server 的 key 粘贴进
`$HOME/programs/Hermes-quant-agent/data/_runtime/hermes-api.key`（该运行时目录已
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
export QS_HERMES_GATEWAY_API_KEY_FILE=$HOME/programs/Hermes-quant-agent/data/_runtime/hermes-api.key
export QS_HERMES_GATEWAY_TIMEOUT_SECONDS=2
export QS_HERMES_GATEWAY_MAX_RESPONSE_BYTES=4194304
export QS_HERMES_GATEWAY_MAX_MESSAGES=200

quant-system serve --host 127.0.0.1 --port 8765
```

前端仍按通常方式绑定 loopback：

```bash
cd $HOME/programs/ai-quant-platform/src/frontend
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
curl -fsS http://127.0.0.1:8765/api/safety/effective
```

gateway 正常时应看到：

- `connected=true`
- `session_api_available=true`
- `read_status=available`
- `chat_write_ready` 按当前 local-trust readiness 计算，可能为 false 或在本地条件完整时
  为 true；同时检查 `admission_mode=local_trust`，但不能据此推断 public write；
- `platform_delivery_blockers` 与 `blockers` 必须如实保留 schema、runtime、
  resource envelope、connector、Keychain 或上游缺口，不能把 unavailable 改写成空状态。

`GET /api/safety/effective` 不调用 provider。只有 canonical 模式、root owner 恰好一个
`default` 账户、materialized/raw `account_id` 与 JSON boolean `kill_switch=true`
一致、global kill switch 为 true 且 current paper-authority epoch 可读时，
`effective` 才能为 true。它仍不授权本地 chat 或 public release。

从 sessions 响应选择一个真实 `id` 后，可以验证：

```bash
curl -fsS 'http://127.0.0.1:8765/api/hermes/sessions/<URL_ENCODED_ID>'
curl -fsS 'http://127.0.0.1:8765/api/hermes/sessions/<URL_ENCODED_ID>/messages'
```

最后用浏览器检查现役入口和深链：

- `http://127.0.0.1:3001/zh/hermes`（会话列表已合并到助手页）
- `http://127.0.0.1:3001/zh/hermes/sessions/<URL_ENCODED_ID>`

`/hermes/sessions` 是到 `/hermes` 的 301 兼容别名，不是另一套会话列表页面。

persisted-session 详情页只显示 `user` / `assistant` 文本消息，并保持只读；它不是
managed workspace composer。system/tool/reasoning 等上游消息不会透传；消息数受
`QS_HERMES_GATEWAY_MAX_MESSAGES` 限制，响应以 `omitted_message_count`
说明被省略数量。

这里没有 DLP/秘密扫描：user/assistant 文本会按原内容限长展示。若用户曾把 key、token 或
其他敏感文本粘贴进对话，它仍可能出现在详情页；不要把会话观察面当作脱敏归档。

## BFF 固定合同

| 平台路由 | 上游读取 | 能否触发 provider |
|---|---|---|
| `GET /api/hermes/gateway` | capabilities | 否 |
| `GET /api/hermes/sessions` | persisted session list | 否 |
| `GET /api/hermes/sessions/{session_id}` | persisted session detail | 否 |
| `GET /api/hermes/sessions/{session_id}/messages` | persisted messages | 否 |
| `GET /api/workspace/{workspace_id}/commands/{command_id}/activity` | owner/workspace 绑定的 Run status + 有限事件快照，只返回通用阶段/耗时 | 否 |

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
- **平台 BFF 当前面向单用户本地部署。** 写路由使用本地 owner cookie 与 CSRF，
  但这不是多用户身份系统；读取面也不能公开绑定或反向代理到 LAN/公网。
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
| 页面“读取不可用” | 先看 `/api/hermes/gateway` warning，再看后端日志；不要通过打开 local composer 绕过。 |
| `/api/safety/effective` 为 404 | 运行进程尚未加载当前 source；按 local-stack runbook 完成被授权的迁移/readiness/restart，不能把 source 当 live。 |
| `candidate_paper_authority_epoch_stale` | paper authority 已变化；关闭写端并 CAS revoke exact candidate，不能刷新或代换 epoch。 |

## 本地私有写入链路

本地写入使用 durable ledger 与 deterministic connector，不让 LLM cron 空轮询：

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
       GET …/commands/{command_id}/activity  (sanitized stage/tool state)
       after delivered: GET /api/hermes/sessions/{id}/messages (preview)
```

Worker 模式：

| mode | 行为 | 默认 |
|---|---|---|
| `reconcile_only` | LISTEN/NOTIFY + periodic scan + expired-lease reconcile；**不 claim** | CLI 默认 |
| `supervised_dispatch` | reconcile → claim → gate → `mark_dispatch_started` → adapter **事务外** → delivered / rejected / `outcome_unknown` | 需 `--mode supervised_dispatch`；自动构建 HTTP adapter |

本地开关默认 OFF，只是必要条件：

| 变量 | 作用 |
|---|---|
| `QS_HERMES_GATEWAY_ALLOW_EPHEMERAL_RUNS` | 仅显式测试兼容窗口；不得替代 durable release contract |
| `QS_HERMES_GATEWAY_DISPATCH_TIMEOUT_SECONDS` | 写端超时（默认 120s；读端仍 2s） |
| `QS_LOCAL_MUTATION_ENABLED` | 打开 authenticated local BFF mutation 门 |
| `QS_LOCAL_MUTATION_COMPOSER_OPEN` | 在 schema 就绪时表面 `chat_write_ready` / composer |
| `QS_HERMES_CHAT_ENABLED`（FE） | 解锁 composer 草稿 UI；与 API local mutation 联用后可走 L2a composite submit（仍非 public V8） |
| `QS_INTENT_PAYLOAD_*` | BFF/worker 子进程调用 HQA Intent Payload CLI（put / bind_resolve）；平台不 `import hqa` |

这些开关之外还必须满足 migration 034 exact readiness/resource envelope、effective
paper safety、非创建式 HQA Keychain `probe`、fresh supervised connector 与
owner/CSRF。`local_trust` 下不需要伪造 private candidate 或 accepted release，且绝不
投影 public/release authority。Key missing 时必须暂停；只有操作者可按 local-stack
runbook 单独执行 `initialize-key`，普通 put/encrypt 不得创建 key。

保留的 private candidate CLI 属于 legacy candidate/release qualification，不是
local-trust composer 的前置条件：

```bash
quant-system hermes candidate status
quant-system hermes candidate open \
  --note "<operator reason>" \
  --client-action-id "<stable exact action id>"
quant-system hermes candidate revoke \
  --admission-id "<exact id>" \
  --expected-admission-digest "<exact digest>" \
  --reason "<reason>" \
  --client-action-id "<stable exact revoke id>"
```

`open` 不授权 public write。任何 runtime/schema/paper epoch/connector drift、证据失败
或放弃都应 revoke exact candidate。

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
6. UI 只从平台 read model 恢复状态；GET timeout 可安全重读，POST timeout 是
   `outcome_unknown`，不能直接创建第二个 run。

聊天栏活动查询只在命令仍在运行且侧栏可见时进行，切换命令或关闭移动侧栏会中止当前
请求；终态与历史命令不继续轮询。连接断开不等于 Run 已失败，页面会明确说明任务可能仍
在后台继续。成功终态活动行会收起；失败保留可见状态供用户判断。

不推荐“让 Hermes cron 每隔 N 秒请求平台并问有没有任务”。
