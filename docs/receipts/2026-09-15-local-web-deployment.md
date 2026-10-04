# 本地网站发布与实际页面验收

> 本地路径说明（公开版）：文中未随本版提供的 `artifacts/`、`evidence/` 和运行目录是本地证据坐标或路径示例，原件未公开；不能把路径存在当作公开证据。详见[公开范围说明](../publication-20261004.md)。

2026-09-15，Asia/Shanghai。主人明确选择“更新本地网站并验收”。

**部署已完成，实际页面已检查；已知导航请求取消在实站再次出现，因此不声明整站稳定性全绿。**

## 部署范围与身份

| 项目 | 发布前镜像 | 发布的产品版本 |
|---|---|---|
| Platform | `c92eee8a` | `a4fc35bf` |
| HQA | `139a5a8` | `1ed2d48` |

两座部署镜像均从各自本地主仓 `source` remote fetch 后精确 fast-forward，没有推送远端。
包括此前待发布的 `e7fb6820` Futu 超时有限重试/研究摘要，以及 `e5ef624` 的 intake `sync-report` 和 Longbridge 公司研究工具说明。
主仓其它 Agent 的未提交代码、AGENTS 和 Skill 编辑未打包。

本批没有新增数据库迁移或依赖变更。镜像中的 `earnings_calendar.csv` 与 `sp500_nasdaq100.csv`
运行数据虽有未提交变化，但与代码更新不重叠；快进前后 SHA-256 分别保持
`d1c255b29f7b2c38b8bf722448d33713e014224e84a429086dd181b2b3ccd582`、
`7654ccbbeb766dd577cf3110f44b84dba6745d54bf0810fe6ca953e0051dae3c`。

执行顺序：

1. 记录原健康、安全与账户经济字段，核对运行目录和待部署差异。
2. 两镜像快进；从 Platform 镜像执行 `local_mac_stack.sh build`，成功后再切换服务。
3. 从 HQA 镜像更新既有 wrappers/Skills；对 intake 使用 `install_research_intake.py --platform <Platform镜像>`，不带 `--install-worker`。
4. 使用 `install_agent_v02_stack_launchagents.sh` 只替换 backend/frontend。启动过程出现受控的 launchd EIO 重试，最终两服务启动成功。

Frontend BUILD_ID 为 `jg_68xeiykUy6xUJohe7J`；验收时 backend PID `46783`、frontend PID `46896`。
后台继续使用已配置的 Python 3.12 运行环境，没有借此次部署更换解释器；此前隔离全套测试环境另列在原测试收据。
Connector 的 local-trust 身份不含 Git HEAD，且本批未修改其工作循环，故保留原进程。
Hermes 本体、OAuth 代理、Futu OpenD、数据库和各定时任务没有额外重启或改排程。

## 运行检查

- `/api/health` 为 `ok`，`paper_trading=true`、`live_trading_enabled=false`、`kill_switch=true`。
- `/api/safety/effective` 为 true，canonical account 数为1；没有执行迁移或正式修账。
- `/api/hermes/gateway` 的连接、会话读取及 `chat_write_ready` 均为 true。
- 新 API 类型已出现在部署后的 OpenAPI：DataSourcesResponse、DailyBackupResponse、StrategyLibraryResponse。
- 安装态 intake Skill 为1.2.0；实际执行只读 `sync-report` 返回17个作业，16个质量拒绝、1个完成。
  `cloud_acknowledged=false`，本次未声称云端 Grok Bot 已读取新说明。
- 部署前与页面验收后，API提供的现金、可用现金、已实现盈亏及持仓数量/成本字段一致。
  这是所选经济字段的核对，不冒充全库行级审计。

## 实际页面验收

使用用户 Chrome 的真实 `http://127.0.0.1:3001`，没有 `page.route`、测试后端或模拟报价。
只操作导航、筛选、展开/收起和读取已保存记录；没有发送聊天消息、启动研究、重新验证策略、启用模拟仓、下单、全量期权扫描或 Grok 研判。

| 页面/功能 | 实际结果 |
|---|---|
| Hermes 首页 | 本机连接与输入就绪；真实记录为7个已验证候选、2个模拟运行策略，手机宽度390时页面宽度390、今日卡片table min-width为0。 |
| 手机菜单与对话抽屉 | 打开/关闭及恢复桌面宽度正常，没有发送消息或创建对话。 |
| 统一结果 | 8条已有记录可见；输入“自动化”后命中1条；历史样例回测明确标记“样例数据·非真实表现”。 |
| 公司研究 | NVDA 已保存快照14/14章节；财务页5个季度、8个观察指标、16项核对正常显示；Futu报价与Longbridge公司/财务来源分别标注。 |
| 长桥能力显示 | 报价、最近日线、财报、到期日和行权价可用；指定日期历史仍quota_exceeded，期权报价仍permission_denied。没有追加权限检查或填造数据。 |
| 策略与因子 | 9项研究、4个模板、7个因子；示例业绩被排除。跨行业24股月度动量的806.38%属于对应原记录，平台Sharpe1.0014/回撤31.72%；Qlib未留存的指标继续空白。 |
| 策略深链接 | 跳转保留精确 strategy 参数和片段，定位到同名规则；没有点验证或启用。 |
| 模拟账户/日报 | 当前行情可用，账面展示与持仓读取正常；日报区分策略观察和整个账户。缺行情分支沿用此前隔离验证，本次不人为制造缺行情。 |
| 市场研判 | 美股/亚洲、宏观历史对照与行情展开收起正常；亚洲已有Grok4.6/xhigh解读可见，未知估值项仍留空；未刷新模型。 |
| 期权推荐 | 已保存9/14扫描记录能读取，但页面判定快照需要更新，当前候选不展示。未启动新扫描，不能称获得了新鲜可交易推荐。 |
| AI新闻/设置 | 页面与现有资讯/安全设置正常显示；没有修改设置。 |

观察到的残留展示问题：Hermes首页部分新策略仍使用“横截面选股研究因子”通用名称，
策略目录中有更明确的独立名称；这是展示一致性不足，不代表策略ID或资金被合并。本次未追加产品改动。

## 已知导航问题在实站复现

两次从全新加载的Hermes首页点击“查看全部”：

- 第一次目标RSC请求 HTTP 200 → `Network.loadingFinished`，收到16234字节；结果页显示8条记录。
- 第二次目标请求 `76181.485` 在HTTP 200之后触发 `Network.loadingFailed`，`canceled=true`、`net::ERR_ABORTED`；结果页仍显示正常内容。

没有使用浏览器请求替换、fetch包装或测试数据。该结果证明问题不只存在于先前隔离矩阵；
没有证明具体取消原因，也不能用第一次成功撤销第二次失败。页面捕获的console error为空，不等于网络全部成功。
本次只复核部署后的已知问题，未增加重试、忽略异常或更改导航实现。

## 证据与结束状态

`artifacts/local-web-deploy-2026-09-15/`保留构建、安装、重启日志，前后账户/健康快照、
只读sync-report、两次脱敏请求事件和9张实际页面截图。没有保存请求头、cookie或凭据。
浏览器尺寸已恢复，网络观察已关闭，策略页面留给用户查看。

发布动作完成；源码原测试结论与本次实站结论分别保留。没有推远端，没有手工模拟周期、正式交易、历史补账或云端团队消息。
