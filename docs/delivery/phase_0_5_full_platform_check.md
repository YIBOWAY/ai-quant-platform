# Phase 0-5 完整模拟平台检查记录

本记录覆盖 Phase 0 到 Phase 5 的一次完整加固和端到端演练。目标不是证明策略有效，而是验证系统是否能把数据、因子、信号、回测、风控和模拟交易串起来，并且默认保持安全边界。

## 完成标准

- Phase 5 的关键安全问题有自动化测试覆盖。
- 模拟券商不能买到负现金，不能无持仓卖空。
- 默认 kill switch 开启；只有显式 `--no-kill-switch` 才能跑出模拟成交。
- 订单成交后也要做风控检查并记录风险突破。
- 新增常见技术因子 RSI 和 MACD，并纳入默认因子注册表。
- 单因子信号和多因子信号都能进入回测和 paper trading。
- 使用 SPY + QQQ 跑一遍完整流程并保存结果。

## 本次修改

### 风控和模拟交易加固

- `PaperBroker` 增加现金约束：买入成交量不能超过账户可支付数量。
- `PaperBroker` 增加持仓约束：卖出成交量不能超过已有持仓。
- `RiskLimits` 默认 `kill_switch=True`，与全局安全配置一致。
- `paper run-sample` 支持 `--kill-switch/--no-kill-switch`，不传参数时使用全局安全配置。
- paper trading loop 每次下单前重新构建风控上下文，不复用旧上下文。
- `RiskEngine` 增加交易后组合检查，覆盖单票仓位、日亏损、回撤。
- `OrderManager` 增加交易后风险检查入口，并记录风险突破。

### 因子层增强

- 新增 `RSIFactor`。
- 新增 `MACDFactor`。
- 默认因子注册表现在包含：
  - `momentum`
  - `volatility`
  - `liquidity`
  - `rsi`
  - `macd`
- `factor run-sample` 会一起输出 RSI / MACD 结果。

### 信号到模拟交易打通

- 新增 `run_signal_paper_trading`。
- 它接收 Phase 2/4 生成的 `score_frame`，再交给 Phase 5 的风控、订单管理和 paper broker。
- 策略仍然只产生目标仓位；订单、成交、风控仍由执行层处理。

### 可重复演练脚本

新增脚本：

```bash
python scripts/run_spy_qqq_phase5_full_check.py --source auto --start 2024-01-02 --end 2024-12-31 --output-dir data/phase5_spy_qqq_full_check
```

脚本优先使用 Tiingo。若 Tiingo 不可用，会自动回退到本地样例数据并在结果中记录原因。

## 遇到的问题与处理

| 问题 | 影响 | 处理 |
|---|---|---|
| paper broker 允许负现金买入 | 模拟结果可能严重失真 | 买入成交量按可用现金截断 |
| paper broker 允许裸空卖出 | 与当前 long-only MVP 不一致 | 卖出成交量按已有持仓截断 |
| kill switch 默认值不一致 | 文档说默认安全，但 CLI 可以直接成交 | 统一为默认开启，成交示例必须显式关闭 |
| 只做交易前风控 | 成交后组合可能越界而无记录 | 增加交易后组合检查 |
| 单因子/多因子信号不能直接进入 paper trading | Phase 4 和 Phase 5 没有完全闭环 | 增加 signal-driven paper trading pipeline |
| 本地系统 Python 环境包冲突 | 测试无法可靠运行 | 使用 `conda run -n ai-quant ...` 执行测试和脚本 |
| 本地样例数据过于机械 | RSI 可能没有有效信号 | 真实演练使用 Tiingo SPY+QQQ 数据 |

## SPY + QQQ 演练结果

演练命令：

```bash
conda run -n ai-quant python scripts/run_spy_qqq_phase5_full_check.py --source auto --start 2024-01-02 --end 2024-12-31 --output-dir data/phase5_spy_qqq_full_check
```

数据来源：Tiingo EOD  
数据区间：2024-01-02 到 2024-12-31  
标的：SPY、QQQ  
OHLCV 行数：504  
因子结果行数：2296  
初始资金：100,000  
目标总敞口：50%  
手续费：1 bps  
滑点：5 bps  
本次只做本地 paper trading，没有真实下单。

| 策略 | 回测收益 | 敞口调整收益 | Sharpe | 最大回撤 | 回测成交数 | Paper 成交数 | 风控突破 | Paper 期末权益 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| single_rsi | 10.3984% | 20.7968% | 1.2574 | 6.9763% | 64 | 64 | 0 | 110,398.41 |
| single_macd | 7.0199% | 14.0398% | 0.9815 | 5.1990% | 57 | 57 | 0 | 107,019.88 |
| multi_factor | 8.4413% | 16.8826% | 1.2191 | 5.1990% | 66 | 66 | 0 | 108,441.26 |

同期买入并持有参考：

| 标的 | 近似收益 |
|---|---:|
| SPY | 24.1274% |
| QQQ | 25.9684% |

注意：本次策略只使用 50% 目标总敞口，因此不能直接和 100% 买入持有收益简单比较。

## 产物位置

- 总结 JSON：`data/phase5_spy_qqq_full_check/summary.json`
- 自动生成摘要：`data/phase5_spy_qqq_full_check/summary.md`
- 输入数据：`data/phase5_spy_qqq_full_check/input/ohlcv.parquet`
- 因子结果：`data/phase5_spy_qqq_full_check/factors/factor_results.parquet`
- 单 RSI 策略：`data/phase5_spy_qqq_full_check/strategies/single_rsi/`
- 单 MACD 策略：`data/phase5_spy_qqq_full_check/strategies/single_macd/`
- 多因子策略：`data/phase5_spy_qqq_full_check/strategies/multi_factor/`

## 验证命令

```bash
conda run -n ai-quant python -m pytest tests/test_order_manager_paper_broker.py tests/test_risk_engine_phase5.py tests/test_paper_trading_pipeline_cli.py tests/test_factors_examples.py tests/test_factors_registry.py tests/test_factor_storage_reporting_cli.py tests/test_signal_paper_trading_integration.py -q
```

结果：30 个相关测试通过。

```bash
conda run -n ai-quant python scripts/run_spy_qqq_phase5_full_check.py --source auto --start 2024-01-02 --end 2024-12-31 --output-dir data/phase5_spy_qqq_full_check
```

结果：Tiingo 数据加载成功，三组策略均完成回测和 paper trading，paper 交易风控突破数为 0。

## 当前限制

- Tiingo EOD 当前使用原始 OHLCV，尚未系统处理复权、分红、拆分和点时间成分股。
- 这里只是工程连通性和模拟演练，不代表策略有真实交易价值。
- 现在还没有真实 broker adapter，也没有任何 live trading。
- Paper trading 和 backtest 当前使用同一类开盘成交假设，所以结果非常接近；未来接入真实异步行情后会自然产生差异。
- 目前只有 SPY+QQQ 两个标的，横截面太小，因子统计意义有限。

## 后续建议

- 先扩展到 20-100 个 ETF 或大盘股，再看因子表现是否稳定。
- 加入基准比较、持仓暴露、换手分解和收益归因报告。
- 在 Phase 5 内继续完善 paper trading 的每日状态快照和风险日报。
- 在进入 Phase 6 前，保留 live trading 默认关闭，并要求 checklist 通过后才能考虑 broker adapter。
