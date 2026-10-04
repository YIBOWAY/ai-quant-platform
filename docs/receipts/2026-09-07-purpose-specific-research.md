# 按用途研究、回测修复与一次真实因子探索

日期：2026-09-07。范围为本地研究和展示，未改模拟成交路径、准入阈值或账户，没有发起 canonical research job 或启用策略。

## 结论

原 10 ETF 每日 Top-3 只是特定用法，不能代表全部因子的效果。保留它为“原 ETF 诊断”，新默认页“按用途研究”分别评价股票月度动量、价格多因子、跨资产轮动、指数趋势和指数短期回归。源码缺陷与策略本身较弱分开处理，不以跑赢 QQQ 作为修改停止条件。

独立审计详见 [回测核心与九项用途研究复核](../audits/2026-09-07-core-backtest-methodology-audit.md)。原四组反例已修复，新增九方案的信号日期、执行日期、同池对照和训练截断均经过独立检查。该审计不认可任何策略已经有可交易 alpha。

## 本批固定研究协议

在读取本批结果之前固定以下九方案，无参数寻优、加杠杆或收益截尾。资金 100,000 美元；已知收盘后下一真实交易日开盘交易；单边佣金 1bp、滑点 5bp，现金利息及风险自由利率均为 0。Futu 日线 QFQ，不冒充含分红再投资的总回报。

| 用途 | 规则 | 主基准与同池对照 |
|---|---|---|
| 科技 9 股动量 | 12–2 月动量，跳过最近一个月，Top3 等权月调仓 | QQQ；同 9 股等权月调仓 |
| 跨行业 24 股动量 | 同一形成方法，Top5 等权月调仓 | SPY；同 24 股等权月调仓 |
| 跨行业价格多因子 | 12–2 月动量、252 日低波动、1 月短反转，各转横截面百分位后等权，Top5 月调仓 | SPY；同 24 股等权月调仓 |
| 五类资产轮动 | 3/6/12 月收益平均，Top3 月调仓 | SPY；五类资产等权月调仓 |
| 五类资产轮动＋趋势 | Top3 中跌破 10 月均线的份额转 SHY | 同上 |
| SPY / QQQ 趋势各一项 | 月末高于 10 月均线持有指数，否则 SHY | 相同指数买入持有 |
| SPY / QQQ R2 各一项 | Wilder RSI(2)、SMA200、连续 RSI 回落入场，RSI>75 退出 | 相同指数买入持有 |

股票清单直接取本项目现有 technology、defense、healthcare registry，排除 ETF，并在本批固定；不是对看过的结果筛出来的优胜股票，但仍是今天存续的静态名单。

- 科技：AAPL、MSFT、NVDA、AMD、GOOGL、META、AVGO、ORCL、CRM。
- 24 股增加：LMT、RTX、NOC、GD、HII、LHX、BA、UNH、JNJ、PFE、MRK、ABBV、TMO、MDT、AMGN。
- 跨资产：SPY、EFA、IEF、VNQ、DBC；防守代理 SHY。
- 每期 peer 只包含与策略满足相同历史资格的股票。缺历史不前填，不把未来上市股票放进过去；必要成交价格缺失直接失败。

原作者依据与项目改编分别保存于 `study_profiles.py` 和页面，主要来源：

