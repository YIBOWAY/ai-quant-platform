# Phase 9 前端/API 集成检查

## 范围

本历史检查验证了 `src/frontend/` 中的 Next.js 前端
能够在本地运行，并读取来自 Phase 9 后端 API 的真实响应。如需
当前的运行命令，请优先参考 `README.md`。

## 本地端口

- 后端 API：`http://127.0.0.1:8765`
- 前端：`http://127.0.0.1:3001`

## 后端启动选项

后端是一个 FastAPI 应用。标准的直接启动命令是：

```powershell
python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765
```

含义：

- `python -m uvicorn`：启动 FastAPI 所使用的 ASGI 服务器。
- `quant_system.api.server:create_app`：从项目中加载应用工厂。
- `--factory`：告诉 uvicorn 必须调用 `create_app` 来构建应用。
- `--host 127.0.0.1`：仅绑定到本机。
- `--port 8765`：在端口 `8765` 上暴露后端 API。

项目 CLI 还提供了以下便捷封装：

```powershell
quant-system serve --host 127.0.0.1 --port 8765
```

该封装在内部仍然调用 `uvicorn`。它的存在是为了与 `data`、`factor`、`backtest`、`paper` 保持相同的项目 CLI 风格，并强制执行本地安全的默认设置，例如在未明确确认前阻止公开绑定。

完整的 Web 测试需要同时运行两个服务：后端在 `8765`，
前端在 `3001`。

## 使用的命令

```powershell
conda activate ai-quant
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[api,dev]"
python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765
```

```powershell
cd src/frontend
npm install
npm run lint
npm run build
npm run dev -- --hostname 127.0.0.1 --port 3001
```

从仓库根目录一键本地启动：

```powershell
conda activate ai-quant
.\scripts\start_phase9_full_stack.ps1
```

如果端口 `3001` 已被占用：

```powershell
.\scripts\start_phase9_full_stack.ps1 -FrontendPort 3002
```

停止：

```powershell
.\scripts\stop_phase9_full_stack.ps1
```

## 后端冒烟测试结果

本次集成运行通过真实 API 调用创建了示例后端产物：

- `POST /api/backtests/run`
- `POST /api/paper/run`
- `POST /api/agent/tasks`
- `POST /api/prediction-market/scan`
- `POST /api/prediction-market/dry-arbitrage`
- `GET /api/symbols`
- `GET /api/factors`

观测到的结果：

```json
{
  "backend": "ok",
  "frontend_status": 200,
  "pm_candidates": 3,
  "pm_proposed_trades": 3,
  "symbols": "SPY,QQQ,IWM,TLT,GLD",
  "factors": 5
}
```

## 浏览器冒烟测试结果

在等待后端驱动的文本出现后，捕获了 Playwright 截图：

- `output/playwright/dashboard.png` 等待 `API CONNECTED`
- `output/playwright/data-explorer.png` 等待 `API source`
- `output/playwright/order-book.png` 等待 `Loaded`

## 备注

- 前端现在使用 `NEXT_PUBLIC_QUANT_API_BASE_URL`，默认值为 `http://127.0.0.1:8765`。
- 未添加任何实盘交易端点。
- 预测市场视图仅使用示例数据。
- 智能体视图仅读取候选项元数据；候选项来源不会被执行。
