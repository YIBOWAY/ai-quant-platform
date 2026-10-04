# 公司研究与 Longbridge 备用数据

侧栏“公司研究”打开 `/zh/company-research`。输入NVDA、AAPL、700.HK等明确代码，先查看已存资料，
点击“更新公司资料”才采集。页面读取、切换页签和比较旧快照不启动模型、回测或交易。

## 可以看什么

- 概览：公司业务、Futu优先的常规时段报价（失败才用Longbridge并显示轨迹）、业务与地区构成。
- 财务：Longbridge IS/BS/CF分表的最新五个财政季度；同比/环比自行重算，8项指标均带公式和缺失原因。
- 事件与观点：公告、新闻、分红与公司行动，第三方盈利预期/分析师观点和内部人交易，分开标来源。
- 数据来源：每节实际provider、抓取时间、摘要、错误；“检查数据源”验证当前symbol的具体能力。
- 公司对比：最多4家，只并列已有快照；报告期可能不同，不把不同期间指标强行排成优劣榜。
- 复制研究问题：带symbol和snapshot_id，方便交给Hermes继续解释；不会自动发送或新建回测。

## 接入和未接入的边界

13个Longbridge Skills中，行情/基本面/内容/研究/情报/财报类的数据命令用于本页。
量化、技术和价值投资类借鉴“明确公式、原始数据、交叉校验”的方法，不复制未经验证的评分或收益。
账户、下单、定投、银行卡和自选写操作没有接入，平台仍是paper-only。

安装Longbridge CLI及授权不会自动赋予历史K线或OPRA行情权限。资料获取成功、数据检查通过、
历史回测有效和模拟成交是不同状态。cashflow的qf/季度身份必须与利润表净利润对齐，否则相应比率留空。
报表日期缺失、跨币种/错期、勾稽冲突不补零；用户看到的是数据计算结果，不是Grok已生成的判断。

新采集保存独立不可变快照；全源失败时保留上次可用内容并显示更新失败。超过24小时标陈旧，
报价自身时段和数据时间另列。重启中断显示失败，GET不自行补跑。

基本面研究线索目前是observation_only，`pit_backtest_ready=false`：有当前财报和rpt_date，
不等于已掌握历史修订、首次公开时刻或当年股票名单。现有OHLCV公式白名单不新增财务字段，
也不会将这些观察直接注册或启用模拟。

## Futu 与 Longbridge 如何分工

Futu保持默认。`build_ohlcv_provider(requested="longbridge")`允许明确读取Longbridge完整日线；
旧的明确futu调用仍严格futu。已有ETF备用CLI现在优先尝试Longbridge，再尝试已配置的其他备用源。
HTTP `/api/market-data/daily-backup?symbols=SPY&start=2026-01-02&end=2026-01-09`
是显式Futu→Longbridge备用读取，返回served_by、fallbacks和真实复权标签。

Longbridge历史按已完成交易日分窗校验，缓存与实时读取同样要求覆盖完整。历史权限失败不会用
最近1000根替代；同一批请求不混两家数据。Longbridge forward不冒称Futu qfq。
已冻结的D34、策略定义、模拟开盘和净值协议不自动换源；这保证旧结果可复核。

## Hermes

安装工具 `~/.hermes/scripts/hqa-company-research.sh`：

```bash
hqa-company-research.sh show NVDA
hqa-company-research.sh section NVDA income
hqa-company-research.sh refresh NVDA
hqa-company-research.sh compare NVDA AAPL
hqa-company-research.sh sources
hqa-company-research.sh check-sources NVDA
```

show/section/compare/sources仅读记录（sources额外识别本机CLI安装版本）；refresh/check-sources会读取外部数据
并写本地快照。命令不调用券商账户或成交，也不创建Grok研究任务。

show/refresh/compare默认输出紧凑摘要、财务指标、来源与快照身份；section按需读取一节原始资料。
这不影响网页完整展示，也不会把原始报表丢掉。向Hermes询问“查看NVDA最新财报，解释收入增长和
现金流与利润的差异”即可走同一工具；本轮验证了安装后的实际工具输出，没有另发模型消息。

## 本次实际验收（2026-09-12）

15:08（北京时间）从正式页面更新NVDA，14/14资料章节取得数据，保存为独立快照；
财务五个财政季度可比，16项一致性检查通过。公司业务构成的来源披露日期早于期末，仍保留警告，
不能据此建立历史事件信号。15:12的权限检查为partial：报价、最近日线、季度财报和期权链可用，
指定日期历史日线quota_exceeded，期权报价permission_denied。一次NVDA成功不代表其他股票全部可用。

验收数据、测试、部署与浏览器证据见[交付收据](../receipts/2026-09-12-longbridge-company-research.md)。
