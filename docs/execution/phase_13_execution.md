# Phase 13 执行指南

现役期权推荐用户流程见[期权推荐指南](../guides/options-recommendations.md)。本页记录
Platform CLI、API 和隔离验证；macOS 自动调度由 HQA runbook 负责。

## 正式 34 标的任务合同

正常用户只用页面“立即更新”，自动流程只由 HQA wrapper 启动。下面展示的是
Platform `daily-task` 的合同形状，**不是让开发者从 source checkout 另跑一份正式任务**：

```bash
./ai-quant/bin/quant-system options daily-task \
  --provider futu \
  --top 34 \
  --universe-source existing \
  --earnings-source public \
  --dividend-source public \
  --vix-source public
```

正式输出只接受：真实 Futu、tracked `curated_wheel.csv` 的 exact 34 标的、正式输出
目录及其 `iv_history`。命令依次加载策展名单，刷新财报、除息事件和 VIX，再扫描并写入
v3 generation、当天 meta 指针和 `daily_task_status.json`。单标的失败会形成 partial
终态，不再清空其他标的结果。

不要把 `--top 100`、`--universe-source public` 或任意 34 ticker 文件写进正式目录。
周六 top-100 宽池由 HQA wrapper 写入独立 `data/options_scans/wide`。
source checkout 与 deployment mirror 的相对 `data/` 是两套目录；从 source 运行上面的
命令不会刷新 live 页面。不要在页面/cron 可能运行时手工竞争正式输出锁。

## 从页面立即更新

打开：

```text
http://127.0.0.1:3001/options-radar
```

点击「立即更新今日推荐」会调用：

```bash
curl -i -X POST http://127.0.0.1:8765/api/options/daily-scan/run
```

成功获得锁时返回 `202` 和 `queued` 状态；它不表示扫描已经完成。页面随后轮询：

```bash
curl -fsS http://127.0.0.1:8765/api/options/daily-scan/status
```

如果定时任务或另一次手动任务正在运行，返回
`409 options_scan_already_running`，不会启动第二份扫描。页面可以关闭，后端任务仍继续。

结果读取：

```bash
curl -fsS http://127.0.0.1:8765/api/options/daily-scan/dates
curl -fsS 'http://127.0.0.1:8765/api/options/daily-scan?date=2026-08-25&strategy=all&top=20'
curl -fsS 'http://127.0.0.1:8765/api/options/daily-scan/symbol/SPY?date=2026-08-25&top=20'
```

raw meta 的 `status=empty` 只表示候选行数为 0。只有 task/coverage 完整且 API freshness
合格时，页面才把它解释为有效零推荐；`status=unavailable` 表示快照当前不可用。

## 隔离的真实诊断

CLI `daily-scan` 不得写正式输出目录。它只对已有输入做窄扫描，不刷新财报、除息和 VIX，
因此不能复现完整 daily-task 或 2026-08-26 的 34/34 收据。需要这种有界窄诊断时：

```bash
options_verify_dir="$(mktemp -d /private/tmp/options-verify.XXXXXX)"
./ai-quant/bin/quant-system options daily-scan \
  --provider futu \
  --top 34 \
  --output-dir "$options_verify_dir"
```

这是开发诊断，不会更新正式页，也不会形成完整输入刷新证据。2026-08-26 的 34/34、
0 失败、Top 20 是隔离 **daily-task** 的 dated proof；精确运行身份与 hashes 见
[HQA 收据](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/receipts/2026-08-26-options-recommendations.md)。
不要为文档验收重跑它，也不能复制隔离 JSONL 到正式目录。

`daily-scan --dry-run` 只检查计划和 Futu 连接，不写快照：

```bash
./ai-quant/bin/quant-system options daily-scan --provider futu --top 34 --dry-run
```

## 全隔离 sample 测试

sample 的输入、输出和 IV history 必须全部指向独立目录；它只验证任务编排，不会生成
可展示为正式 Futu 推荐的结果：

```bash
./ai-quant/bin/quant-system options daily-task \
  --provider sample \
  --top 2 \
  --date 2026-05-03 \
  --universe-source sample \
  --earnings-source sample \
  --dividend-source sample \
  --vix-source sample \
  --universe-path /private/tmp/options-sample/universe.csv \
  --earnings-path /private/tmp/options-sample/earnings.csv \
  --dividends-path /private/tmp/options-sample/dividends.csv \
  --vix-path /private/tmp/options-sample/vix.csv \
  --output-dir /private/tmp/options-sample/scans \
  --iv-history-dir /private/tmp/options-sample/iv-history
```

sample 路径不得复用正式的 universe、earnings、dividend、VIX、snapshot 或 IV history。

## 快照检查

先进入 live deployment mirror，再做只读检查；不要在 source checkout 误读另一套
ignored `data/`：

```bash
cd $HOME/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform
jq '{contract_version,snapshot_generation,data_file,data_sha256,data_line_count,
     status,provider,run_date,as_of,universe_size,expected_universe_size,
     scanned_tickers,failed_tickers,candidate_count,risk_free_rate,
     equity_risk_premium,shortfall_reasons}' \
  data/options_scans/2026-08-25_meta.json
```

同一 session 重跑时还要比较覆盖率。当前 store 阻止 `as_of` 回退，但不会阻止较晚
generation 从 34/34 回退为 partial；只看日期或 `status=empty` 不足以证明完整覆盖。

## 相关验证

按改动范围选择聚焦测试：

```bash
./.venv/bin/python -m pytest -q \
  tests/test_options_daily_task.py \
  tests/test_options_daily_scan_cli.py \
  tests/test_options_radar.py \
  tests/test_options_radar_storage_op1.py \
  tests/test_api_options_radar.py

npm --prefix src/frontend run test -- components/forms/OptionsRadarView.test.tsx
npm --prefix src/frontend run type-check
```

需要浏览器验收时，在隔离端口启用项目 Playwright 配置；不要为了文档检查触发正式扫描。
