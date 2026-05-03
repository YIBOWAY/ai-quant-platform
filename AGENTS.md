# AGENTS.md

本文件给后续 AI agent 使用。回复用户时要简单、直白、中文优先；实际做事时要严谨、先验证再汇报。

## 项目状态

- 当前项目已经完成到 Phase 13。
- 后端是本地 FastAPI API。
- 前端是 `src/frontend` 下的 Next.js 应用。
- 当前主数据方向包括股票/ETF、Futu 期权、Polymarket 只读研究、AI 研究助手。

## 环境

- Windows + conda env `ai-quant`。
- 运行 Python、pytest、ruff、`quant-system` 前先执行：

```powershell
conda activate ai-quant
```

- pip 安装优先使用清华镜像：

```powershell
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple ...
```

## 安全红线

- 不实盘。
- 不下单。
- 不签名。
- 不连接钱包。
- 不解锁 Futu 交易账户。
- 不引入 Futu 交易 context。
- 不加入真实 broker 下单接口。
- 不削弱 `dry_run`、`paper_trading`、`live_trading_enabled=false`、`kill_switch=true`。

Futu 只能用于只读行情数据。Polymarket 只能用于只读公开数据和研究回放。

## 常用验证

```powershell
python -m pytest -q
ruff check src/quant_system tests
npm --prefix src/frontend run lint
npm --prefix src/frontend run build
```

浏览器联调：

```powershell
cd src/frontend
$env:PW_E2E="1"
npx playwright test --config playwright.config.ts --workers=1
```

## 启动

后端：

```powershell
quant-system serve --host 127.0.0.1 --port 8765
```

前端：

```powershell
cd src/frontend
npm run dev -- --hostname 127.0.0.1 --port 3001
```

## 文档入口

- `README.md`
- `docs/OVERVIEW.md`
- `docs/INDEX.md`
- `docs/delivery/phase_13_delivery.md`
- `docs/execution/phase_13_execution.md`
