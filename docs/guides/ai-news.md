# AI 新闻研究流（界面路由：`/ai-news`）

> 适用读者：想在量化研究平台里快速浏览 AI 行业热点，但不希望新闻自动影响策略或账户的人。
> 安全红线：本页面是外部新闻的只读入口，不生成交易信号，不触发回测，不调用 paper account，也不接任何真实交易链路。

---

## 一句话定位

`/ai-news` 是 AI HOT 的本地只读代理页面。前端只访问本地 FastAPI：

```text
/ai-news -> /api/news/aihot/* -> AI HOT public API
```

页面展示精选动态、分类 / 关键词 / 时间窗筛选、最新日报和近期日报归档。它只帮助阅读和追溯原文，不把新闻写入因子、策略、回测或模拟账户。

## 能做什么

- 看 AI HOT 精选或全部新闻流。
- 按分类筛选：模型、产品、行业、论文、技巧观点。
- 按关键词搜索，例如 `OpenAI`、`Sora`、`agents`。
- 按 `24h` / `3d` / `7d` 时间窗收窄。
- 查看最新或指定日期的 AI HOT 日报。
- 打开原文链接核对来源。

## 本地 API 速查

前端页面只调用本地后端；不要在前端直连 `https://aihot.virxact.com`。

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/news/aihot/items` | 新闻流；支持 `mode=selected|all`、`category`、`q`、`since`、`cursor`、`take=1..100`。 |
| `GET` | `/api/news/aihot/daily` | 最新日报；可选 `date=YYYY-MM-DD`。 |
| `GET` | `/api/news/aihot/dailies` | 日报归档；`take=1..180`。 |
| `GET` | `/api/news/aihot/status` | 本地配置、beta/read-only 声明和进程内最近错误；不探测 AI HOT 外网。 |

示例：

```powershell
curl "http://127.0.0.1:8765/api/news/aihot/items?mode=selected&take=20"
curl "http://127.0.0.1:8765/api/news/aihot/items?mode=selected&q=OpenAI&take=20"
curl "http://127.0.0.1:8765/api/news/aihot/daily"
curl "http://127.0.0.1:8765/api/news/aihot/status"
```

## 不能做什么

- 不会自动生成交易建议。
- 不会创建、启动、暂停或修改策略。
- 不会启动回测。
- 不会修改 paper account 或 Paper Strategy Sleeves。
- 不会调用 Futu 交易接口、券商账户、钱包或签名逻辑。

## 数据可信度边界

AI HOT 是外部 beta 数据源，摘要可能由 LLM 生成。页面会保留 `provider_beta` 和 `research_safety` 提示。引用任何内容前，应点击原文链接核对。

## 配置

`.env` 可覆盖：

```text
QS_AIHOT_ENABLED=true
QS_AIHOT_BASE_URL=https://aihot.virxact.com
QS_AIHOT_TIMEOUT_SECONDS=8
QS_AIHOT_CACHE_TTL_SECONDS=120
QS_AIHOT_USER_AGENT=Mozilla/5.0 ...
```

`QS_AIHOT_ENABLED=false` 时，新闻 API 返回 `503 aihot_disabled`，状态页仍只显示本地配置，不探测外网。

常见错误：

| 情况 | HTTP | `detail.code` |
|---|---:|---|
| 功能关闭 | `503` | `aihot_disabled` |
| 上游超时 | `503` | `aihot_timeout` |
| 上游 4xx/5xx 或网络错误 | `502` | `aihot_bad_gateway` |
| 上游 JSON 或字段结构异常 | `502` | `aihot_invalid_response` |
| 本地 query 参数非法 | `422` | FastAPI validation |

## 可选数据库缓存

如果启用现有 `QS_DATABASE_*` Postgres 配置，`/api/news/aihot/items` 会在实时请求成功后把 AI HOT items 写入 `quant_system.ai_news_items`。当上游暂时失败时，后端会尝试返回匹配的本地缓存，并在 `warnings` 中标明“来自本地数据库缓存”和上游错误。

这个缓存只用于页面只读兜底：

- 不缓存日报正文。
- 不运行调度器。
- 不生成信号、因子或交易建议。
- 数据库不可用时，新闻功能仍按实时代理方式工作。

本地 Docker 数据库检查：

```powershell
docker start quantplatform-db

$env:QS_DATABASE_ENABLED='true'
$env:QS_DATABASE_URL='postgresql://quant:quantpass@127.0.0.1:5432/quantplatform'
quant-system serve --host 127.0.0.1 --port 8765

curl http://127.0.0.1:8765/api/health
docker exec quantplatform-db psql -U quant -d quantplatform -c "SELECT table_name FROM information_schema.tables WHERE table_schema = 'quant_system' AND table_name LIKE 'ai_news_%' ORDER BY table_name;"
```

正常情况下会看到：

```text
ai_news_fetches
ai_news_items
```

## 验证

离线测试不得访问真实 AI HOT，也不得访问真实 Postgres：

```powershell
python -m pytest tests/test_api_news_aihot.py tests/test_news_aihot_client.py tests/test_news_aihot_repository.py tests/test_settings_aihot.py -q
python -m pytest tests/test_frontend_ai_news_contract.py -q
npm --prefix src/frontend run type-check
npm --prefix src/frontend run lint
```

## 相关代码入口

- 后端 client：`src/quant_system/news/aihot_client.py`
- 后端模型：`src/quant_system/news/models.py`
- 可选缓存：`src/quant_system/news/repository.py`
- API schema：`src/quant_system/api/schemas/news.py`
- API route：`src/quant_system/api/routes/news.py`
- 数据库迁移：`scripts/sql/002_ai_news_cache.sql`
- 前端页面：`src/frontend/app/ai-news/page.tsx`
- 前端组件：`src/frontend/components/forms/AiNewsView.tsx`
- 前端 API client：`src/frontend/lib/api.ts`
