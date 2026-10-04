# 个人量化助手：实际使用评估与修复

> 本地路径说明（公开版）：文中未随本版提供的 `artifacts/`、`evidence/` 和运行目录是本地证据坐标或路径示例，原件未公开；不能把路径存在当作公开证据。详见[公开范围说明](../publication-20261004.md)。

检查日期：2026-09-05。按主人本次要求检查并修复本地项目，以当前代码、API、页面和运行日志为依据。修改前 Platform source 为 `6e1c087`、部署镜像为 `7269395`；HQA source 为 `c3d8101`、部署镜像为 `5dfa806`。HQA 原有大量未提交工作保留。

## 结论

已有真实的 Hermes 接入、研究队列、Qlib 回测、Platform 独立回放、模拟账户和日历执行；但它们组合起来还不能等同于“发任意论文，自动忠实复现并每天稳定交易”。用户的不适来自真实的运行故障、算法接线错误与产品信息架构问题，不能归为使用方式不对。

| 能力 | 现场事实 | 本次处理 |
|---|---|---|
| 本机 Hermes 对话 | 网页和 Hermes 在线，PostgreSQL 停机约25小时，connector/worker失败，chat_write_ready=false | 恢复原容器后数据库与连接就绪；网页真实发消息并收到回复 |
| 新论文/策略研究 | 材料约束存在；原formula仅进入objective文本，RD-Agent仍可更换公式选最优试验 | 日线OHLCV可表达公式独立传递、校验、固定复现一次；不支持的规则明确拒绝 |
| 双引擎一致性 | Qlib Rank是时序百分位，生成因子却横截面排名；EMA在Rolling上调用ewm报错 | 对齐实际Qlib实现；修复复合公式历史窗口累计 |
| 自动模拟启用 | 原同聊研究成功一律停在verified，需去另一个页面点击 | 新作业复用既有digest绑定服务，合格后分配$10,000；确定失败保留候选、部分写入走既有对账恢复 |
| 每日模拟 | 正式绩效只有8月19日、8月25日、9月1日三个记账日；存在行情失败和DB断开 | 修复空计划仍估值写账引发的无关MU报价崩溃；未补造历史观察 |
| 期权推荐 | 9月4日20条中AAPL12、SPY3、QQQ3、UNH2；23/34成功 | 每标的最多2条再全局排名；不宣称等同于分散组合优化 |
| DELL筛选 | 真实链可获取，默认533行全部未通过；财报缓存过期 | 单标的刷新后缺财报533→0；仍因HV/IV、OI、价差、Delta等返回0合格候选 |
| 备兑看涨 | 筛选API未传股息事件；明确不分红记录会None.isoformat崩溃；过去除息错误放行 | 接线和空日期修复，拒绝把历史除息当下一次事件依据 |
| 盯盘 | 切任意子页仍加载三套内容；横截面/亚洲页主要展示YTD | 只加载当前页；周/月强弱、涨跌家数、量价和研究深链 |
| 界面 | 对话挤在窄栏，旧产物/技术表格占主要区域，重复状态多 | 对话主区、运行上下文侧区、诊断折叠；统一中性深色、琥珀强调、可读字号和表格 |

## 关键证据

### 连接和运行

`docker ps -a` 初始显示 `quantplatform-db Exited (0) 25 hours ago`；`docker start quantplatform-db` 返回 `quantplatform-db`。
恢复后的 GET `/api/health` 中 `database.reachable=true`；GET `/api/hermes/gateway` 中 `connected=true, chat_write_ready=true`。

浏览器在 `http://127.0.0.1:3001/zh/hermes` 发送连接测试，明确不执行研究/回测/交易；Hermes 返回连接测试回复（公开版不引用正文），页面终态“已成功”。公开版省略具体会话身份与正文；本地原件保留，可在本机最近会话中复核。这个测试证明聊天接入，不证明一篇论文已经复现。

正确加载部署wrapper环境后，`observe_paper_emergency_stop` 返回 `active=false`，原因是原有 `D-34 cold-restart acceptance complete`，记录日期2026-08-11。9月4日停止符合数据库不可用时的保护行为，不是发现了一次新的人工停止。

运行日志：`data/_runtime/agent-v02-work/ai-quant-platform/data/_runtime/logs/d34-paper-cycle.launchd.out.log`（相对HQA根）。9月2日数据不可用；9月3日上午计划受阻、晚间无待执行计划但无条件取全账户价格而因MU崩溃；9月4日数据库不可用时停止。当前账户6个持仓报价只读读取均为Futu成功，不能据此倒填过去。

### 期权与模型

默认DELL条件下533行中，HV/IV过滤失败340、OI不足350、价差超限327，原因重叠。原来全部还有缺财报；实际公开数据返回下一财报 `2026-11-28` 后，该原因降为0。这里的零推荐不是无行情，页面已取消“直接关闭过滤器”的通用建议，改为解释实际拒绝原因。