- [French 月度动量](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/det_mom_factor.html)：原版为规模分组、价值加权多空，本项目只做多等权，不能把它称为原版因子复制。
- [French 短期反转](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/det_st_rev_factor.html) 与 [S&P 低波动方法](https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-low-volatility-indices.pdf)：价格三因子为固定组合改编，不包含基本面 value/quality。
- [Faber 跨资产动量](https://mebfaber.com/2008/08/07/alpha-persistence-a-simple-momentum-system-for-beating-the-market/) 与 [10 月趋势方法](https://mebfaber.com/2017/12/13/episode-86-quantitative-approach-tactical-asset-allocation/)：项目改用 next-open 和 SHY，不借用原文收益。
- [Connors Improved R2](https://tradingmarkets.com/recent/the_improved_r2_strategy_84_correct_with_just_6_rules_-674361)：此处 RSI(2) 进出场，与旧 RSI(14) 横截面组件不同。

## 真实数据与结果

Futu 31 个标的共 91,016 行，数据 2015-01-02—2026-09-04，用于预热和评价；实际评价为 2018-01-02—2026-09-04，2,181 个交易日。31 个标的全部取得，没有缺标的替代、sample 或 mock。首次整批获取碰到上游超时后，改为逐标的取得并复用已校验、同请求的快照；每项均保留原始 SHA、来源、取得时间。

研究 `study-10b60ea40d94441abadb5ccf2b668fb5`，行情 SHA `febe42c5c2eadfd4af5d3cc0196fb0e68d197daccc18d7ce138b74d94a6e7133`；计算摘要 `d916b96c13a470e8a44f34bfc1180a1ac832e5ed3448ca6bcf67d8fcc1c52c63`。

| 方案 | 扣费累计收益 | 年化收益 | Sharpe | 最大回撤 | 主基准累计 | 同池累计 |
|---|---:|---:|---:|---:|---:|---:|
| 科技 9 股月动量 | 2,850.66% | 47.86% | 1.215 | 41.79% | QQQ 387.07% | 1,153.61% |
| 跨行业 24 股月动量 | 800.10% | 28.90% | 0.999 | 31.72% | SPY 227.35% | 400.41% |
| 24 股价格三因子 | 131.01% | 10.16% | 0.560 | 36.94% | SPY 227.35% | 400.41% |
| 五资产动量 | 160.88% | 11.72% | 0.902 | 28.08% | SPY 227.35% | 100.79% |
| 五资产动量＋趋势 | 121.57% | 9.63% | 0.938 | 13.56% | SPY 227.35% | 100.79% |
| SPY 10 月趋势 | 78.87% | 6.95% | 0.578 | 27.80% | SPY 227.35% | 同主基准 |
| QQQ 10 月趋势 | 252.73% | 15.68% | 0.856 | 28.65% | QQQ 387.07% | 同主基准 |
| SPY R2 | 25.45% | 2.65% | 0.291 | 31.42% | SPY 227.35% | 同主基准 |
| QQQ R2 | 40.72% | 4.03% | 0.441 | 13.67% | QQQ 387.07% | 同主基准 |

这些数字不是找回用户旧项目的“800%”，而是本次独立固定规则计算。跨行业月动量收益高于同池，但同池 Sharpe 为 1.074，高于策略 0.999；策略的更高收益也伴随更多波动，不能仅凭累计收益说全面更好。科技名单本身回报极高，也直接显示了幸存者和股票池选择的影响。三因子没有胜过单动量，不能因为多因子就宣称改进。

2025-01-01—2026-09-04 的独立时间分区中，24 股月动量 72.45%、同池 51.69%、SPY 33.66%；三因子 28.46%。这些时期没有参与本批调参，但历史早已可被查看，仍不是前瞻实盘证据。

## RD-Agent 与 Qlib 真实工作

使用已有镜像 `hqa-qlib-evaluation:0.1.0`，实际 RD-Agent `APIBackend`，上游提交 `274e274d5dbb72cc2ea139d1a7c93d73ce9b1198`。配置为 `openai/grok-4.6`、`xhigh`、stream，一次请求，无自动续写/重试。沿用既有容器可达代理与 owner-only env 文件。最初源终端没有加载 env 路径，属于运行配置遗漏，补用现有 `QS_D34_ENV_FILE` 后真实调用成功，未更换模型或凭证。

只传入 2018–2021 两项固定股票协议的训练统计、股票清单；输入字段严格限定，不传验证/测试收益。三项提议全部先冻结、再计算，不按测试结果回改；数值常数、全缺失或同批完全相同排序会保留拒绝原因。模型固有知识可能知道 2021 以后的历史，因此不声称彻底消除模型历史知识偏差。

| 冻结公式 | 2025 起扣费收益 | 同池 | SPY |
|---|---:|---:|---:|
| `Mean($close,21)/Mean($close,63)` | 19.35% | 51.69% | 33.66% |
| `Min($low,21)/$close` | -7.90% | 51.69% | 33.66% |
| `Sum($volume,5)/Sum($volume,21)` | 21.54% | 51.69% | 33.66% |

三项全部成功计算，但全部未胜同池；展示失败的研究结论，不挑选其中较好的一条冒充发现 alpha。真实 proposal 文件 SHA `9106caf0d9c0edaf7c84b5dc5b22964e96487b9d20168d54ae06fe533d838fc4`，生成于 `2026-09-07T09:19:23.746535+00:00`，attempts=1。调用分支的等价简化没有再次请求模型；缓存标识改为提示/方法协议摘要，避免格式调整导致看过测试后再生成一批。冻结文件内容与 SHA 未变。

Qlib `calc_ic` 真正处理月度信号：标签为实际次月入场开盘到下一次月调仓开盘，而非将日频标签生搬到月频。跨训练截止的标签剔除，未成熟末月不补数；24 股训练区间为 46 个完整月、1,104 个样本。单标的择时不计算横截面 IC。平台引擎负责交易、成本和组合指标，Qlib 负责适配持有期的信号诊断；已有 RollingGen/Ridge 的滚动与增量仍保留。

## 原报告确实重算

修复为：MACD 柱值按当日价格归一化；形成期保留公共交易日缺口；预测映射不使用全标的日期交集；Qlib 最后标签只计到退出开盘；底层指标纳入初始本金至第一条净值的损益，reference 不再重复补初始行。

| 原对象 | 新运行 | 结果 |
|---|---|---|
| catalog | `evaluation-fa2adacaa1c54313a23e3df126edff20` | ready，19 折 |
| research:artifact-a604ad9ad2792c32 | `evaluation-28dbaef1103f4527896b2783fc953e5c` | ready，19 折 |
| research:artifact-d489583fb04bdc04 | `evaluation-b9379fdc003c430d9e98b80bf9deced9` | ready，19 折 |

三份输入行情 SHA 各自未变，特征 SHA 均变化，source digest 为 `7a153b294658a10e4050ce93a4ca216e1375edb83435ed8bc0c57d4481955be8`。MACD 参考累计收益 48.7057%→76.2907%、Sharpe 0.33094→0.42836、回撤 42.1354%→29.7331%。旧报告留在旧 run 目录，不重绑版本标记。

## 用户旧仓库核查

只读 GitHub API/笔记本 JSON，未 clone、执行远端笔记本或导入代码：

- `YIBOWAY/APEXUSTech_Inter`，检查提交 `fe16857837fbe75b634a3f6c88317e7dc3c465a5`。`project4/YiboSun_Project4_26_08_V3.ipynb` 有月度科技股风险调整动量、Top30% 和动态现金；保存的短区间结果为 44.6323%，不是 800%。其一些“年化”用月均收益年化而非 CAGR；基准月末日期对齐错位、持仓实际收益的 1%/99% 截尾会影响可实现收益比较。
- 同仓 `project4/test2.ipynb` 的 Top/Bottom20% 多空保存结果为 43.3491%，也不支持 800%。V4/V5 无相应输出。
- `YIBOWAY/Quant_Bootcamp`，检查提交 `54a5e5f5d240e19fbe77c248477ee663c1ef509f`。`standard_12w/notebooks/phase3/03_multi_stock_and_comparison.ipynb` 有 20 日动量 Top5 月换仓，但用 `DataLoader(mode="sample")` 且没有支持 800% 的保存输出，不能搬来作真实数据证明。
- public APEX 仓库的 `YiboSun_Project1_25_07.ipynb` 存在 Tiingo/Polygon 凭证赋值；未复制、使用或记录值。应由 owner 撤销/轮换，不把凭证带入本项目。

## 页面与接口

`/research-evaluation` 默认“按用途研究”；按用途/方案选择，全标的中文清单、明确交易规则与来源，未扣费/扣费/主基准/同池四列指标，三条净值曲线，逐年/分期、Qlib 信号表现与最近历史目标。

`GET /api/strategy-studies` 仅返回保存结果。`POST /api/strategy-studies/refresh` 沿用 owner/CSRF/Origin，默认 `include_discovery=false`，true 才请求因子探索；同选项运行中去重，不同选项返回 409。仅更新固定方案时保留上次因子探索；行情或计算变化则标旧结果。完整信号/成交保留在文件，API 仅发送最新历史信号和降采样曲线；缺值不填 0。

保存位置为部署 data 下 `strategy_studies/runs/<run>`、`strategy_studies/hypotheses/<training+protocol digest>` 及 `research_evaluations/runs/<run>`。源仓不保存真实行情、正文或凭证。

## 验证与部署

相关后端最初一组 102 项：90 passed、12 host skipped；跳过的 Qlib/RD-Agent 依赖已另在真实容器通过聚焦检查。新增保留历史探索测试后，该服务 7 项通过；模型分支等价简化后相关 38 passed / 1 host skipped。前端相关 20 项、TypeScript、局部 ESLint 与 Next 生产构建通过。新增/修改后端文件 Ruff 通过；扩大到整个 research 目录时，未修改的 `trials.py` 有 24 项原有 lint，未擅自修它。

浏览器工具仍引用已移除的 `26.901.31953/browser-service.mjs`，当前插件为 `26.901.51231`；没有绕过工具限制或声称截图验收通过。页面构建和组件检查不等于真人浏览器验收。

产品代码提交 `20e0ebae`。2026-09-07 17:32（北京时间）部署镜像从 `fe08b2c7` ff-only 到该提交，使用 `scripts/local_mac_stack.sh start` 完成镜像内生产构建及正常启动。运行时生成的两份 options_universe CSV 改动保留，未回滚。

部署后 `:3001/zh/research-evaluation` 为 HTTP 200，SSR 包含新默认“按用途研究”和“先确定用途，再看回测”；同源 `/api/strategy-studies` HTTP 200、ready，返回上述 9 个固定方案和 3 个实际 Grok 公式结果，model/effort 为 `openai/grok-4.6` / `xhigh`。同源原 `/api/research-evaluation` 为 ready，指向实际重算的新 catalog run。正式 API 序列化也已验证保留 latest_signal、剔除完整 signals/trades，计算摘要匹配。

Ponytail 前两次要求合并重复 completion 分支、复用生成 API 类型，均处理；第三次通过后正常提交。模型请求没有因等价简化重发，原冻结 proposal SHA 未变。没有推远端、迁移数据库、发新 canonical 研究或执行模拟观察周期。
