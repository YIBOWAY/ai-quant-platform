# Longbridge备用数据与公司研究交付

> 本地路径说明（公开版）：文中未随本版提供的 `artifacts/`、`evidence/` 和运行目录是本地证据坐标或路径示例，原件未公开；不能把路径存在当作公开证据。详见[公开范围说明](../publication-20261004.md)。

日期：2026-09-12，Asia/Shanghai。用户明确授权Longbridge作为备用，并结合全部13个Skills补充公司研究能力。
本轮主体代码Platform `f6f027ea`、HQA `21c3827`；实际页面字段适配和Hermes摘要另有窄修提交。

## 用户可见结果

侧栏工作台 → **公司研究**，位于市场研判之后；实际页面
http://127.0.0.1:3001/zh/company-research?symbol=NVDA 。

- 概览：公司主营、来源明确的报价、估值、业务和地区构成。
- 财务：最新五个财政季度三表、营收同比/环比、毛利率、净利率、资产负债率、流动比率、
  单季毛利润/期末资产、经营现金流/净利润；显示公式、缺失原因和报表一致性检查。
- 事件与观点：公告原文链接/日期、新闻、分红、公司行动、第三方盈利预期/机构评级、内部人记录。
  授予/行权记录不直接称看多或看空，分析师目标价不称平台预测。
- 数据来源：每节来源、操作、抓取时刻、数据SHA、快照ID；可检查该股票的实际权限。
- 对比最多四家公司已有资料，保留不同财年/币种/报告期，不伪造可比排名；复制给Hermes的问题绑定股票和快照ID。

页面读取/切换/比较不采集。更新公司资料和检查权限是两个明确按钮，更新中GET轮询只读取状态。
当前页面总结由已计算指标和规则生成，不是本轮调用Grok生成的散文。

## 13个Skills如何采用

全部本机SKILL.md和有关CLI引用已由主代理阅读，没有把所有模板直接搬进平台。

| Skill | 采用方式 |
|---|---|
| longbridge | 复用CLI已登录会话、命令和代码规范；不新装MCP或另建模型链 |
| market-data | 报价备用、最近日线与指定日期历史能力检测、完整历史provider |
| fundamentals | IS/BS/CF分表、业务构成、分红/公司行动、估值、公司概况 |
| content | 公告与新闻记录，保留实际URL/日期 |
| research | 一致预期、评级及内部人公开记录，第三方观点单列 |
| earnings | 同期报表对照、增长与现金质量检查；未伪称完整财报电话会研究 |
| intel | 可用于资料研究，但本轮不扩自动股票池或搬入供应商选股排名 |
| derivatives | 白名单期权链/报价能力与实际权限检测；现役卖方扫描仍Futu |
| quant | 公式、收益验证与输入口径分离；当前财务数据不直接加入历史价量因子 |
| technical | 不复制未经本地验证的技术评分或策略收益 |
| value-investing | 采用原表交叉核对；未把模板DCF/巴菲特评分当事实或交易信号 |
| portfolio | 不接券商账户、下单、定投和银行卡；平台模拟账保持原管道 |
| watchlist | 不修改券商自选/提醒，不依赖私有持仓扩大本轮采集范围 |

这次新增的是可用的资料、财务检查与研究入口，不是每个Skill里所有功能的产品化。

## Futu默认与Longbridge备用

Longbridge 0.28.5通过固定argv、白名单命令调用；拒绝任意shell/标志，错误使用固定分类，
不把stderr或token写入页面。每次读取有超时、输出上限、并发/频率约束。

