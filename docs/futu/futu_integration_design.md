# 富途只读集成设计

## 1. 范围

本阶段引入富途 OpenAPI / OpenD 作为以下场景的主要**只读**行情数据来源：

- 美股历史行情数据
- 在权限与 API 字段允许的情况下，提供美股期权链及期权报价数据
- 前端行情数据探索
- 因子研究、回测与模拟交易的数据输入
- 一个全新的只读期权筛选器 (Options Screener) 工作流

本阶段**不**改动 Polymarket 研究模块。

## 2. 非目标

本阶段明确**不**做以下任何事项：

- 真实交易
- 下单
- 账户解锁
- 创建交易上下文
- 改单 / 撤单
- 钱包 / 签名 / 私钥处理
- 实盘执行
- 券商账户管理
- Polymarket 执行逻辑改动

富途**仅用于行情数据**。

## 3. 现有数据提供方映射

### 3.1 当前后端股票数据提供方

- `SampleOHLCVProvider`
  - 文件：`src/quant_system/data/providers/sample.py`
  - 用途：确定性的离线样本数据
- `TiingoEODProvider`
  - 文件：`src/quant_system/data/providers/tiingo.py`
  - 用途：历史 EOD 股票数据
- `build_ohlcv_provider(...)`
  - 文件：`src/quant_system/data/provider_factory.py`
  - 当前支持 `sample` 与 `tiingo`

### 3.2 现有配置字段

- `QS_DEFAULT_DATA_PROVIDER`
- `QS_TIINGO_API_TOKEN`
- `ApiKeySettings` 中仍保留的遗留键：
  - Finnhub
  - Alpha Vantage
  - Tiingo
  - Twelve Data
  - Polygon
  - News API
  - Twitter

### 3.3 现有后端股票数据调用点

- `src/quant_system/api/routes/data.py`
- `src/quant_system/api/routes/benchmark.py`
- `src/quant_system/factors/pipeline.py`
- `src/quant_system/backtest/pipeline.py`
- `src/quant_system/execution/pipeline.py`

### 3.4 现有前端股票数据流

- 页面：`src/frontend/app/data-explorer/page.tsx`
- 控件：`src/frontend/components/forms/DataExplorerControls.tsx`
- API 客户端：`src/frontend/lib/api.ts`
- 提供方默认值当前指向 `tiingo`
- 因子 / 回测 / 模拟交易表单当前同样使用 `sample | tiingo`

### 3.5 现有期权支持

- 当前不存在真实的期权数据提供方
- 当前不存在后端期权路由
- 当前不存在期权筛选器页面

### 3.6 现有 Polymarket 边界

预测市场模块已存在于：

- `src/quant_system/prediction_market/**`
- `src/quant_system/api/routes/prediction_market.py`
- `src/frontend/app/order-book/**`

这些模块的功能必须保持不变。

## 4. 现有后端 API 流程

### 4.1 当前 OHLCV 流程

```text
Frontend / CLI
    -> /api/ohlcv
    -> LocalDataStorage local parquet check
    -> build_ohlcv_provider(settings, requested)
    -> provider.fetch_ohlcv(...)
    -> normalized rows
    -> safety footer in API middleware
```

### 4.2 当前因子 / 回测 / 模拟交易流程

```text
Frontend / CLI
    -> /api/factors/run or /api/backtests/run or /api/paper/run
    -> run_* pipeline
    -> build_ohlcv_provider(...)
    -> provider.fetch_ohlcv(...)
    -> factor/backtest/paper logic
    -> artifacts on disk
    -> API detail pages
```

这是好消息：只需改动一处提供方，即可贯通整个研究技术栈。

## 5. 现有前端流程

### 5.1 当前行情数据页面

```text
Data Explorer page
    -> read search params
    -> getSymbols()
    -> getOhlcv(symbol, start, end, provider)
    -> render source badge
    -> render simple price chart
```

### 5.2 受影响的研究页面

- `Factor Lab`
- `Backtester`
- `Paper Trading`

这些页面已接受一个提供方参数，只需少量 UI 改动即可切换至富途。

## 6. 富途集成架构

### 6.1 提供方策略

新增一个只读提供方：

- `FutuMarketDataProvider`

职责：

- 规范化美股代码：`AAPL -> US.AAPL`
- 仅连接本地 OpenD 行情服务
- 拉取历史 K 线数据
- 在可用时拉取期权链 / 期权报价
- 规范化为项目 schema
- 将富途 / OpenD 故障映射为清晰的应用层错误

### 6.2 安全边界

该提供方必须：

- 仅创建行情上下文
- 绝不创建交易上下文
- 绝不解锁交易
- 绝不提交订单
- 绝不暴露凭据

### 6.3 提供方选择

本阶段后支持的股票提供方：

- `sample`
- `futu`
- `tiingo`，暂时保留以兼容 / 回滚

验证通过后的推荐默认值：

- 当本地存在 OpenD 时，`QS_DEFAULT_DATA_PROVIDER="futu"`

安全回退行为：

