# US Stock Crash Monitor 源码评估

日期：2026-09-05。结论：可借鉴风险分量解释方式；原总分不能作为本项目的崩盘概率或交易依据。
本次通过 GitHub API 和固定提交的 raw 文件只读审阅；没有 clone、安装依赖或运行远端 Streamlit App。
只提取已审阅的两个纯计算函数，在独立进程执行数值反例；没有访问其行情接口或执行顶层页面代码。

## 1. 固定源码与范围

- 仓库：[middletoo/US_Stock_Crash_Monitor][repo]。
- 提交：`deaefd6188003bdfc11c2349bb9ba5379e049aa9`，时间 `2025-12-21T13:18:19Z`。
- GitHub 完整树 `truncated=false`，只有 `app.py`、`README.md`、`README_EN.md`、`LICENSE`、`main2.png`。
- `app.py` 共 642 行、22,922 bytes；SHA-256 为 `62720e5b6d09ae5d8a7c6fea240acdfc9258b496d7ad6b7fa2f3f29f3318a9e5`。
- 仓库没有回测模块、测试、训练集或历史行情数据集。以下结论来自代码，不以 README 的效果宣称代替验证。

## 2. 五项指标的实际计算

下表区间按源码的严格大于/小于关系整理；数值是启发式分档，不是统计估计的概率。

| 指标 | 实际数据与公式 | 原风险分档 |
|---|---|---|
| Buffett | 手填总市值/GDP×100；默认 59/29 万亿美元 | ≤120→25；(120,150]→50；(150,180]→75；(180,200]→90；>200→100 |
| CAPE | 手填，默认 40 | ≤25→20；(25,30]→50；(30,35]→70；(35,40]→90；>40→100 |
| 10Y−2Y | 10Y 尝试读取 `^TNX`；2Y 手填默认 4.20；单位百分点 | <−0.5→80；[−0.5,0)→60；[0,0.5)→70；≥0.5→30 |
| 200MA 乖离 | `(最新收盘/SMA200−1)×100` | >25→100；(20,25]→85；(15,20]→65；(5,15]→40；<−10→10；其余→20 |
| Fear & Greed | 手填，默认45；没有 CNN 数据读取器 | <20→0；[20,60]→40；(60,80]→70；>80→100 |

默认权重依次为15%、25%、25%、20%、15%，总分直接相加。切换 VOO/QQQ 只改变价格相关输入，
其余四项宏观/情绪输入不随标的变化。依据：[输入与权重][inputs]、[完整评分函数][score]。

## 3. 六项实质问题

1. **故障混入虚构数据。** ETF 获取失败生成随机价格；10Y 单独失败则静默填 `4.0`，仍返回
   `is_mock=False`，页面显示“实时连接”“自动获取”。缓存一小时，没有行情日期检查。[数据获取][fetch]、[状态展示][status]
2. **过热与当前压力混淆。** 跌到200MA下方30%时技术风险仅10分，极端恐慌情绪也贡献0分。
   这表达的是反向过热观点，不能表示下跌过程中的压力；不能直接当作卖方期权或持仓风险开关。[评分函数][score]
3. **缺失值被算成正常。** 缺SMA200时设0乖离、给20分；价格NaN也落入20分分支。
   GDP输入没有正数约束，0会除零。原代码没有完整的有效性、日期、发布时点或覆盖率口径。[输入][inputs]、[评分函数][score]
4. **“解挂”没有历史证据。** 当前利差在[0,0.5)就显示“解挂/平坦(危)”，函数不接收过去利差，
   无法证明之前倒挂。衰退也不等于股市崩盘；纽约联储相关模型估计未来12个月衰退概率，使用10Y−3M。[评分函数][score]、[纽约联储][nyfed]
5. **权重与展示尺度不一致。** 五个滑块各允许0–50%，总和非100只警告、不归一化；全0得0分，
   全50%可得240分。仪表盘固定0–100，颜色分界40/70，文字建议分界却是60/80。[输入][inputs]、[仪表与建议][advice]
6. **历史比较不是回测。** 三组宏观输入和Price/SMA是人工常数，没有未来收益、事件标签、误报率、
   预测窗口或样本外检验。其2008“崩盘前夜”快照按默认权重得52.25，页面分类恰好是Safe Zone。[历史输入][history]、[历史展示][history-view]

“历史阈值”“崩盘线”等文案不能证明预测能力。没有发现收益率、命中率或概率校准的可复算证据。

## 4. 纯函数验证与原文证据

使用标准库 `urllib.request` 读取固定 raw 源码，`ast.parse` 后仅保留
`calculate_risk_score` 与 `get_historical_benchmarks` 两个 `FunctionDef`；提供 `np.isnan=math.isnan`。
默认输入为价格=SMA=100、10Y=4.15、2Y=4.20、Buffett=59/29×100、CAPE=40、Fear=45。
技术反例仅令technical权重=1；最高分反例令各权重=.5，并输入130/100、利差−1、Buffett220、CAPE45、Fear90。