旧9月4日推荐包含5条AAPL备兑看涨，使用已经过去的8月10日除息日期。新代码重验旧快照得到 `unavailable / invalid_recommendation_snapshot`。需要正常更新生成当前规则的新结果，不能把旧数据改个日期继续当证据。

旧11个Futu失败已逐项对应OpenD的 `{"retType":-1,"retMsg":"网络中断","errCode":0}`。原始日志 `~/.com.futunn.FutuOpenD/Log/GTWLog_<local-id>_2026_09_04_03_43_38.log` 的3438/3513/3553/3574/3645/3670/3689/3708/3761行分别对应NVDA/GOOGL/AMZN/META/TSLA/SOXX/SMH/IGV/XLY；`GTWLog_<local-id>_2026_09_05_00_20_17.log` 的238/257行对应XLP/XLF。该轮22:52:56开始、00:50:45结束。没有证据把这些失败归为无期权数据或缺权限。

EV仍基于物理对数正态模型、波动率`min(IV,HV)`及默认4%股权风险溢价；POP仍是`1-|delta|`近似。它们不是已经回测校准的概率或可保证收益。推荐去重仅解决同标的占屏，不完成相关性/行业/尾部风险的组合优化。

### 研究与模拟

代码链为 `intake_research_operation → job.input_document.formula → D34ResearchRequest.formula → Qlib一次固定公式试验 → Platform目标权重回放 → 候选准入 → hang_candidate → 日历信号/成交`。

固定公式不再调用自由假设提案模型，不重复跑9次相同实验虚增试验数。研究和回放仍绑定同一市场快照、日历、权重与成本证据。`Rank(expr,1)`在Qlib中恒等于1，原示例已修正。EMA、Ref、Mean、Std、Rank、嵌套表达式和负Ref语义经实际Qlib差分检查。

自动启用复用现有DSR 0.95、相关性0.7、成本敏感性和资金检查，未降低标准。独立审查发现并修复“资金已分配但激活写入失败，终态导致永不恢复”的问题：下一次projector沿原候选恢复，测试断言只有一个策略仓和一笔分配。

## 使用方式与能力限制

1. 在Hermes中发论文链接或描述规则。Hermes先读材料并抽取可执行公式、研究说明、明确股票池；缺失时同聊追问。
2. 当前自动复现覆盖日线OHLCV及支持的Qlib运算符，组合为最高分一只（top_k=1）、约三年历史、次交易时段开盘执行。复杂仓位规则、盘中、期权组合、需要另类数据的策略，不能声称已复现。
3. 合格新作业自动分配$10,000模拟资金。原有旧候选仍由候选库查看与手动处理；页面读取不会启用它们。
4. 日历运行后在模拟账户看实际成交与绩效；已启用、产生信号、实际成交是不同事实。机器离线不会补齐过去的交易。
5. 盯盘的亚洲页是美元计价、美股上市ETF的区域比较。12个ETF当前可用；本地指数只有日本/香港、龙头篮子只有香港可用，其余仍有通道/权限错误，不能叫覆盖完整的亚洲实时雷达。

## 验证与交付记录

- 前端相关验证：`Test Files 12 passed (12); Tests 87 passed (87)`，类型检查和ESLint exit0。
- 期权相关：`220 passed, 1 warning in 6.24s`；警告为既有Starlette TestClient弃用提示；Ruff通过。
- 模拟operations+price_source：24项通过，包括空计划不取价、正常成交落账、保存失败journal保留与恢复。
- 自动启用独立复核：`6 passed, 78 deselected in 1.24s`。
- 双引擎与研究链：`151 passed, 9 skipped, 1 warning in 8.39s`。其中9项PostgreSQL资金/恢复测试随后在一次性库补跑，`9 passed, 75 deselected in 5.75s`；本次测试库及sibling全部清理（复查剩余0），未迁移或改写正式库。
- HQA精确提交 `93a048b` 在具名detached worktree测试：聊天 `48 passed`，研究skill/安装/包装器 `4 passed`；没有消费主工作区既有WIP。提交前Ponytail hook输出 `PONYTAIL_REVIEW_PASS`。
- D34容器已从更新源码重建；只读无网络容器内输出 `formula_field=True lookback=80`（`Mean(Ref($close,20),60)`），证明新公式接线进入实际镜像。此前镜像标签保留为 `hqa-d34-rdagent-qlib:pre-usability-20260905`。
- 浏览器已验证原站点真实聊天、新版桌面与390×844手机聊天、Escape返回、横截面周期切换与META深链；量价摘要显示与横截面一致的近5/21交易日变化。
- 改造截图位于 `artifacts/usability-2026-09-05/`：`hermes-before.png`、`hermes-after.png`、`hermes-mobile.png`。

前端全套在基础改造后为 `119 files / 710 tests passed`；未将相关Python测试等同于两仓后端全套通过。未创建新的正式论文研究/策略仓/成交，未手工paper-cycle，未推远端。后续新论文实际复现、自动启用和持续自然交易仍需各自真实产物验证。部署与最终扫描结果另在本节记录。

