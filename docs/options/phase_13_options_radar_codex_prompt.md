# Phase 13 Codex GPT-5.5 Prompt — 每日全市场期权卖方扫描器（Options Radar）

> **使用说明**：把整份 prompt 贴给 Codex GPT-5.5；它会基于现有 Phase 12 代码完成 Phase 13 全部代码 + 文档 + 测试 + commit。

---

## 角色与上下文

你是这个仓库 (YIBOWAY/ai-quant-platform, branch `phase-10-fix`) 的资深 Python + Next.js 工程师。Phase 0-12 已交付：FastAPI + Next.js 15 + Tailwind v4 + react-hook-form + zod + react-query + sonner；股票真实数据 (Tiingo + Futu)、Polymarket 只读、期权单标的卖方筛选器都已就位 (230 pytest + ruff clean)。

**你必须遵守的不可变约束（红线）：**
- 不实盘、不签名、不连钱包、不下任何真实/模拟订单。
- `live_trading_enabled=false`、`kill_switch=true`、`bind_address=127.0.0.1`、`/api/orders/submit` 必须仍 404。
- Futu 只能用 `OpenQuoteContext`，**严禁** `OpenSecTradeContext / trd_open / unlock_trade / place_order / modify_order` 出现在新增代码或测试里。
- 所有 API 响应继续含 `safety: { dry_run, paper_trading, kill_switch }`。
- CORS allowlist 仍为 `127.0.0.1:3000/3001`，不允许 `*`。
- 所有外部数据源 (Futu、yfinance) 通过 provider/factory 接口 mock 化，单测必须不依赖网络与 OpenD。

**先读 →**
- [options_screener_review_2026_05_03.md](options_screener_review_2026_05_03.md)（你这次要落地的目标）
- [src/quant_system/options/screener.py](../src/quant_system/options/screener.py)
- [src/quant_system/options/models.py](../src/quant_system/options/models.py)
- [src/quant_system/data/providers/futu.py](../src/quant_system/data/providers/futu.py)
- [src/quant_system/api/routes/options.py](../src/quant_system/api/routes/options.py)
- [src/quant_system/prediction_market/storage.py](../src/quant_system/prediction_market/storage.py)（参考 JSONL append + replay 模式）
- [src/frontend/components/forms/OptionsScreenerForm.tsx](../src/frontend/components/forms/OptionsScreenerForm.tsx)
- [.claude/skills/futuapi/SKILL.md](../.claude/skills/futuapi/SKILL.md) — Futu 接口速查（限频 10 次 / 30 秒、`get_market_snapshot` 单次 ≤ 400、`get_option_chain` / `get_option_expiration_date`）

**Phase 13 目标功能**：每天美东收盘后定时跑一次，扫描"S&P 500 ∪ Nasdaq 100"全市场，对每个标的运行 sell-put 与 covered-call 卖方筛选器，把全市场最适合当卖方的股票及具体期权合约（按综合分排序）落盘 + 通过新前端页面 `/options-radar` 展示。

---

## 子阶段 13-0：Universe & 配置

### 13-0-1 Universe 数据

新建 [src/quant_system/options/universe.py](../src/quant_system/options/universe.py)：

- 维护一个静态 `data/options_universe/sp500_nasdaq100.csv`（提交到 git，~530 行），列：`ticker, name, sector, exchange, source`（source ∈ `{sp500, nasdaq100, both}`）。**不要**在 runtime 联网拉维基百科或 SSGA；写一个 oneshot 脚本 `scripts/refresh_options_universe.py` 给用户手动跑一次（用 yfinance 或离线 CSV）。
- `OptionsUniverse.load(path)` 返回 `list[UniverseEntry]`；支持 `top_n` 过滤（按市值降序）。
- 默认精选首版 universe：去重后取前 100 标的（高流动性优先）。

### 13-0-2 settings 扩展

在 [src/quant_system/config/settings.py](../src/quant_system/config/settings.py) 新增 `OptionsRadarSettings`（嵌入 `Settings`）：

```python
class OptionsRadarSettings(BaseSettings):
    enabled: bool = True
    universe_path: Path = Path("data/options_universe/sp500_nasdaq100.csv")
    universe_top_n: int = 100
    output_dir: Path = Path("data/options_scans")
    # Futu 限频：行情接口 10 次 / 30 秒 / 接口
    futu_rate_limit_per_30s: int = 10
    futu_request_pause_seconds: float = 3.1   # 安全余量
    snapshot_batch_size: int = 200
    max_dte_for_radar: int = 60
    min_dte_for_radar: int = 7
    iv_history_lookback_days: int = 252
    earnings_calendar_path: Path = Path("data/options_universe/earnings_calendar.csv")
```

