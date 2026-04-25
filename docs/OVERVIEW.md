# 平台总览（零基础导读）

这份文档用普通话解释这个项目"是什么、能做什么、怎么用"，不需要量化金融背景。

读完之后你能：

- 知道每个目录在干嘛
- 知道四条 CLI 命令分别会产出什么
- 知道哪些事情**绝不会**发生（关键安全边界）
- 知道接下来去看哪份文档

## 这个项目是什么

一个**本地运行**的量化研究脚手架。从历史行情数据出发，研究"什么样的信号可能赚钱"，然后在本地用模拟器验证"扣掉成本之后还有没有钱赚"。

它**不是**：

- ❌ 实盘交易系统
- ❌ 自动下单机器人
- ❌ 接券商 API 的 paper trading 网关
- ❌ AI 自动选策略上线的工具

它**是**：

- ✅ 数据 → 因子 → 回测 → 实验对比的本地研究流水线
- ✅ 一个为后续 Phase 5（风控 + paper trading）做铺垫的基座
- ✅ 输出标准化、可复现、AI Agent 可读的研究产出

## 关键术语（看完这一节就够用了）

| 术语 | 一句话解释 |
| --- | --- |
| OHLCV | 一根 K 线的开高低收成交量；行情的最小单位 |
| symbol | 代码，比如 `SPY` `AAPL`；一个 symbol 是一支股票 / ETF |
| factor（因子） | 一个把价格序列压缩成一个数字的函数，例如"过去 20 天涨幅" |
| signal_ts | 因子值"在这一刻就算出来"的时间戳 |
| tradeable_ts | 这个因子值"在这一刻才能用来交易"的时间戳；通常是下一根 K 线 |
| score | 多个因子值标准化加权后合成的一个综合评分 |
| target weight | 目标仓位占组合的比例，例如 `SPY=0.5` 表示一半仓位放 SPY |
| fill | 模拟成交记录 |
| equity curve | 资金曲线：每一根 K 线之后总权益（现金 + 持仓市值）的时间序列 |
| Sharpe | 年化收益 / 年化波动；风险调整后收益指标 |
| max drawdown | 最大回撤：历史最高点到之后最低点的跌幅 |
| walk-forward | 把时间切成"训练段-验证段"反复滑动，避免一次回测过拟合 |
| PIT（point-in-time） | "这一刻就只能看到这一刻已经发生的事情"；防止未来函数 |

## 五个 Phase 是怎么叠起来的

```
Phase 0  项目骨架（配置 / 日志 / CLI / 安全默认值）
   │
Phase 1  数据层（拉取 OHLCV → 校验 → 存 Parquet + DuckDB）
   │
Phase 2  因子层（OHLCV → 因子值 → IC / 分组收益 / 报告）
   │
Phase 3  回测层（信号 → 目标权重 → 订单 → 模拟成交 → 资金曲线 + 指标）
   │
Phase 4  实验层（多因子合成 + 参数 sweep + walk-forward + 对比报告）
   │
Phase 5  （未来）风控 + Paper Trading
```

每一层只依赖上一层，不依赖下一层。所以你可以单独跑因子研究而不碰回测，也可以单独跑回测而不碰实验框架。

## 仓库目录速查

```text
src/quant_system/
├── config/        Phase 0：从 .env 读设置（API Key、数据目录、安全开关）
├── logging/       Phase 0：结构化 JSON 日志
├── risk/          Phase 0：默认风控参数（kill switch、止损上限等占位）
├── core/          Phase 0：跨阶段的抽象 Protocol（Factor / Strategy / ...）
├── data/          Phase 1：行情数据 provider + schema 校验 + 本地存储
├── factors/       Phase 2：因子基类、注册表、IC/分组评估、报告
├── backtest/      Phase 3：策略 / 订单 / 券商模拟 / 组合 / 引擎 / 指标
├── experiments/   Phase 4：实验配置 / 参数展开 / walk-forward / 多因子打分
└── cli.py         所有命令行入口（quant-system <subcommand>）

tests/             每个模块都有对应单测，pytest 一键跑通
docs/              本目录；按 phase 分四组（architecture / delivery / execution / learning）
data/              本地落盘：Parquet + DuckDB + 报告 Markdown
.env               本地敏感配置（不入版本控制）
```

## 5 分钟跑通：从环境到实验报告

前置条件：Windows + conda 已安装，仓库已 clone 到本地。

### 1. 创建 / 激活环境

```powershell
conda env create -f environment.yml      # 仅首次需要
conda activate ai-quant
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

### 2. 体检

```powershell
quant-system doctor
quant-system config show
```

`doctor` 会打印一行 `dry_run=true, live trading disabled` —— 这就是默认安全状态。

### 3. 拉一段样例数据（Phase 1）

样例 provider 不需要 API Key，会确定性地造一段假的 K 线。如果你已经在 `.env` 配了 `QS_TIINGO_API_TOKEN`，可以换成 `data ingest-tiingo`。

```powershell
quant-system data ingest-sample `
  --symbol SPY --symbol AAPL `
  --start 2024-01-02 --end 2024-01-31 `
  --output-dir data/quickstart_phase1
```

输出：`data/quickstart_phase1/raw/*.parquet`、DuckDB 表 `ohlcv_*`、质量报告 markdown。

### 4. 算因子 + IC 报告（Phase 2）