## 新增的市场风险观察

按主人本次追加要求审阅 `middletoo/US_Stock_Crash_Monitor`，没有clone或运行该App。其原始启发式总分存在随机数据回退、缺数据判低风险、下跌越深分数越低、权重超出量表等问题，详见 [固定源码评估与数值反例](2026-09-05-crash-monitor-assessment.md)。

本项目借鉴分项解释，使用现有Futu与VIX缓存提供市场压力观察，显示长期均线位置、252交易日高点回撤、VIX水平/变化和同日配对的期限结构。缺数据/过期/窗口不足明确不可用；不输出崩盘概率，不把固定篮子涨跌家数冒充全市场宽度。阈值是透明的观察条件，尚未经过预测概率或策略收益校准。

## 本地部署与正式浏览器

- Platform主改造 `3a8ae38`，标题颜色修复 `952e3b9`，会话切换瞬态状态隔离 `80767a7a`；HQA研究契约 `93a048b`、定时脚本路径修复 `6d6aaac`。均为本地提交，提交前Ponytail hook通过；镜像仅fetch/fast-forward。
- 正式镜像 `bash scripts/local_mac_stack.sh start` 成功：`hermes_ready=true`、`backend_ready=true`、`connector_ready=true`、`frontend_ready=true`。启动中的launchctl EIO沿原有有界安装逻辑恢复，最终exit0。
- HQA安装器实际从镜像运行时暴露重复拼接路径的问题，模板已改用已有 `HQA_AIQP_DIR`。重新安装后期权定时脚本和研究启动器均指向真实Platform镜像，HQA指向真实HQA镜像；没有修改原有WIP的安装器代码。安装路径相关 `3 passed`。
- 正式浏览器刷新原会话后继续发送连接测试，收到连接恢复确认（公开版省略回复正文）；最近会话选择仍在 `/hermes?hermes_session_id=...`，原生导航清除上一会话的瞬态回复/草稿状态。
- 正式页面实测发现Tailwind遗留 `--color-base` 覆盖 `text-base` 字号类，标题颜色等于背景 `rgb(17,19,21)`；删除无调用方的别名后，风险和强弱标题实测均为 `rgb(238,237,232)`。该修复只删除冗余别名。
- 最终整合测试为前端 `120 files / 712 tests passed`，受影响后端 `437 passed, 9 skipped, 1 warning in 17.85s`；这9项已在单独PG验证中全部通过。生产构建、类型检查和ESLint通过；后续标题/会话窄修各13项相关测试通过。
- 当前研究镜像为 `sha256:e371e6e52d51e6d8d86bf080650392dcb71a916def37a2bfe74f6b731a6e369a`；主代码已进入镜像，旧镜像保留可回退。

正式期权刷新由浏览器唯一一次启动，2026-09-05 05:21:20至05:42:30 +08，终态 `completed_with_warnings`：34个处理、31个成功，TSLA/XLE/UNH三项 `ValueError`，因此只报部分完成。正式API返回 `available`、20条候选、10个标的，各2条：AAPL/AMD/AMZN/GOOGL/META/MSFT/MU/NVDA/QQQ/SPY，缺口0。原始摘要见 `artifacts/usability-2026-09-05/options-live.json` 与 `options-task-live.json`；未重复启动全池扫描。

三个失败的限定诊断：TSLA/XLE当时在首个快照的 `resolve_trusted_underlying_quote` 校验阶段退出，还未请求期权链；程序未保存具体异常消息或该次快照正文。各一次当前快照检查通过（TSLA 354.08，2026-09-04 17:48:37.555；XLE 64.06，17:48:06.657），因此不能反推当时究竟哪个子条件失败。UNH同次只读缓存复算的ATM IV为0.28158，历史已存0.264965，二者 `quote_as_of=2026-09-04T15:41:51Z`；这满足 `iv_history_observation_conflict` 条件，与当时链路阶段一致，但不是当时异常原文。上述三项未被额外重扫或覆盖旧值隐藏，具体原始子码仍属证据缺口。

正式浏览器DELL默认条件实测：6个到期日、533个被过滤、0候选；Delta评分区间473、OI不足350、HV/IV339、价差327（重叠）。行情与HV/IV原值可见，未再出现缺财报原因。见 `dell-visible.txt` 与 `dell-live.png`；不能把0候选说成行情读取失败。

正式风险面板及手机截图见 `risk-live.png`、`risk-mobile.png`；手机实测 `window.innerWidth=390, document.documentElement.scrollWidth=390`，表格在内部横向滚动。会话切换实测URL从旧回归会话切到本次连接会话，未发送草稿清空为 `''`，不会带入别的会话。最终候选池仍为 verified=1/hung=1/fossil=4/request=1，未新增正式研究或资金分配。