加 `QS_OPTIONS_RADAR_*` 到 [.env.example](../.env.example)。

---

## 子阶段 13-1：限频客户端

新建 [src/quant_system/options/rate_limiter.py](../src/quant_system/options/rate_limiter.py)：

- 实现一个 token-bucket：`TokenBucket(max_tokens=10, refill_seconds=30)`。
- 包装一个 `RateLimitedFutuProvider`（`FutuMarketDataProvider` 的 facade），每次进入 `fetch_option_*` / `fetch_market_snapshots` / `fetch_ohlcv` 前先 acquire 一个 token，超时再 sleep。
- 必须可注入假的时钟做测试 (`time_func: Callable[[], float]`).

测试：[tests/test_options_rate_limiter.py](../tests/test_options_rate_limiter.py)
- 100 次请求在 fake clock 下耗时 ≈ `(100 / 10) × 30 = 300s`。
- 突发 10 次后第 11 次必须等待 ≥ 30s。

---

## 子阶段 13-2：IV Rank 历史快照存储

新建 [src/quant_system/options/iv_history.py](../src/quant_system/options/iv_history.py)：

- 每次 daily-scan 把每个标的的"当日 ATM IV（一个最接近 30 DTE 的 ATM 期权 IV）"追加到 `data/options_scans/iv_history/{ticker}.jsonl`。
- `compute_iv_rank(ticker, current_iv, lookback_days=252) -> float | None`：取过去 252 个交易日内的 IV 序列，用 percentile 计算 IVR。样本不足 30 天返回 None。

测试：构造合成序列，验证 IVR 边界值（min=0、max=100、中位数=50）。

---

## 子阶段 13-3：Earnings 日历离线缓存

新建 [src/quant_system/options/earnings_calendar.py](../src/quant_system/options/earnings_calendar.py)：

- 读取 `data/options_universe/earnings_calendar.csv`（列：`ticker, earnings_date`）。
- `next_earnings(ticker, today) -> date | None`。
- `is_within(ticker, today, days)` 用于实施 `avoid_earnings_within_days` 硬约束。
- 配套写一个脚本 `scripts/refresh_earnings_calendar.py`，**用 yfinance** 离线刷新（不在 runtime 联网）。脚本里加日志：来源、刷新时间。
- 单测全部 mock 化，不能真的请求 yfinance。

---

## 子阶段 13-4：Radar Scanner 跨标的扫描

新建 [src/quant_system/options/radar.py](../src/quant_system/options/radar.py)：

```python
@dataclass
class OptionsRadarConfig:
    strategies: list[Literal["sell_put", "covered_call"]] = ("sell_put", "covered_call")
    base_screen_config: OptionsScreenerConfig
    universe_top_n: int = 100
    top_per_ticker: int = 5

@dataclass
class OptionsRadarCandidate:
    ticker: str
    sector: str | None
    strategy: str
    candidate: OptionsScreenerCandidate    # 复用现有模型
    iv_rank: float | None
    earnings_in_window: bool
    global_score: float                    # 综合分

@dataclass
class OptionsRadarReport:
    run_date: str                          # America/New_York 当日
    started_at: str                        # ISO UTC
    finished_at: str
    universe_size: int
    scanned_tickers: int
    failed_tickers: list[tuple[str, str]]  # (ticker, error_code)
    candidates: list[OptionsRadarCandidate]
```

要点：
- 串行遍历 universe；每标的复用 [run_options_screener](../src/quant_system/options/screener.py)；按 `top_per_ticker` 取头部。
- 每标的失败（OpenD 断、permission_denied、no_data）记录到 `failed_tickers`，**不要中断扫描**。
- 综合分公式（写在常量中、可调）：

  ```
  global_score =
      rating_weight   ({Strong: 100, Watch: 30, Avoid: 0})
    + clip(APR × 100, 0, 60)              # 每 1% APR 1 分，封顶 60
    + 0.4 × clip(iv_rank, 0, 100)         # IVR 加分，未知 IVR 当 0
    - 50 × earnings_in_window             # 财报日窗口扣分
    - 100 × (spread_pct > 0.10)           # 高滑点惩罚
  ```

- 排序：`global_score desc, APR desc, spread_pct asc`。