- 若显式指定 `provider=futu` 但 OpenD 不可用 -> 向 API 调用方返回带类型的错误
- 若默认提供方为 `futu` 且 OpenD 不可用 -> 仅在当前 API 约定要求返回不崩溃响应的情况下，可选地回退到 sample，但响应必须明确说明这是回退结果

### 6.4 期权提供方形态

期权数据应保持只读，并可能采用以下两种形态之一：

- 在 `futu.py` 中扩展报价与期权链辅助方法
- 或在不触及无关模块、能保持代码更清晰的前提下，新增 `futu_options.py`

最终选择应尽量减少抽象层的反复改动。

## 7. 配置设计

为富途 / OpenD 新增安全设置：

- `QS_FUTU_ENABLED=true`
- `QS_FUTU_HOST=127.0.0.1`
- `QS_FUTU_PORT=11111`
- `QS_FUTU_MARKET=US`
- `QS_FUTU_REQUEST_TIMEOUT_SECONDS=15`
- `QS_FUTU_DEFAULT_KLINE_FREQ=1d`
- `QS_FUTU_CACHE_DIR=data/futu`
- `QS_FUTU_USE_CACHE=true`

可选：

- `QS_FUTU_OPTIONS_ENABLED=true`

在本项目设计中，本地 OpenD 连接无需任何密钥。

遗留的供应商密钥仍会加载，但应将其在美股 / 期权行情数据场景下标注为已弃用。

## 8. 后端 API 设计

### 8.1 待扩展的现有端点

- `GET /api/ohlcv`
- `GET /api/benchmark`
- `POST /api/factors/run`
- `POST /api/backtests/run`
- `POST /api/paper/run`

提供方枚举改动：

- 从 `sample | tiingo`
- 改为 `sample | futu | tiingo`

### 8.2 新增股票行情端点

新增一个更清晰、面向前端的端点：

`GET /api/market-data/history?ticker=AAPL&start=2024-01-01&end=2024-12-31&freq=1d&provider=futu`

目的：

- 保持现有 `/api/ohlcv` 可用
- 为前端提供一个以代码 / 频率为导向、易于理解的端点

### 8.3 期权端点

新增只读期权路由：

- `GET /api/options/chain`
- `GET /api/options/expirations`
- `POST /api/options/screener`

所有响应仍必须包含安全页脚。

## 9. 前端 UI 设计

### 9.1 行情数据页面

用户输入：

- 股票代码
- 提供方 (`sample | futu`)
- 起始日期
- 结束日期
- 频率

展示：

- 来源徽章
- 拉取时间
- 最新收盘价
- K 线数量
- K 线 / 蜡烛图
- 当 OpenD 离线或缺少权限时显示的可读错误块

### 9.2 期权筛选器页面

在前端应用结构下新增页面，包含：

- 股票代码输入
- 策略类型
  - Sell Put
  - Covered Call / Sell Call
- DTE 时间窗口；后端会自动扫描匹配的到期日
- 最小 IV
- 目标 delta / 最大 delta
- 最小权利金
- 最大价差百分比
- 趋势过滤
- HV/IV 择时过滤
- 运行按钮
- 结果表格
- 说明 / 免责声明块

### 9.3 中文前端版本

当前不存在 i18n 框架。风险最低的方案是：

- 新增一个轻量的 locale 字典层
- 保持逻辑不变
- 从共享映射中暴露英文与中文标签

若此方案侵入性过大，则可接受基于路由的 `/zh` 包装层，但前提是逻辑复用度仍然较高。

## 10. 期权筛选器设计

### 10.1 策略输出

对每个候选项：

- 标的价格
- 期权代码
- 策略类型
- 行权价
- 到期日
- bid / ask / mid
- 权利金估计
- 价差百分比
- 价值状态 / 距离
- 年化收益率估计
- 若富途可提供则给出 IV
- 由股票历史在本地计算的 HV
- 趋势过滤结果
- 保守评级

### 10.2 评级

仅人类可读：

- `Strong`
- `Watch`
- `Avoid`

评分必须保守且有文档说明。数据缺失时必须降低置信度，而非臆造数值。

### 10.3 免责声明

筛选器必须展示：

- 只读数据模式
- 仅供研究
- 无实盘交易
- 非投资建议

## 11. 可能被修改的文件

本方案可能触及**超过 30 个文件**。原因：

1. 提供方实现
2. 配置与环境变量模板
3. API 路由与 schema
4. 因子 / 回测 / 模拟交易的提供方枚举
5. CLI 数据导入路径
6. 前端行情数据页面
7. 新期权页面与 API 客户端类型
8. 中文标签
9. 测试
10. 文档

可能的代码改动：

