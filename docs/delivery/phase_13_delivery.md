# Phase 13 交付文档 — 期权雷达

## 已交付

- 静态 `S&P 500 ∪ Nasdaq 100` 股票池 CSV。
- 通过脚本和 `/options-radar` 页面刷新股票池、财报及 VIX 数据。
- 只读富途限频器。
- IV 历史与 IV Rank 计算。
- 离线财报日历。
- VIX 市场状态分类器（V5 双因子），通过 Yahoo Chart REST 端到端贯通。
- Yahoo `^VIX` / `^VIX3M` 抓取器 + CSV 缓存 + 刷新脚本。
- 跨标的期权雷达扫描器，含按策略的市场状态惩罚。
- 单标的 `/api/options/screener` 路由 + `/options-screener` 页面现已共用同一条
  VIX 市场状态路径：响应体中暴露 `market_regime` + `market_regime_penalty`，
  并对卖方评级进行降级处理（Elevated 状态下 Strong→Watch；Panic 状态下
  sell_put 强制降为 Avoid）。页面在指标网格上方显示市场状态横幅。
- 幂等的每日 JSONL 快照存储（将 `market_regime` + `market_regime_penalty`
  写入每个候选；同日重新运行会替换已存储的快照，而不是合并过期行）。
- CLI 命令：
  - `quant-system options daily-scan`
  - `quant-system options refresh-universe`
  - `quant-system options refresh-earnings`
  - `quant-system options refresh-vix`
- API：
  - `GET /api/options/daily-scan/dates`
  - `GET /api/options/daily-scan`
- 前端页面：
  - `/options-radar`
  - 日期 / 策略 / 板块 / DTE / Top N 筛选
  - 当日扫描及公开/样本本地缓存刷新控件
  - 安全横幅
  - 详情展开
  - CSV 导出
  - 单标的下钻链接至 `/options-radar/[symbol]`

## 验证快照

```text
pytest: 共收集 274 条测试，全部通过
ruff: 全部检查通过
前端 lint: 通过
前端 build: 通过
playwright: 14 条通过
```

使用真实 VIX 历史的示例运行（Yahoo 刷新于 2026-05-03）：

```text
dry_run=false provider=sample top=5 strategies=sell_put,covered_call output_dir=data\options_scans
market_regime=Normal w_vix=1.0 vix_density=0.227 term_ratio=0.899
run_date=2026-05-03 universe_size=5 scanned_tickers=5 failed_tickers=0 candidates=50 data=data\options_scans\2026-05-03.jsonl meta=data\options_scans\2026-05-03_meta.json
```

Dry-run 示例：

```text
dry_run=true provider=sample top=5 strategies=sell_put,covered_call output_dir=data\options_scans
provider_check=skipped
```

Yahoo VIX 刷新（只读，无需 API key）：

```text
python scripts/refresh_vix_history.py --output data/options_universe/vix_history.csv --lookback-days 400
source=yahoo_chart fetched_at=2026-05-03T10:12:27+00:00 vix_rows=274 vix3m_rows=274 end=2026-05-03 output=data\options_universe\vix_history.csv
```

## 最终命令执行记录

```text
python -m pytest -q
........................................................................ [ 28%]
........................................................................ [ 56%]
........................................................................ [ 84%]
........................................                                 [100%]
```

```text
ruff check src/quant_system tests
All checks passed!
```

```text
npm --prefix src/frontend run lint
eslint app components lib tests playwright.config.ts eslint.config.mjs next.config.ts
```

```text
npm --prefix src/frontend run build
编译成功
/options-radar 已包含在构建路由列表中
```

```text
cd src/frontend
$env:PW_E2E="1"
npx playwright test --config playwright.config.ts --workers=1
14 条通过
```

## 安全检查

- 未新增任何下单端点。
- 未新增任何富途交易上下文。
- 未新增账户解锁功能。
- 未新增签名、托管访问或私钥路径。
- 雷达 API 仅读取本地快照文件。
- `/api/orders/submit` 仍然返回 `404`。
- `/api/options/daily-scan/dates` 包含 `safety` 尾部。
- 在 `src/quant_system`、`src/frontend` 和 `tests` 下对交易上下文 /
  签名 / 托管敏感关键词进行代码搜索，无匹配项。

## 已知限制

- 股票池和财报数据可通过脚本或雷达页面刷新。
- IV Rank 需待每日扫描积累足够历史后才有数据。
- VIX 历史可通过脚本或雷达页面刷新，并缓存在
  `data/options_universe/vix_history.csv`。当缓存缺失时，雷达会在
  无市场状态调整的情况下运行（`market_regime=Unknown`）。
- 单标的筛选器在 VIX 缓存缺失时也会优雅降级为 `market_regime=null`
  （无惩罚）。
