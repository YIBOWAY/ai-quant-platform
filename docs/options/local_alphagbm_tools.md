# 本地 AlphaGBM 风格期权工具

## 概述

本项目现已包含一套受已安装的 AlphaGBM 技能启发的本地只读期权工具集。

该本地工具集不调用 AlphaGBM API，也不需要 `ALPHAGBM_API_KEY`。Futu OpenD 作为实时股票与期权链数据的行情数据源。策略相关的数学计算在本地完成。

在 `/options-tools` 页面上，对行情敏感的工具会先向后端请求所输入标的的 Futu 快照与期权链，然后用返回的合约运行本地计算器。手动 / 仅本地的工具仍可对所提供的输入使用，并被标注为本地后端研究操作，而非实时行情数据。

任何端点都无法提交、修改、签署或下达真实订单。

## 阶段 1 范围

阶段 1 增加了多个 AlphaGBM 风格技能所需的共享构件：

- 当前期权快照，包含 ATM IV、历史波动率、IV rank 近似值以及波动率风险溢价近似值
- 跨已挂牌行权价与到期日的波动率曲面
- 单一到期日的波动率微笑与 25-delta 偏斜
- Black-Scholes 定价、隐含波动率与希腊字母
- 单腿与多腿损益模拟
- 常见期权策略的本地模板

这些工具可被后续的股票分析、财报、对冲、异动、自选股以及预警等功能复用。

## API 端点

### GET `/api/options/snapshot/{ticker}`

返回某标的基于 Futu 实时数据的期权快照。

示例：

```powershell
curl "http://127.0.0.1:8765/api/options/snapshot/AAPL?provider=futu"
```

响应包含：

- 当前股价
- 最近到期日
- ATM 隐含波动率
- 30 日历史波动率
- 本地 IV rank / 分位数近似值
- 波动率风险溢价近似值
- 只读假设

### GET `/api/options/tools/vol-surface/{ticker}`

返回基于 Futu 实时数据的波动率曲面。

示例：

```powershell
curl "http://127.0.0.1:8765/api/options/tools/vol-surface/AAPL?provider=futu&max_expirations=2"
```

响应包含：

- 价值状态（moneyness）分桶
- 到期日轴
- IV 网格
- 原始曲面点
- ATM 期限结构
- 曲面形态标签

### GET `/api/options/tools/vol-smile/{ticker}`

返回单一到期日基于 Futu 实时数据的波动率微笑。若省略 `expiry`，则使用最近的已挂牌到期日。

示例：

```powershell
curl "http://127.0.0.1:8765/api/options/tools/vol-smile/AAPL?provider=futu"
```

响应包含：

- 行权价
- IV 值
- delta 值
- 价值状态（moneyness）
- 25-delta 偏斜近似值
- 微笑形态标签

### POST `/api/options/tools/greeks`

计算单一期权的本地希腊字母。

示例请求体：

```json
{
  "spot": 100,
  "strike": 100,
  "expiry_days": 30,
  "iv": 0.25,
  "option_type": "call",
  "rate": 0.04
}
```

### POST `/api/options/tools/implied-volatility`

从期权市场价格反解本地隐含波动率。

示例请求体：

```json
{
  "market_price": 4.2,
  "spot": 100,
  "strike": 100,
  "expiry_days": 30,
  "option_type": "call",
  "rate": 0.04
}
```

### POST `/api/options/tools/simulate`

模拟单腿或多腿期权头寸的损益。

示例请求体：

```json
{
  "symbol": "AAPL",
  "spot": 100,
  "legs": [
    {
      "action": "buy",
      "option_type": "call",
      "strike": 100,
      "expiry_days": 30,
      "entry_price": 5,
      "quantity": 1
    }
  ]
}
```

### GET `/api/options/tools/strategy/templates`

列出本地策略模板。

当前模板：

- long call / long put
- bull call spread / bull put spread
- bear put spread / bear call spread
- covered call / cash-secured put
- collar
- long or short straddle
- long or short strangle
- iron condor
- iron butterfly
- synthetic long / synthetic short

### POST `/api/options/tools/strategy/build`

基于其中一个模板构建本地策略。

示例请求体：

```json
{
  "mode": "template",
  "template_id": "bull_call_spread",
  "symbol": "AAPL",
  "spot": 100,
  "expiry_days": 30,
  "strikes": [95, 100, 105, 110],
  "iv": 0.25
}
```

### POST `/api/options/tools/score-contracts`

用本地多因子打分对所提供的期权合约进行排序。

示例请求体：

```json
{
  "spot": 100,
  "objective": "sell_premium",
  "contracts": [
    {
      "symbol": "US.AAPL260619P00090000",
      "option_type": "PUT",
      "strike": 90,
      "bid": 1.1,
      "ask": 1.2,
      "volume": 600,
      "open_interest": 1200,
      "implied_volatility": 0.5,
      "delta": -0.24
    }
  ]
}
```

响应包含排序后的合约、总分、评级、各项子分、警告以及只读假设。

### POST `/api/options/tools/strategy/rank`

针对某一市场观点对本地策略模板进行排序。

示例请求体：

```json
{
  "market_view": "bullish",
  "spot": 100,
  "expiry_days": 45,
  "strikes": [85, 90, 95, 100, 105, 110, 115],
  "iv": 0.25
}
```