公司报价优先Futu，失败后用Longbridge并记录fallback轨迹。已知美股Futu update_time为美东时间；
它按快照更新时间展示，不冒称最后成交时间或UTC。价格字段与盘前/盘后字段分开，
依据[Futu快照文档](https://openapi.futunn.com/futu-api-doc/quote/get-market-snapshot.html)。

新增`build_ohlcv_provider(requested="longbridge")`，现有显式backup_bars流程接Longbridge；
HTTP `GET /api/market-data/daily-backup`为明确备用读取入口。一次请求整批同源，保留
Longbridge forward标签，不冒称Futu qfq，不把两个源拼接为同一次回测输入。
完整历史按已完成交易日分窗核查；旧缓存如果在收盘后缺新的一天，也不能继续作为完整结果。

**没有给所有旧消费者统一加静默fallback。** 已冻结D34、StrategyDefinition、模拟开盘/估值、
卖方期权协议仍按既有来源执行。长桥未获历史/期权报价权限时，不能称已有全面灾备能力。

## 实际数据收据

生产新页面于15:08:07发起唯一一次`POST /api/company-research/refresh`，返回202，
15:08:21后台终态available。股票NVDA.US，14/14章节获得数据（1个Futu报价、13个Longbridge资料节）。

- snapshot_id：`918b7ca98783db644e5f1acfe47acf0041a85c748020ba24abf157931bcccd1c`
- updated_at：`2026-09-12T07:08:21.356954+00:00`
- 最新财政季度FY2027Q2，期末2026-07-26，披露日期2026-08-26，USD；不能把2027财年误写成未来日历年。
- 最新营收96,221,000,000，去年同期46,743,000,000，重算同比105.8511%；
  季环比17.8962%，毛利率74.9753%，经营现金流/净利润0.40338。
- 五期财务数据，16项一致性检查通过（币种与各期报表勾稽）。原始JSON和公式均保留。
- 业务构成来源的披露日期早于报告期末，明确提示不能当历史事件信号。

15:12:46页面唯一一次`POST /api/data-sources/check`，15:12:55完成partial，8项中6项可用：

| 本次NVDA检查 | 实际状态 |
|---|---|
| Futu报价 | available |
| Longbridge报价 | available |
| Longbridge最近已收盘日线 | available |
| Longbridge指定日期历史日线 | unavailable / quota_exceeded |
| Longbridge季度财报 | available |
| Longbridge期权到期日 | available |
| Longbridge期权行权价列表 | available |
| Longbridge期权报价 | unavailable / permission_denied |

checked_at `2026-09-12T07:12:55.364788+00:00`。这是本机账号、该股票、该次请求的证据，不推广成全市场全权限。
本轮没有购买行情、重新授权或修改账号权限。

真实文件在[验收目录：本地原件未公开](../publication-20261004.md)：
`nvda-real-snapshot.json`、`nvda-real-source-check.json`、`browser-qa-receipt.json`、
`browser-source-check-receipt.json`和`readonly-browser-qa-receipt.json`。

## Hermes接线与保留内容

独立安装`~/.hermes/scripts/hqa-company-research.sh`和`hqa-company-research` Skill，
现役hqa-quant路由增加公司研究入口。show/compare/sources/section读取平台资料，
refresh/check-sources明确采集并写本地快照；不创建研究job或模拟仓。

CLI默认摘要投影，保留财务、来源与精确ID，原文用`section NVDA income`等按需读取。
完整原始数据存于不可变symbol/snapshot文件，摘要不是数据删除。全源刷新失败保留旧可用快照，
失败attempt另存；损坏缓存不能伪装available，更新中断会显示失败。

原始快照在配置的data_dir下`company_research/`保存，**不是把财务填入交易数据库或PIT因子库**。
本轮未新增数据库migration。已有`rpt_date`不能证明历史修订和首次公开可见性，
因此research_ideas=observation_only、pit_backtest_ready=false，OHLCV表达式白名单不变。

## 验证与部署

- Platform九个聚焦后端测试文件合计181 passed；独立QA修复后原反例另行复验通过。
- 前端四个相关文件38 passed，TypeScript检查与改动文件ESLint通过；新增CLI摘要/按节读取28 passed。
- HQA窄安装测试3 passed；未重复两仓全套。
- 独立审查真实关闭四类缺陷：全源失败覆盖旧快照、无效JSON误报能力可用、损坏能力缓存500/覆盖固定策略、
  Longbridge收盘前旧缓存跨收盘后仍被视为完整。
- 主体生产构建28/28页面成功后，正常重载backend/frontend。没有改OpenD、Grok/研究worker或模拟日历。
- Browser原生服务依赖版本缺失、Computer Use native pipe启动失败，未伪称它们已恢复。
  改用本机现有Chrome的独立临时无登录headless上下文完成真实页面点击，未读取已有Chrome用户目录/会话。
  一次公司刷新、一次权限检查；四tab、复制问题、390px局部表格滚动通过，页面无JS/console错误。
- 初次真实截图发现公告publish_at/file_urls、分红desc、公司行动act_desc、预期details与评级嵌套字段
  未完整显示，已窄修；截图区分修复前与最后只读复验，不把单元fixture当线上数据。

具体源码文件、操作用法见[指南](../guides/company-research.md)，接口与字段见[设计](../design/2026-09-12-longbridge-company-research.md)。
其他两仓WIP保留，不打包进入本轮提交；无远端push。

## 未以本轮代替的工作

没有运行新的Grok研判、研究回测、手工paper-cycle、补造正式成交、修改旧仓资金或启动实盘。
没有完成基本面PIT库/基本面因子准入、周期性公司资料刷新、市场全量扫描或完整财报电话会分析。
此前残差相关、持续IC、绩效退出、intake心跳、日志轮转及DSR口径/历史重判不在本次数据源改动中；
其他agent是否随后完成须现场另核，不能从本轮测试推导。新协议自然投递、自然成交与长期效果仍应读真实运行记录。

## 2026-09-13续接发布

续接先核对两仓源码和镜像，期间主体HEAD未漂移，保留其他agent的AGENTS/neat-freak与HQA大批WIP。
窄修Platform `6a956e2b`、HQA `c7e98f7`已本地提交并fetch/ff到镜像。

生产Next构建再次成功28/28，company-research页面16.4 kB，首载JS129 kB；
随后标准安装器仅重载backend/frontend，launchd短时EIO由既有退避处理后退出0。
页面和同源API均HTTP200，NVDA snapshot_id及updated_at没有改变，没有再次抓取资料或检查权限。

最终已安装Hermes工具实际验证：

- `show NVDA`为compact，14个来源元数据、5期财务、8项指标、16项checks；默认仅quote/company保留data。
- `section NVDA income`读取原始利润表，25,966 bytes，原SHA与snapshot_id保留。
- `compare NVDA AAPL`返回NVDA available、AAPL not_loaded；没有为了对比而自动采集苹果。
- 默认show UTF-8输出17,229 bytes，原完整快照压紧JSON为158,414 bytes；原文仍完整保存，按节可取。
- 续接新增代码复验：CLI 28 passed，前端4文件38 passed；此前未变的181项不重复跑。

9/13最新版原生Browser连接恢复成功，最终UI验收改用受支持浏览器接口，不继续使用前日故障时的替代控制。
原生最终检查通过：7张截图已目视复核；同快照身份、SEC日期/原文链接、分红、预期、评级及
中文权限提示均正确，390px四页签无整页横向溢出，console error=0。
正常reload后网络观察3个GET、0个POST，未截断；临时viewport复原、自己新建tab关闭。
收据为`artifacts/longbridge-company-2026-09-12/2026-09-13-native-qa-receipt.json`。

随后主人追加“全量E2E浏览器测试、覆盖所有功能”，作为独立验收批次继续，结果不预先写成通过。
