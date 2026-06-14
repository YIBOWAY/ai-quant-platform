# 富途前端 / 后端集成报告

## 范围

本报告记录了针对以下内容的富途集成冒烟测试：

- 后端富途行情数据端点
- 前端行情数据页面
- 前端期权筛选器页面
- 中文查询参数版本
- 因子实验室 (Factor Lab)、回测器 (Backtester) 和模拟交易 (Paper Trading) 的研究流程默认配置

## 安全声明

该集成为只读模式。它不会解锁账户、提交订单、修改订单、签署交易或启用实盘交易。

## 环境

| 项 | 值 |
|---|---|
| Conda 环境 | `ai-quant` |
| 后端 | `http://127.0.0.1:8765` |
| 前端 | `http://127.0.0.1:3001` |
| OpenD 主机 | `127.0.0.1` |
| OpenD 端口 | `11111` |

## 验证命令

```powershell
conda activate ai-quant
python scripts/verify_futu_connection.py
```

预期关键行：

```text
PASS read_only_quote_connectivity
```

```powershell
python -m pytest tests/test_data_futu_provider.py tests/test_api_options_futu.py tests/test_options_screener.py -q
```

预期：

```text
passed
```

```powershell
cd src/frontend
npm run lint
npm run build
```

预期：

```text
lint passed
build passed
```

## API 冒烟示例

股票历史数据：

```powershell
curl "http://127.0.0.1:8765/api/market-data/history?ticker=SPY&start=2024-01-02&end=2024-01-12&freq=1d&provider=futu"
```

期权筛选器：

```powershell
curl -X POST "http://127.0.0.1:8765/api/options/screener" `
  -H "Content-Type: application/json" `
  -d "{\"ticker\":\"AAPL\",\"strategy\":\"sell_put\",\"provider\":\"futu\"}"
```

## 前端冒烟检查清单

- `/data-explorer` 以 `futu` 作为数据源加载。
- 可以更改标的代码、日期范围和频率。
- 行情数据页面接受手动输入的标的代码，并渲染真实的 OHLC 蜡烛图。
- 长日期范围使用稀疏的时间轴标签，而非每根 K 线一个标签。
- 当 OpenD 返回数据时，数据源徽标显示 `futu`。
- `/data-explorer?lang=zh` 渲染中文标签。
- `/options-screener` 可以运行基于富途的筛选。
- `/options-screener` 在配置的 DTE 窗口内扫描每个富途到期日；无需手动选择到期日。
- `/options-screener` 不再显示原始期权链预览；该页面聚焦于卖方风格的排名候选标的。
- `/options-screener` 包含用于卖方风格筛选的保守 / 平衡 / 激进预设。
- `/options-screener?lang=zh` 渲染中文标签。
- 因子实验室、回测器和模拟交易表单默认以 `futu` 作为数据源。
- 任何页面均不暴露下单或账户解锁控件。

## 最新本地结果

最近刷新时间：2026-05-03。

OpenD / SDK 验证：

```text
PASS read_only_quote_connectivity
US.AAPL: rows=9
US.NVDA: rows=9
US.MSFT: rows=9
US.SPY: rows=9
option expiries=26
option chain rows=88
```

后端 / 前端冒烟：

```text
health_live=False kill_switch=True
history_source=futu rows=9 first_close=459.991975474
options_candidates=50 scanned_expirations=11 first_rating=Strong first_symbol=US.SPY260512P712000
frontend_data_explorer_status=200
frontend_options_zh_status=200
```

自动化浏览器冒烟：

```text
13 passed (1.6m)
options_screener_ui_ok
data_explorer_zh_ui_ok
options_zh_ok scanned_expirations=11 no_manual_expiration_select=True no_chain_preview=True
data_explorer_ok tick_labels=10
```

质量门禁：

```text
python -m pytest -q      -> passed
ruff check .             -> All checks passed
npm run lint             -> passed
npm run build            -> passed
```

## 已知限制

- OpenD 必须保持运行。
- 富途权限控制字段的可用性。
- 期权筛选器评级为筛选标签，并非投资建议。
- 模拟交易仍为模拟性质，并受现有安全标志控制。