```text
PINNED_SOURCE 22922 bytes
62720e5b6d09ae5d8a7c6fea240acdfc9258b496d7ad6b7fa2f3f29f3318a9e5
DEFAULT_MANUAL_INPUTS_PRICE_AT_SMA 62.5
PRICE_30_PERCENT_ABOVE_SMA 100.0 (100, 30.0)
PRICE_30_PERCENT_BELOW_SMA 10.0 (10, -30.0)
MISSING_SMA 20.0 (20, 0)
MISSING_PRICE 20.0 (20, nan)
ZERO_WEIGHTS 0
MAX_ALLOWED_SLIDERS 240.0
HARDCODED_HISTORICAL 2000 互联网泡沫 (Top) 70.5 UI_LABEL Elevated Risk
HARDCODED_HISTORICAL 2008 次贷危机 (Pre-Crash) 52.25 UI_LABEL Safe Zone
HARDCODED_HISTORICAL 2022 加息熊市 (Top) 62.0 UI_LABEL Elevated Risk
```

复算入口：[固定 raw 源码][raw]；模型与历史输入均无随机操作，以上反例不依赖实时行情。
这证明上述软件行为，不证明任何新模型有效，也不是本项目的历史交易表现。

## 5. 本项目已选整合方案

以下方案已在本项目重新实现并部署至 `/zh/watch?pane=cross`。实现、测试和正式页面收据见 [本批实际使用评估](2026-09-05-personal-quant-usability.md)；此部署结论不代表阈值已经过预测校准。

- **趋势与回撤**：复用现有Futu日线，展示SMA200位置、距近252交易日最高收盘的当前回撤。
  跌破200MA、回撤≤−10%作为可解释的观察条件；高于200MA15%单列过热背景，不将下跌解释为低风险。
- **波动压力**：读取本地真实VIX序列，展示水平与相邻交易session变化；VIX≥30、单日升幅≥20%仅作观察规则。
  VIX/VIX3M只使用同session、分别通过日期检查的点值；不使用历史平均期限比替代当前比值。
- **输入诚实**：不足200/252个有效交易观测则相应项不可用；两条波动序列分别展示日期。
  缺失或陈旧数据不补0、不补固定数、不转随机数据；固定板块篮子的扩散注明范围，不冒充全市场宽度。
- **展示目的**：每项展示数值、触发条件、来源和日期，帮助决定今天应关注什么。
  不继承综合0–100总分、崩盘概率、权重面板或由分数直接推导的减仓/买Put文案。

上述阈值尚未校准，只是公开显示的观察规则。VIX从10升到12也会触发20%变化，应解释为波动升温，
不能称为崩盘预警；“近252日最高收盘回撤”也不能写成完整历史最大回撤。

Buffett、CAPE、收益率曲线暂不纳入该评分。未来若接宏观，可采用[FRED同口径T10Y2Y][fred]；
必须以真实历史判断倒挂/回正。Buffett分母应与美元市值保持一致口径；原链接指向real GDP，
[BEA明确区分通胀调整后的real GDP与当期价格nominal GDP][bea]。本批没有补造这些宏观数值。

## 6. 许可与归属

上游为 **MIT License，Copyright (c) 2025 竹林寺**。[许可原文][license]允许修改、合并和分发，
要求代码副本或实质部分保留版权与许可文本。若复制实质代码，应随代码保留原许可；仅借鉴机制并基于
本项目现有输入重写，也在本文件记录固定来源。仓库许可不代替行情或宏观供应方的数据使用条件。

## 来源

[repo]: https://github.com/middletoo/US_Stock_Crash_Monitor/tree/deaefd6188003bdfc11c2349bb9ba5379e049aa9
[raw]: https://raw.githubusercontent.com/middletoo/US_Stock_Crash_Monitor/deaefd6188003bdfc11c2349bb9ba5379e049aa9/app.py
[inputs]: https://github.com/middletoo/US_Stock_Crash_Monitor/blob/deaefd6188003bdfc11c2349bb9ba5379e049aa9/app.py#L188-L270
[score]: https://github.com/middletoo/US_Stock_Crash_Monitor/blob/deaefd6188003bdfc11c2349bb9ba5379e049aa9/app.py#L277-L373
[fetch]: https://github.com/middletoo/US_Stock_Crash_Monitor/blob/deaefd6188003bdfc11c2349bb9ba5379e049aa9/app.py#L105-L168
[status]: https://github.com/middletoo/US_Stock_Crash_Monitor/blob/deaefd6188003bdfc11c2349bb9ba5379e049aa9/app.py#L429-L441
[advice]: https://github.com/middletoo/US_Stock_Crash_Monitor/blob/deaefd6188003bdfc11c2349bb9ba5379e049aa9/app.py#L465-L503
[history]: https://github.com/middletoo/US_Stock_Crash_Monitor/blob/deaefd6188003bdfc11c2349bb9ba5379e049aa9/app.py#L379-L422
[history-view]: https://github.com/middletoo/US_Stock_Crash_Monitor/blob/deaefd6188003bdfc11c2349bb9ba5379e049aa9/app.py#L575-L628
[license]: https://github.com/middletoo/US_Stock_Crash_Monitor/blob/deaefd6188003bdfc11c2349bb9ba5379e049aa9/LICENSE#L1-L21
[fred]: https://fred.stlouisfed.org/series/T10Y2Y
[nyfed]: https://www.newyorkfed.org/research/capital_markets/ycfaq.htm
[bea]: https://www.bea.gov/resources/learning-center/what-to-know-gdp
