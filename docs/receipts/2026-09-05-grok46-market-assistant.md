# Grok 4.6、自动市场检查与真实证券目录

> 本地路径说明（公开版）：文中未随本版提供的 `artifacts/`、`evidence/` 和运行目录是本地证据坐标或路径示例，原件未公开；不能把路径存在当作公开证据。详见[公开范围说明](../publication-20261004.md)。

本轮依据用户截图中的固定套话、模型要求和“缺数据宁空、不用模拟数据”的明确要求实施。起点 Platform source/mirror 为 `d455acd6`，HQA 为 `2c827e8`；两仓已有用户修改的 AGENTS.md 与 HQA 产品代码未纳入本轮提交。

## 模型实际生效位置

- 市场研判、周报、月报共用 `RollupLlmClient`，默认 `grok-4.6`，实际请求带 `reasoning_effort=xhigh`。缓存复用同时比较数据指纹、模型、推理强度和分析版本；新模型/新提示不会继续复用旧回复。
- Hermes 主聊天的全局配置原本已是4.6/xhigh；X Search及两处MoA Grok slot此次同步修改，其他模型保持原样。19个原4.5的 `web_*` 会话通过现有 `/api/sessions/{id}/model` 正式接口修改后续模型选择，所有消息数量未变，0聊天请求、0模型生成。未把历史回复重新生成或改成新模型的产物。
- RD-Agent原固定依赖仅接受low/medium/high，LiteLLM又拒绝OpenAI兼容路径的Grok reasoning参数。固定补丁仅扩展词汇，并对 `openai/grok-*` 明确透传；没有丢弃参数、降级为high或更换上游。Docker构建中的密封测试执行真实RD-Agent→LiteLLM→OpenAI SDK，捕获到 `model=grok-4.6, reasoning_effort=xhigh, http_attempts=1`。
- 本机8645代理按字节转发到xAI，没有模型别名映射。最初纯文本真实能力请求返回HTTP200、`returned_model=grok-4.6`、`READY`，耗时2.21秒，reasoning_tokens=87。支持说明见[xAI推理文档](https://docs.x.ai/developers/model-capabilities/text/reasoning)。

配置备份为 `~/.hermes/config.yaml.grok46-xhigh-20260905.bak` 与 `~/.config/hqa/d34.env.grok46-xhigh-20260905.bak`，均0600、未提交。镜像验证成功后，现役D34 env已补 `LITELLM_REASONING_EFFORT=xhigh`。实际研究作业未触发，本片不把密封SDK检查称作真实研究完成。

## 页面与自动执行

旧主标题与三列说明来自固定规则，不是Grok。现在删除重复的三列，把匹配当前数据的AI解读、当前建议与适用条件放到前面；下面单独展示程序已经算出的均线位置、回撤、VIX及期限比等检查。缺数据与尚未生成AI明确区分。

原句“估值偏贵，当前价格压力尚未同幅度升高”改为“美股估值偏高，但目前尚未出现明显的下跌信号”。检查直接报告SPY/QQQ是否在均线上方、回撤是否达到10%、VIX是否达到30以及期限是否倒挂，不要求读者再计算。MarketPulse也改为实际周/月同涨、同跌和反向数量；未为其他页面伪造尚不存在的研究恢复或交易恢复功能。

指标分为本地切换的“行情与波动 / 宏观与估值”，亚洲为“行情与波动 / ETF估值”。亚洲比较表按组显示12个市场，价格日期与发行人估值日期分开。

复用已加载的 `com.aiquant.asia-radar-refresh` 每日17:05（本机北京时间）日程，在原行情刷新后执行 `scripts/refresh_market_assessments.py`。该命令通过现有本地owner会话和CSRF，向与页面相同的API分别提交美股、亚洲更新，后台完成后打印结果；不创建研究job或交易。GET和页面打开只读结果；数据与模型等未变化时复用AI。安装日程不等于自然17:05已经发生，本次另外实跑同一市场更新命令验证两份结果。

## 补充真实数据

- CAPE就是席勒市盈率，已有指标此次写全名称，没有重复计权。新增巴菲特指标后，总权重仍100%，估值组仍45%；CAPE/P/E/P/B/巴菲特分别15/10/5/15。
- 巴菲特指标采用联储 `BOGZ1LM883164115Q` 同季度美国上市股权市值与BEA/FRED名义GDP，分子百万美元、分母十亿美元，按1000换算。真实2026Q1为250.0299%，此前80个季度经验分位97.5。季度末2026-03-31，联储Z.1发布2026-06-11；GDP采用当前修订值，不把它称为两项共同首次发布日或今日实时Wilshire比率。三份来源在页面均可打开。
- VIX缺口的原因是非空但过期的Yahoo VIX3M挡住Cboe获取。正式reader已统一Cboe两个官方CSV。实际2026-09-04 VIX=14.53、VIX3M=17.61、比值0.8250993754；本轮还通过现有public刷新函数更新正式VIX缓存284行，并保留原CSV备份，未重扫期权推荐或修改IV history。
- ASHR已核对DWS美国基金ISIN `US2330518794`，正式API含09-03组合数据但没有可核验P/E、P/B，下载目录为空。同名欧洲UCITS不混用，两个字段仍为空，页面标明此次核查日期与DWS来源。

当前修订后的季度历史可用于描述相对估值位置，不能冒充完整点时历史。缺少完整按当时发布日期保存的输入与样本外验证，因此没有把评分校准成崩盘概率，也没有生成虚假的策略收益证明。

## FinanceDatabase接入范围

[FinanceDatabase](https://github.com/JerBouma/FinanceDatabase)是证券分类目录，不提供实时行情、财报或P/E、P/B。本片使用固定commit `5865ce3b26e6f393dc0600cad1ae02339bd7d52d` 的公开美股股票及ETF CSV，保留MIT版权说明，不安装依赖FinanceToolkit的完整包。

导入12个交易所/资产类型CSV，过滤已标退市和 `^...` 指示净值代码后保留11,629条记录。首轮导入因ASE ETF文件全部为指示值代码而中止，核对真实文件后允许该来源过滤后为空，仍拒绝整体空目录。

已接入顶栏公司名/代码搜索、个股行情输入、`GET /api/securities/search` 和 `quant-system data security-search`。实测Microsoft→MSFT、DELL精确优先、ASHR保留美国基金ISIN。目录不等于行情授权、历史成分股或有效投资分类；例如上游SPY分类存在可疑值，本片未用于评分、自动选股或交易。未自动扩大34只期权标的或已启用策略的范围。

## 删除真实行情失败后的样本替代

移除`/market-data/history`、`/ohlcv`、`/benchmark`的隐式sample补缺，工厂在默认真实源缺配置时明确失败。`/ohlcv`不再无条件读来源不明local缓存，复用现有严格缓存；缺provider/interval或来源不匹配的缓存不能命中。`/symbols`同样仅使用当前来源日线。显式sample仅保留隔离测试用途，正式行情输入不再提供sample选项。

正式HTTP反例为默认来源请求未知代码，返回502 `provider_query_failed`，原文“未知股票 __NO_SUCH_SECURITY__”，没有rows或sample行情。原始JSON见 `artifacts/market-assistant-2026-09-05/provider-error.json`。

## 验证与部署记录

- 前端整批 `125 files / 727 tests passed`，TypeScript与相关ESLint通过。
- 相关后端集合 `105 passed, 1 warning in 4.22s`；包含真实源失败、已完成检查、目录检索、模型客户端与数据源。最后缓存/提示修改16项通过。既有Starlette弃用警告不影响结果。
- 代码 `69634c0a`、补丁上下文修复 `e72715b1`、最终市场提示 `7f8bc635` 均经Ponytail通过并本地提交，没有push。首次镜像构建因补丁无后文上下文而失败，密封重现并修正后构建成功；旧镜像保留在 `hqa-d34-rdagent-qlib:before-grok46-20260905`。
- 第一轮正式市场更新两份均成功，为4.6/xhigh；美股9/9、亚洲58/60。进一步精简市场建议的下一轮两份返回通用 `RollupLlmUnavailable`，原生产结果没有保存具体子异常，无法反推当时原因。随后一次只读真实诊断请求返回HTTP200、上游 `grok-4.6`、有效JSON，耗时96.05秒，reasoning_tokens=5999；没有把这次成功当作前次失败的原因证明。元数据见 `artifacts/market-assistant-2026-09-05/model-diagnostic.json`。
- `a846e3de` 把已有模型等待预算从120秒放宽到300秒，并分别显示安全的超时/HTTP/JSON错误；同数据刷新失败保留上次有效AI并显式标旧结果，成功清除旧错误。32项相关测试通过；没有加入自动POST重试。该修改针对xhigh的已观察延迟留出余量，不声称已经证实前两次一定是超时。
- 最后正式stack启动exit0，API、前端、Hermes、代理、connector启动检查通过。D34镜像为 `sha256:63952cea43b053e4b15f32aa56afefab442dcc89dbcaa626e32baacfd87ac69b`；读取实际D34 env的无网络容器检查返回 `model=openai/grok-4.6,reasoning_effort=xhigh,provider_calls=0`。
- **最终AI验收未通过**：放宽等待后的最后一轮美股、亚洲均返回“模型服务返回HTTP 502”，任务exit1，两份结果 `ai_analysis=null`。原始结果见 `artifacts/market-assistant-2026-09-05/verified-refresh.json`、`us-final.json`、`asia-final.json`。不把早先成功回复或单次诊断成功当作当前页面成功；没有继续盲重试。到底由代理还是上游生成这次502，未取得响应体证据，保持未确认。
- 最终数据仍为美股9/9、100%权重覆盖，亚洲58/60、97.08%，缺ASHR PE/PB。正式浏览器验证了公司名Microsoft→MSFT、390px移动目录无水平溢出，以及两个指标分组的切换与来源链接。模型失败如实可见。
- 本轮模型请求共8次，包括一次能力probe、首轮市场2次成功、后续2次通用失败、一次成功诊断、最后2次502。没有新研究、模型交易、手工paper-cycle或模拟成交。
- 检查日程时一次 `plutil -extract ... json` 导出命令意外覆盖了plist，已立即通过原安装器从项目模板恢复，`plutil -lint`返回OK，逐项读取时间仍17/5。RunAtLoad仍false，未触发日程执行。日程只证明已安装；自然17:05触发在本次验收时尚未发生。