新建 [src/quant_system/options/radar_storage.py](../src/quant_system/options/radar_storage.py)：
- `RadarSnapshotStore.write(report, output_dir)` → 写 `data/options_scans/{run_date}.jsonl`（每行一个 candidate）+ `data/options_scans/{run_date}_meta.json`（report 元信息）。
- `RadarSnapshotStore.read(run_date)` → 加载 candidates。
- 写入幂等：相同 `(run_date, ticker, contract_symbol, strategy)` 重复时覆盖。

测试：
- [tests/test_options_radar.py](../tests/test_options_radar.py) — 用假 provider 跑 5 标的，验证 universe 加载、错误隔离、score 单调性、storage 往返。

---

## 子阶段 13-5：CLI + Windows 任务计划

在 [src/quant_system/cli.py](../src/quant_system/cli.py) 注册子命令：

```bash
quant-system options daily-scan [--top 100] [--strategies sell_put,covered_call] [--date 2026-05-03] [--dry-run]
quant-system options refresh-universe
quant-system options refresh-earnings
```

- `daily-scan` 默认 `--date` 取美东当日；`--dry-run` 只打印计划不写盘。
- 退出码：0 全部成功 / 2 部分失败 / 3 完全失败。

在 [scripts/](../scripts) 下新增 [scripts/run_options_radar.ps1](../scripts/run_options_radar.ps1)：

```powershell
# 由 Windows 任务计划程序在每个工作日 BJT 06:30（美东收盘后）触发
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot/..
$env:PYTHONPATH = "."
& D:\anaconda3\envs\ai-quant\python.exe -m quant_system.cli options daily-scan --top 100
```

文档化：[phase_13_scheduler_setup.md](phase_13_scheduler_setup.md) — 写明如何在 Windows 任务计划程序里：触发器（每个工作日 06:30）、操作（运行上述 ps1）、条件（仅在网络可用时运行）。**严禁** 写入注册表或自启动。

---

## 子阶段 13-6：API 端点

新建 [src/quant_system/api/routes/options_radar.py](../src/quant_system/api/routes/options_radar.py)：

- `GET /api/options/daily-scan?date=YYYY-MM-DD&strategy=sell_put&sector=Tech&top=50`
  - 默认 date = 最近一份可读快照。
  - 返回 `{ run_date, candidates: [...], universe_size, failed_tickers, safety: {...} }`。
  - 4xx：日期没有数据返回 404 + `code=no_radar_snapshot`。
- `GET /api/options/daily-scan/dates` → 列出已有快照日期（按降序）。
- 在 [src/quant_system/api/server.py](../src/quant_system/api/server.py) 注册路由。

测试：[tests/test_api_options_radar.py](../tests/test_api_options_radar.py) — 用 fixture 写假 jsonl，断言 200/404、过滤、safety footer。

---

## 子阶段 13-7：前端 `/options-radar` 页面

新建：

- [src/frontend/app/options-radar/page.tsx](../src/frontend/app/options-radar/page.tsx)（薄包装，渲染 form 组件，支持 `?lang=zh`）
- [src/frontend/components/forms/OptionsRadarView.tsx](../src/frontend/components/forms/OptionsRadarView.tsx)：
  - 顶部：日期选择器（从 `/api/options/daily-scan/dates` 拉取列表）+ 策略 select（sell_put / covered_call / all）+ Sector 多选 + DTE 桶（7-21 / 21-45 / 45-60）+ Top N。
  - 中部：safety banner（read-only / no orders）。
  - 主体：表格列 — Symbol | Sector | Strategy | Expiry | Strike | Mid | APR | IV | IVR | Δ | OI | Spread | Earnings | Score | Rating。点击行内"详情"展开 `notes`。
  - CSV 导出按钮（前端纯客户端生成）。
  - 中英文文案（参考 OptionsScreenerForm copy 模式）。
- 在 [src/frontend/components/Sidebar.tsx](../src/frontend/components/Sidebar.tsx) 加路由项。
- Hydration-safe 模式必须保留：`<form onSubmit={e => e.preventDefault()}>` + `<button type="button">`。

新增 Playwright e2e [src/frontend/tests/e2e/phase13-radar-smoke.spec.ts](../src/frontend/tests/e2e/phase13-radar-smoke.spec.ts)：访问页面、断言 safety banner、断言 mock fixture 渲染。

---

## 子阶段 13-8：Futu LV2 / 限制告知

更新 [futu_options_data_provider.md](../futu/futu_options_data_provider.md) 增加章节 "Required entitlements"：