- `src/quant_system/config/settings.py`
- `.env.example`
- `src/quant_system/data/provider_factory.py`
- `src/quant_system/data/providers/__init__.py`
- 新的富途提供方模块
- `src/quant_system/data/pipeline.py`
- `src/quant_system/cli.py`
- `src/quant_system/api/routes/data.py`
- `src/quant_system/api/routes/benchmark.py`
- 新的 `src/quant_system/api/routes/options.py`
- `src/quant_system/api/server.py`
- 相关 API schema
- 因子 / 回测 / 模拟交易 schema
- 因子 / 回测 / 模拟交易前端表单
- `src/frontend/lib/api.ts`
- `src/frontend/app/data-explorer/page.tsx`
- 图表组件
- 新的期权筛选器前端页面 / 组件
- 侧边栏 / 导航文件
- 测试
- 文档

## 12. 绝不可触及的文件

除非某个微小的共享接口修复变得不可避免：

- `src/quant_system/prediction_market/**`
- Polymarket API 行为
- Polymarket 前端工作流
- 任何实盘交易路径
- 任何钱包 / 签名 / 私钥逻辑

## 13. 测试策略

### 13.1 单元测试

- 股票代码规范化
- OHLCV 规范化
- 提供方工厂选择
- 使用 mock 的富途 SDK 成功路径
- OpenD 不可用
- 权限被拒绝
- 无效代码
- 空数据
- 期权链规范化
- 缺失 IV / Greeks 字段
- 筛选器评分行为

### 13.2 API 测试

- `/api/ohlcv` 或 `/api/market-data/history`
- benchmark
- 使用 `provider=futu` 的因子运行
- 使用 `provider=futu` 的回测运行
- 使用 `provider=futu` 的模拟交易运行
- 期权链 / 筛选器端点

### 13.3 前端测试

- 行情数据页面表单
- 提供方切换
- 加载 / 错误状态
- 基于 mock 数据的图表渲染
- 期权筛选器页面正常路径
- 中文标签渲染

### 13.4 人工验证

由于真实 OpenD 连接依赖本地状态，需新增：

- `scripts/verify_futu_connection.py`
- 逐步人工验证文档

## 14. 人工验证策略

人工检查必须确认：

1. `ai-quant` 环境已激活
2. 富途 SDK 可在该环境中导入
3. 本地 OpenD 可达
4. 行情上下文可查询基础美股行情数据
5. 至少一个美股 K 线请求成功
6. 在权限允许时期权链 / 报价可用
7. 前端行情数据页面加载到真实的富途数据
8. 期权筛选器返回可读结果
9. Polymarket 页面仍正常工作

## 15. 错误映射

将富途 / OpenD 故障映射为前端可读错误：

- OpenD 未运行
- 无法连接主机 / 端口
- 行情权限被拒绝
- 无效代码
- 不支持的频率
- 空数据集
- 超时

API 不应泄露原始堆栈跟踪信息。

## 16. 回滚方案

若富途验证失败：

1. 保持 `sample` 与 `tiingo` 路径完好
2. 将默认提供方切回当前的安全默认值
3. 将富途路由隐藏在显式的提供方选择之后
4. 记录阻塞点，但不破坏现有研究流程

回滚粒度：

- 仅提供方工厂
- 仅前端提供方下拉框
- 期权筛选器可在 API 验证通过前保持隐藏

## 17. 官方技能 / SDK 安装说明

官方富途技能已安装到全局 Codex 技能目录：

- `futuapi`
- `install-futu-opend`

本地 OpenD GUI 此前已安装并运行，因此本项目未重新安装 OpenD。

验证路径：

1. 先验证现有的本地 OpenD GUI
2. 验证富途 Python SDK 是否已安装在 `ai-quant` 内
3. 仅在缺失时将 `futu-api` 安装到 `ai-quant`
4. 在 `docs/futu_environment_setup.md` 中记录等效的手动步骤

## 18. ASCII 流程图

```text
                +---------------------------+
                |   Futu OpenD (local GUI)  |
                |   quote only / read-only  |
                +-------------+-------------+
                              |
                              v
                +---------------------------+
                | FutuMarketDataProvider    |
                | - ticker normalize        |
                | - kline fetch             |
                | - option chain fetch      |
                | - quote normalize         |
                +-------------+-------------+
                              |
          +-------------------+-------------------+
          |                   |                   |
          v                   v                   v
 +----------------+  +----------------+  +----------------+
 | /api/ohlcv     |  | /api/benchmark |  | /api/options/* |
 +--------+-------+  +--------+-------+  +--------+-------+
          |                   |                   |
          v                   v                   v
 +--------------------------------------------------------+
 | factor / backtest / paper pipelines use provider       |
 +---------------------------+----------------------------+
                             |
                             v
         +---------------------------------------------+
         | Frontend: Market Data / Factor / Backtest / |
         | Paper / Options Screener / Chinese labels   |
         +---------------------------------------------+
```

## 19. 阶段顺序

1. 设计冻结
2. 验证 `ai-quant` + SDK + OpenD
3. 实现股票提供方
4. 将现有股票流程接入富途
5. 新增期权提供方
6. 新增期权筛选器
7. 前端集成
8. 中文前端标签
9. 回归 + 文档

## 20. 安全声明

本次集成仅将富途用于**只读行情数据**。它**不**新增真实下单、账户解锁、钱包 / 私钥处理或实盘交易。