### POST `/api/options/tools/bull-put-signal`

应用本地 FearScore 阈值规则，并在可能时从所提供的看跌合约中选出一个仅供研究的牛市看跌价差（Bull Put Spread）候选。

### POST `/api/options/tools/fear-score`

从所提供的 VIX、IV rank、RSI、期权成交量异动、Put/Call 比率以及连续下跌天数等输入，计算某标的的本地恐慌评分。

### POST `/api/options/tools/iv-rank`

从所提供的本地 IV 历史值计算 IV rank / 分位数。

### POST `/api/options/tools/market-sentiment`

从所提供的 VIX、Put/Call 比率、市场广度以及趋势等输入，构建本地市场情绪状态（regime）。

### POST `/api/options/tools/earnings-crush`

从所提供的财报前 / 财报后 IV 观测值，估计历史财报 IV 坍缩（crush）。

### POST `/api/options/tools/hedge-advisor`

从所提供的持仓与期权合约，构建仅供研究的 Long Put / Collar 对冲候选。

### POST `/api/options/tools/unusual-activity`

从所提供的成交量与未平仓量字段标记期权异动。

### GET `/api/options/tools/watchlist`

读取本地期权自选股列表。

### POST `/api/options/tools/watchlist`

向本地期权自选股列表添加一个标的。该自选股列表是位于所配置输出目录下的一个本地 JSON 文件。

### POST `/api/options/tools/alerts/evaluate`

针对所提供的标的上下文，评估所提供的本地预警定义。该端点不发送通知。

### POST `/api/options/tools/health-check`

检查所提供的本地研究档案元数据，查找过期更新与缺失的论点。

### POST `/api/options/refresh/universe`

刷新本地 Options Radar 标的池 CSV。支持的数据源：

- `public` / `github`：公开的 S&P 500 + Nasdaq 100 CSV 快照
- `sample`：用于本地测试的确定性离线样本标的池

### POST `/api/options/refresh/earnings`

刷新 Options Radar 使用的本地财报日历 CSV。支持的数据源：

- `public` / `nasdaq`：Nasdaq 公开日历查询
- `yfinance`：显式的只读 yfinance 日历查询
- `sample`：用于本地测试的确定性离线样本日历

### POST `/api/options/refresh/vix`

刷新市场状态评分所使用的本地 VIX/VIX3M 历史 CSV。支持的数据源：

- `public`：优先 Yahoo Chart，回退至 Cboe 公开 CSV
- `sample`：用于本地测试的确定性离线样本 VIX 历史

这些刷新端点仅写入本地 CSV 缓存。它们不会提交、修改、签署或下达订单。

计划任务入口使用 CLI 命令：

```powershell
quant-system options daily-task --top 100 --universe-source public --earnings-source public --vix-source public
```

该命令会串联标的池、财报、VIX 刷新和一次只读雷达扫描，并在雷达输出目录
写入 `daily_task_status.json`。`GET /api/options/daily-scan/status` 和
`/options-radar` 页面会读取这个状态文件，显示最近一次调度任务状态。单个刷新端点和脚本仍用于维护或离线调试。

## 复刻计划

已安装的 AlphaGBM 技能描述的是产品工作流与远程 API 调用；它们并不包含完整的远程评分后端。因此本地复刻计划在 Futu 数据与本地模型之上重建等价的项目功能。

### 阶段 1：本地期权核心

状态：已实现。

- 快照
- 波动率曲面
- 波动率微笑
- 希腊字母
- 隐含波动率
- 损益模拟
- 策略模板

### 阶段 2：本地排序与策略选择

状态：已实现。

- 期权合约打分
- 多因子策略排序
- 牛市看跌价差（Bull Put Spread）信号工作流
- 买方与卖方统一排序
- 使用所提供或已持久化的 IV 历史的本地 IV rank 仪表盘辅助工具

### 阶段 3：研究仪表盘

状态：已作为本地后端研究辅助工具实现。

- 使用 VIX 与市场广度数据的市场情绪仪表盘
- 逐标的恐慌评分
- IV rank 仪表盘
- 财报 IV 坍缩工作流
- 对冲顾问工作流
- 从所提供的成交量 / 未平仓量变化进行的期权异动扫描

### 阶段 4：监控

状态：已作为轻量级本地文件 / 无状态辅助工具实现。

- 本地自选股列表
- 价格 / IV / 异动预警
- 针对过期研究档案的健康检查

### 阶段 5：持久化本地缓存

状态：首版实现完成。

- Futu 期权报价窗口缓存在本地 DuckDB 文件中。
- 新鲜的缓存条目在后端重启后仍可复用。
- Options Screener、Options Radar、Buy-Side Options Assistant 以及本地期权工具通过共享的 Futu provider 使用该缓存。
- 缓存条目仅供研究，不包含密钥、账户状态或订单指令。

仍未实现：

- 定时刷新
- 通知投递

## 验证

阶段 1 通过以下方式验证：

- 针对性单元测试
- 针对性 API 测试
- 相关的现有期权 API 测试
- 对 AAPL 快照、波动率微笑与波动率曲面的实时 Futu OpenD 调用

所有实时检查均为只读。

阶段 2-4 通过针对性单元与 API 测试验证。这些辅助工具仅在本地运行，不调用 AlphaGBM API。