```powershell
quant-system factor list
quant-system factor run-sample `
  --symbol SPY --symbol AAPL --symbol QQQ `
  --start 2024-01-02 --end 2024-02-15 --lookback 5 `
  --output-dir data/quickstart_phase2
```

打开 `data/quickstart_phase2/reports/factor_report.md` 看看 IC 与分组收益。

### 5. 跑回测（Phase 3）

```powershell
quant-system backtest run-sample `
  --symbol SPY --symbol AAPL --symbol QQQ `
  --start 2024-01-02 --end 2024-02-15 `
  --lookback 3 --top-n 2 --initial-cash 100000 `
  --commission-bps 1 --slippage-bps 5 `
  --output-dir data/quickstart_phase3
```

终端会打印 `total_return / sharpe / max_drawdown`。资金曲线、订单、成交、持仓都落在 `data/quickstart_phase3/backtests/` 下。

### 6. 跑参数 sweep + walk-forward 实验（Phase 4）

```powershell
quant-system experiment run-sample `
  --symbol SPY --symbol AAPL --symbol QQQ `
  --start 2024-01-02 --end 2024-03-15 `
  --lookback 3 --lookback 5 --top-n 1 --top-n 2 `
  --output-dir data/quickstart_phase4
```

每次实验会自动落到 `data/quickstart_phase4/experiments/<experiment_id>/` 下，**不会**覆盖之前的实验。打开 `agent_summary.json` 就是一份给 AI Agent 用的研究摘要。

要跑自定义实验？写一个 JSON 配置丢进 `quant-system experiment run-config --config path/to/config.json` 即可（schema 见 [phase_4_architecture.md](architecture/phase_4_architecture.md)）。

## 安全边界（请逐条阅读）

代码里写死的几条不可绕过的红线：

1. 默认 `dry_run=true`，`live_trading_enabled=false`，`paper_trading=true`。
2. 没有任何模块会向真实券商 API 发送下单请求。
3. 模拟成交只在本地内存里运行，输出落到本地文件。
4. CLI `config show` 永远不会打印明文 API Key（只显示 `**********`）。
5. Phase 4 的 `agent_summary.json` 显式包含 `safety.live_trading=False / paper_trading=False / auto_promotion=False`，AI Agent 不被允许把任何实验自动 promote 到上线。

## 数据落盘约定

跑完一次命令后，`--output-dir` 下的结构是：

```text
<output-dir>/
├── raw/                          Phase 1 原始 OHLCV parquet
├── factors/                      Phase 2 因子结果 / 信号宽表 / IC / 分组收益
├── backtests/                    Phase 3 资金曲线 / 订单 / 成交 / 指标
├── experiments/<experiment_id>/  Phase 4 一次实验的全部产出（不会覆盖）
├── reports/                      所有 Markdown 报告
└── quant_system.duckdb           上面所有结构化数据的 DuckDB 镜像
```

DuckDB 让你可以用纯 SQL 查所有结果：

```python
import duckdb
con = duckdb.connect("data/quickstart_phase3/quant_system.duckdb")
con.sql("SELECT * FROM backtest_equity_curve ORDER BY timestamp DESC LIMIT 10").show()
```

## 下一步去哪儿

- 想快速看每个 phase 干了什么 → [delivery 目录](delivery/) 的 `phase_N_delivery.md`
- 想看每个 phase 的架构图、模块职责 → [architecture 目录](architecture/) 的 `phase_N_architecture.md`
- 想看为什么这样设计、踩了哪些坑 → [learning 目录](learning/) 的 `phase_N_learning.md`
- 想看每个 phase 的日常执行步骤 → [execution 目录](execution/) 的 `phase_N_execution.md`
- 想看跨 phase 的整体设计调研（最长的那份） → [SYSTEM_DESIGN_RESEARCH.md](SYSTEM_DESIGN_RESEARCH.md)

## 常见疑问

**Q: 我没有 API Key 能跑吗？**  
A: 能。所有 `*-sample` 命令用的是 `SampleOHLCVProvider`，确定性地造数据，跟 API Key 无关。Tiingo 命令才需要 `QS_TIINGO_API_TOKEN`。

**Q: 测试怎么跑？**  
A: 在 `ai-quant` 环境下 `python -m pytest`。当前共 68+ 个测试，全部应当通过。

**Q: 我想加自己的因子？**  
A: 继承 [src/quant_system/factors/base.py](../src/quant_system/factors/base.py) 里的 `BaseFactor`，实现 `_compute_values`，在 [registry.py](../src/quant_system/factors/registry.py) 里注册一下。可参考 [examples.py](../src/quant_system/factors/examples.py) 里的 `MomentumFactor`。

**Q: 我想换成真实数据？**  
A: 配置 `QS_TIINGO_API_TOKEN` 到 `.env`，把命令换成 `data ingest-tiingo`，再用 `data/<output-dir>/raw/*.parquet` 喂给后续 phase。

**Q: 这套东西可以直接连 IBKR / Alpaca 上线交易吗？**  
A: 不可以。Phase 5 之前没有任何实盘 / paper trading 接入。任何尝试在当前代码上加 `place_order(...)` 都违反 [docs/SYSTEM_DESIGN_RESEARCH.md](SYSTEM_DESIGN_RESEARCH.md) 里的安全边界。
