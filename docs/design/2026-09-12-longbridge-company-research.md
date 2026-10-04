# Longbridge 备用数据与公司研究

实施范围由2026-09-12主人明确授权。Futu保持默认；Longbridge复用当前CLI授权，不读写token，
不接券商订单/资产/定投，不部署第二个模型或回测器。

## 交付

1. Longbridge严格只读CLI客户端、日线provider和既有显式backup_bars接线。
2. 公司研究页：Futu优先报价/Longbridge备用，财务分表、估值、业务构成、文件/新闻、公司行动、
   分析师和内部人记录。字段缺失、限流、权限和时效分别保留，不输出假数据。
3. 同期财报重算增长率、勾稽检查和基本面观察指标。指标只作研究线索，不假装PIT回测或已准入因子。
4. Hermes独立公司研究工具，复用同一份平台快照；增加基本面资料入口而不改变现有OHLCV公式权限。
5. 数据源能力页/接口可显式检查实际权限；备用历史取数失败保留完整原因，不用latest偷补长历史。

## API（根代理拥有）

- GET `/api/company-research?symbol=NVDA`：仅读已保存快照，初次not_loaded，不启动provider。
- POST `/api/company-research/refresh` body `{symbol}`：owner/CSRF，202，按symbol及全局有界锁后台采集。
- GET `/api/company-research/compare?symbols=NVDA,AAPL`：最多4个，仅读已有快照，不混报告期排名。
- GET `/api/data-sources`：只读CLI安装版本及上次实际检查，不调用行情，不把installed当ready。
- POST `/api/data-sources/check` body `{symbol}`：有界检查报价/最近K线/指定历史/财报，保存结果。
- GET `/api/market-data/daily-backup?symbols=SPY&start=...&end=...`：显式备用入口，
  Futu后Longbridge，一次请求整批同源，不拼接两个源；返回served_by/fallbacks和实际复权标签。

`CompanyResearchResponse`结构以api/schemas/company_research.py为准。
sections keys为quote/company/valuation/income/balance/cashflow/segments/dividends/corporate_actions/
news/filings/consensus/ratings/insiders。每节独立status/provider/operation/fetched_at/raw_sha256/source_url/reason。
data为该来源原始JSON（quote节规范化为last/currency/as_of/pre_market/post_market/overnight），
financials为纯函数诊断结果。headline和summary由真实指标及检查规则生成，不冒充Grok解读。

## 界面（前端worker拥有）

新增 `/company-research`，侧栏在市场研判之后显示“公司研究”，保留现有全站搜索目的地。
输入股票代码、查看记录、明确的更新按钮；概览/财务/事件与观点/数据来源四个tab。
概览解释主营和现有财务表现；财务展示多期表格、8个带公式指标和实际检查；
事件分开公司行动、新闻/公告和分析师观点，不将第三方意见当系统买卖信号。
支持复制带symbol+snapshot_id的Hermes研究问题；不自动发送。
来源tab显示备用轨迹、权限检查和未覆盖的PIT条件。未加载/更新中/部分失败/陈旧都可见。
中英文、移动端和键盘可用，沿用现有深色金色主题，优先可阅读的表格，不堆空指标卡。

## 数据与验证

原始快照与JSON摘要文件分离，按symbol+snapshot_id保存，历史不被新采集覆盖；
GET不写，刷新中断可见，单节失败保留其他真实结果。采集按CLI限流顺序执行，不并发扫全市场。
同比自行按上一年同季计算，不相信上游名为yoy却实际为环比的字段。
报表期、发表日期、抓取日期分别保存；有rpt_date不代表有历史修订/PIT数据。
既有策略、候选、回测和模拟都保持冻结来源，明确请求futu不换成longbridge。
不得把Skill中的Graham/Buffett评分模板或未验证策略自动注册、启用或推广为收益证明。
