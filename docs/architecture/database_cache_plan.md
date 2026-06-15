# 数据库缓存方案

状态：目前已实现两个本地存储层 —— (1) 基于 DuckDB 的富途 (Futu)
期权缓存，以及 (2) 一个可选的 PostgreSQL **运行索引 (run index)**，覆盖基于文件的
回测 / 因子 / 模拟盘运行记录。

DuckDB 期权缓存位于 `src/quant_system/storage/options_cache.py`，
在 `QS_FUTU_USE_CACHE=true`（默认值）时，会将富途期权报价窗口持久化到
`data/futu/options_cache.duckdb`。

PostgreSQL 运行索引位于 `src/quant_system/storage/database.py` 和
`src/quant_system/storage/runs_repository.py`，其 schema 定义在
`scripts/sql/001_runs_index.sql` 中。它是**可选的，且默认关闭**；启用后
会对已有的基于文件的运行记录建立索引以实现快速列举，而当数据库被禁用或不可达时，
API 会退回到扫描文件系统。

## PostgreSQL 运行索引（已实现）

`data/api_runs/<kind>/<run_id>/metadata.json` 下的文件仍然是事实来源 (source of
truth)。运行索引是一个可查询的镜像，而非替代品。

- 配置项（`config/settings.py` → `DatabaseSettings`，环境变量前缀 `QS_DATABASE_`）：
  - `QS_DATABASE_ENABLED`（默认 `false`）
  - `QS_DATABASE_URL`（例如 `postgresql://quant:quantpass@127.0.0.1:5432/quantplatform`；
    作为密钥保存，并在 `/api/settings` 中被脱敏处理）
  - `QS_DATABASE_CONNECT_TIMEOUT_SECONDS`（默认 `1`）
  - `QS_DATABASE_AUTO_MIGRATE`（默认 `true`）
- Schema：单张表 `quant_system.runs`（`kind`、`run_id`、`source`、
  `created_at`、`indexed_at`、`artifact_path`、`metadata` JSONB），以
  `(kind, run_id)` 为键。`kind` 取值为 `backtest`、`factor` 或 `paper`。
  反转/动量研报复现运行也会落盘到 `data/api_runs/replications/<run_id>/`，
  但当前不进入该 PostgreSQL 索引。
- 启动时（`api/server.py` lifespan）在后台线程中执行迁移 / 对账：它会回填已存在的
  文件运行记录，并清除那些对应文件已不存在的索引行（自愈机制，避免列举出一个
  其详情会返回 404 的运行），同时不会阻塞 API 启动。
- 连接失败会被短暂记住。可选的连接超时上限为 1 秒；健康数据库允许并发短生命周期连接，
  失败后才进入冷却窗口。在冷却期内重复请求会使用文件系统回退，而不是在每次调用时都去等待
  PostgreSQL。
- 列举端点（`/api/backtests`、`/api/factors/runs`、`/api/paper`）以文件系统决定
  记录是否存在及显示顺序，对已匹配的记录优先复用数据库元数据；因此 API 运行期间新复制
  或新生成但尚未入索引的文件记录也会立即显示。遇到任何数据库错误时完全回退到文件系统。
  运行端点会以即发即忘 (fire-and-forget) 的方式为每个新运行建立索引（数据库故障绝不会
  阻塞运行）。
- `/api/health` 会上报一个 `database` 区块（`enabled`、`reachable`、`error`）。
- 测试通过 `tests/conftest.py` 强制设置 `QS_DATABASE_ENABLED=false`，使整套测试
  永远不会写入共享容器。

直接使用 `psycopg`（无 ORM，无连接池 —— 采用每次操作单独建立的短生命周期
连接，与 DuckDB 缓存的风格一致）。

## 为何需要它

交互式富途期权页面使用一个短生命周期的进程内缓存、一次针对限频响应的重试，
现在还增加了一个本地 DuckDB 缓存用于存储成功的期权报价窗口。DuckDB 缓存可在
后端重启之间持久保留，并由期权筛选器 (Options Screener)、期权雷达 (Options Radar)、
买方期权助手 (Buy-Side Options Assistant) 以及调用富途数据源的本地期权工具共享。

缓存层的存在使平台能够：

- 复用近期获取的期权链和快照。
- 减少对富途 OpenD 的重复请求。
- 让期权筛选器、期权雷达和买方期权助手在相同标的与时间戳下保持一致。
- 以可查询的格式存储扫描结果，供前端使用。
- 保持只读的安全边界。

## 推荐的存储划分

采用混合式本地存储模型：

| 存储 | 最适合的场景 |
|---|---|
| PostgreSQL | 元数据、期权链缓存索引、期权报价快照、雷达运行记录、API 任务记录、数据源请求日志。 |
| Parquet / DuckDB | 大规模 OHLCV 历史数据、回放数据集、宽分析表、批量研究。 |
| JSONL | 可移植的测试夹具 (fixtures) 以及小型的仅追加 (append-only) 研究产物。 |

