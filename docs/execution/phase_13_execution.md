# Phase 13 执行指南

## 离线样本运行

```powershell
conda activate ai-quant
quant-system options daily-scan --provider sample --top 5 --date 2026-05-03 --output-dir data\_phase13_sample_scan
```

预期输出：

```text
dry_run=false provider=sample top=5 strategies=sell_put,covered_call output_dir=data\_phase13_sample_scan
run_date=2026-05-03 universe_size=5 scanned_tickers=5 failed_tickers=0 candidates=50 data=data\_phase13_sample_scan\2026-05-03.jsonl meta=data\_phase13_sample_scan\2026-05-03_meta.json
```

## 离线样本日终任务

```powershell
conda activate ai-quant
quant-system options daily-task --provider sample --top 5 --date 2026-05-03 --universe-source sample --earnings-source sample --vix-source sample --output-dir data\_phase13_sample_task
```

预期输出包含：

```text
step=universe status=refreshed
step=earnings status=refreshed
step=vix status=refreshed
step=scan status=completed
task_status=data\_phase13_sample_task\daily_task_status.json
```

该命令会刷新本地输入缓存，然后写入
`data\_phase13_sample_task\2026-05-03.jsonl`、
`data\_phase13_sample_task\2026-05-03_meta.json` 和
`daily_task_status.json`。Windows 计划任务入口
`scripts/run_options_radar.ps1` 使用同一个 `daily-task` 命令。

## 试运行（Dry Run）

```powershell
quant-system options daily-scan --provider sample --top 5 --date 2026-05-03 --output-dir data\_phase13_sample_scan --dry-run
```

预期输出：

```text
dry_run=true provider=sample top=5 strategies=sell_put,covered_call output_dir=data\_phase13_sample_scan
provider_check=skipped
```

## 富途只读检查

```powershell
quant-system options daily-scan --top 5 --dry-run
```

在运行了 OpenD 的机器上，此命令会打印 `provider_check=ok`。
如果 OpenD 不可用，命令会以退出码 `3` 退出并打印
`provider_check=failed`。

## API

```powershell
curl "http://127.0.0.1:8765/api/options/daily-scan/dates"
curl "http://127.0.0.1:8765/api/options/daily-scan?date=2026-05-03&strategy=sell_put&top=20"
```

## 前端

```powershell
conda activate ai-quant
quant-system serve --host 127.0.0.1 --port 8765

cd src/frontend
npm run dev -- --hostname 127.0.0.1 --port 3001
```

打开：

```text
http://127.0.0.1:3001/options-radar
```

## 验证命令

请在嵌套的前端包目录中运行 Playwright，以便它使用与应用相同的本地
`@playwright/test` 依赖：

```powershell
conda activate ai-quant
cd src/frontend
$env:PW_E2E="1"
npx playwright test --config playwright.config.ts
```

预期输出：

```text
14 passed
```

Playwright 配置会通过向上逐级查找，直到找到 `pyproject.toml` 和
`src/frontend/package.json` 来定位仓库根目录，因此 API 与前端
服务器使用的是当前的检出代码，而不是某个过期的工作目录。

## 从 UI 运行并刷新

`/options-radar` 页面可以运行当日扫描并保存一个新的本地
快照。在默认数据源下，这会使用只读的富途期权数据。如果
你对同一日期重新运行扫描，该日期的快照会被新报告替换，
而不是与过期的行数据合并。

该页面还可以刷新本地的标的池、财报与 VIX 缓存。公开
数据源是默认选项；本地样本数据源仅用于显式的离线
测试。同样的刷新操作也可以通过命令行使用：

```powershell
quant-system options daily-task --top 100 --universe-source public --earnings-source public --vix-source public
python scripts/refresh_options_universe.py --bootstrap-github --output data/options_universe/sp500_nasdaq100.csv
python scripts/refresh_earnings_calendar.py --top 100
python scripts/refresh_vix_history.py --output data/options_universe/vix_history.csv --lookback-days 400
```

`daily-task` 是调度入口：它会串联三项刷新和一次 `daily-scan` 等价扫描，
并在输出目录写入 `daily_task_status.json`。三个脚本仍保留为单项缓存刷新工具。

Radar 的 UI/API 在刷新标的池时默认使用公开的 S&P 500 + Nasdaq 100 数据源，
刷新财报时使用 Nasdaq 公开日历，刷新 VIX 时默认使用 Yahoo/Cboe 公开数据。
上面展示的手动财报脚本仍然使用
`yfinance`。VIX 命令从
`query1.finance.yahoo.com` 拉取 `^VIX` / `^VIX3M` 的每日收盘价（只读 HTTPS GET，无需 API 密钥），
并写入一个 CSV 缓存。下一次 `daily-scan` 会打印一行 `market_regime=...`，例如：

```text
market_regime=Normal w_vix=1.0 vix_density=0.227 term_ratio=0.899
```

当 CSV 缺失时，扫描仍会运行，但会记录
`market_regime=Unknown reason=no_vix_history` 并且不施加任何惩罚。