- 美股期权报价（IV / Greeks / OI / 实时 bid-ask）需要 **美股 LV2 行情订阅**（Futu/moomoo APP 内购买）。
- 没有 LV2 时这些字段会为空 → 全部走入硬约束失败 → radar 输出空。
- OpenD 必须本地运行；账户必须实名 + 登录。
- 接口限频 10 次 / 30 秒 / 接口；`get_market_snapshot` 单次 ≤ 400。
- 大陆地区新开 Futu 美股账户合规收紧（早年开户可继续用）。
- **Futu OpenAPI 服务条款不允许对外提供数据 API；本扫描器仅限自用研究。**

---

## 子阶段 13-9：文档与发布

新建：
- [docs/architecture/phase_13_architecture.md](architecture/phase_13_architecture.md) — 架构图（ASCII）、数据流、限速与故障隔离策略。
- [docs/execution/phase_13_execution.md](execution/phase_13_execution.md) — 实操步骤、命令、Windows Scheduler 截图说明。
- [docs/learning/phase_13_learning.md](learning/phase_13_learning.md) — 设计决策、踩坑、IVR 累积冷启动问题、Earnings 数据源选型。
- [docs/delivery/phase_13_delivery.md](delivery/phase_13_delivery.md) — DoD 验收清单、测试结果、commit 列表。
- [phase_13_design_spec.md](phase_13_design_spec.md) — 完整设计冻结。
- 在 [INDEX.md](../INDEX.md) 的"阶段地图"和"特别专题"两个表格加 Phase 13 行。

---

## DoD 验收清单（必须每条都过）

1. `pytest -q` 全部通过；新增 ≥ 5 个测试文件。
2. `ruff check src/quant_system tests` All checks passed。
3. `npm --prefix src/frontend run lint` 通过。
4. `npx playwright test --config src/frontend/playwright.config.ts` 通过。
5. `quant-system options daily-scan --top 5 --dry-run` 在没有 OpenD 时优雅失败（exit code 3 + 友好错误）。
6. `quant-system options daily-scan --top 5`（带 mock provider env）能写出 `data/options_scans/{date}.jsonl` 与 `_meta.json`。
7. `curl http://127.0.0.1:8765/api/options/daily-scan?date=...` 返回 JSON 含 safety footer。
8. 前端 `/options-radar` 页面 hydrated、读取 fixture、CSV 导出可用。
9. 安全自检脚本（参考 Phase 11 模式）— `/api/orders/submit` 仍 404；新增端点都不接受 `live_key`；CORS allowlist 不变。
10. 全部代码无 `OpenSecTradeContext / trd_open / unlock_trade / place_order / modify_order / web3 / eth_account / wallet / private_key` 出现（grep 校验）。

---

## Commit 策略（提交时必须按此分块）

按下面顺序产出独立 commit，每个 commit 都要在 message 里写明动机 + 影响面 + 测试结果摘要：

1. `feat(options): static SP500+Nasdaq100 universe + refresh script`
2. `feat(options): token-bucket rate limiter for futu read-only calls`
3. `feat(options): IV history store and IV rank computation`
4. `feat(options): offline earnings calendar with yfinance refresh script`
5. `feat(options): radar scanner, scoring, storage`
6. `feat(cli): options daily-scan / refresh-universe / refresh-earnings subcommands`
7. `feat(api): /api/options/daily-scan endpoints with safety footer`
8. `feat(frontend): /options-radar page with date / strategy / sector filters`
9. `test(options-radar): unit + api + playwright coverage`
10. `docs(phase-13): design spec, architecture, execution, learning, delivery, INDEX update`

每个 commit 之前先 `git status` + `git diff --stat` 自检；不要把多个领域揉到一个 commit；不要 force push；保持当前分支 `phase-10-fix`。

---

## 子代理使用建议

如果你需要在执行过程中：
- 找现有代码模式 → 用 `Explore` 子代理（read-only，避免污染主上下文）。
- 验证 Futu 接口字段名 → 读 [.claude/skills/futuapi/SKILL.md](../.claude/skills/futuapi/SKILL.md) + `python skills/futuapi/scripts/quote/get_option_chain.py --help` 等待用户授权后再实际调用（默认 mock）。
- 写架构 ASCII 图 → 自己画，不要联网。

---

## 完成标准

把"230 passed → ≥ 250 passed、ruff clean、playwright pass、新前端页面手动可访问、安全自检全过、INDEX.md 已含 Phase 13"作为唯一交付完成信号。**输出必须包含一份"实际跑通命令清单 + 输出截图样例"附在 `docs/delivery/phase_13_delivery.md` 末尾。**