PostgreSQL 很适合用户本地的 Docker 配置，尤其适用于查询最新的期权链快照以及
为前端视图提供数据。但它不应在所有大型历史研究数据集场景下替代 Parquet / DuckDB。

首个交付的缓存使用 DuckDB，以避免本地用户必须依赖 Docker 或数据库服务器。

## 拟定的表

最小化的首个版本：

| 表 | 用途 |
|---|---|
| `provider_requests` | 每次数据源调用一行，包含数据源、标的代码、端点类型、状态、错误码及获取时间。 |
| `equity_bars` | 可选的、用于前端小窗口的缓存 OHLCV 行。 |
| `option_chain_snapshots` | 快照元数据：标的、到期范围、期权类型、数据源、获取时间、缓存过期时间。 |
| `option_contract_quotes` | 与某个期权链快照关联的归一化期权行。 |
| `vix_history` | 若日后从 CSV 迁出，则存放 VIX/VIX3M 缓存行。 |
| `options_radar_runs` | 每日雷达运行的元数据。 |
| `options_radar_candidates` | 供 API 和前端过滤使用的雷达候选行。 |

在首个 DuckDB 实现中已落地：

- `option_chain_snapshots`
- `option_contract_quotes`

## 缓存策略

建议的安全默认值：

- 股票日线：近期范围在 24 小时后过期；在测试内部绝不自动刷新。
- 期权链：盘中 15 分钟后过期，盘外时间更长。
- 期权快照：盘中 5 分钟后过期。
- 雷达运行：按 `run_date` 不可变，除非用户显式重新运行扫描。
- 数据源错误：存储类型化的错误码，以帮助诊断 OpenD 与限频问题。

所有缓存条目都必须记录：

- `provider`
- `ticker`
- 请求的日期或到期窗口
- `fetched_at`
- `expires_at`
- 归一化的来源标签
- 若请求失败则记录错误码

## API 行为

依赖数据源的端点应遵循以下顺序：

1. 若存在新鲜缓存则直接返回。
2. 若缓存陈旧或缺失，且显式请求了数据源，则从只读数据源获取。
3. 将成功归一化后的数据写入缓存。
4. 返回类型化的数据源错误，不暴露原始堆栈跟踪 (traceback)。

任何端点都不应加入下单或券商执行功能。

## 建议的实现阶段

1. 为可选的 PostgreSQL 支持模式添加数据库配置项。（已实现为
   `QS_DATABASE_ENABLED`、`QS_DATABASE_URL`、`QS_DATABASE_CONNECT_TIMEOUT_SECONDS`、
   `QS_DATABASE_AUTO_MIGRATE`；schema 名称 `quant_system` 在 SQL 中固定，不作为配置项）
2. 添加一个小型存储包：（已实现）
   - `src/quant_system/storage/database.py`（PostgreSQL 连接 + 迁移）
   - `src/quant_system/storage/runs_repository.py`（文件为准，数据库元数据镜像 + 回退）
   - `src/quant_system/storage/options_cache.py`（DuckDB 期权缓存）
3. 在 `scripts/sql/` 下添加纯 SQL 迁移。（已实现：
   `scripts/sql/001_runs_index.sql`）
4. 优先缓存富途期权链和快照结果。（已为期权报价窗口实现）
5. 将期权筛选器和买方期权助手接入缓存优先的路径。
   （已通过共享的富途数据源实现）
6. 将期权雷达的 JSONL 读取置于一个存储门面 (storage facade) 之后，同时保留
   JSONL 导出以保证可移植性。
7. 添加前端可见的缓存元数据：来源、获取时间和缓存时长。

## 依赖建议

推荐的最小依赖：

- `psycopg[binary]`，用于访问 PostgreSQL。

在首轮实现中避免引入 SQLAlchemy 或 Alembic，除非项目开始需要复杂的 schema
迁移。对于首个本地缓存模块，纯 SQL 已经足够。

## 安全规则

- 数据库仅存储市场数据和研究产出。
- 不存储密钥、账户解锁状态、券商凭证、私钥、钱包数据或实盘下单指令。
- 不添加富途交易上下文。
- 不添加真实订单表。
- 所有由缓存支撑的产出都标注为研究数据。

## 尚未解决的问题

- PostgreSQL 现在是可选的且默认关闭；仅当 `QS_DATABASE_ENABLED=true` 时，运行索引
  才指向本地 Docker 容器 `quantplatform-db`。是否同时将期权缓存和雷达运行记录
  迁入 PostgreSQL 仍未确定。
- 用户本地的 Docker 镜像中是否提供 TimescaleDB 仍待确认。
- 运行索引以 JSONB 形式存储完整的运行元数据。若期权报价快照（日后迁入 PostgreSQL）
  应采用压缩 JSONB 还是完全归一化的行，仍未确定。首个 DuckDB 实现存储的是
  归一化的期权报价行。
