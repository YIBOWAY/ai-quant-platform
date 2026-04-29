# Phase 9 API Execution

## 环境要求

- Windows + conda env `ai-quant`
- Python 3.11+
- 本地安装 API extra

## 安装

```powershell
conda activate ai-quant
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[api,dev]"
```

## 启动

标准 FastAPI / uvicorn 启动方式：

```powershell
python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765
```

项目 CLI 包装方式：

```powershell
quant-system serve --host 127.0.0.1 --port 8765
```

这两条命令启动的是同一个 FastAPI app。`quant-system serve` 内部仍然调用 `uvicorn`，只是帮你封装了 app factory 路径和本地安全默认值。

打开健康检查：

```powershell
curl http://127.0.0.1:8765/api/health
```

## 测试

```powershell
python -m pytest tests/test_api_health.py tests/test_api_data.py tests/test_api_factors.py tests/test_api_backtest.py tests/test_api_paper.py tests/test_api_agent.py tests/test_api_prediction_market.py tests/test_api_safety.py -q
ruff check .
```

## 成功标志

- `/api/health` 返回 `status=ok`
- `safety.live_trading_enabled=false`
- `safety.bind_address=127.0.0.1`
- `/api/orders/submit` 返回 404

## 公开绑定

默认禁止：

```powershell
quant-system serve --host 0.0.0.0 --port 8765
```

如确实要给局域网前端测试，需要同时设置：

```powershell
$env:QS_API_ALLOW_PUBLIC_BIND="I_UNDERSTAND"
quant-system serve --host 0.0.0.0 --port 8765 --bind-public
```

这仍然不会打开 live trading。

## 一键启动前后端

从仓库根目录执行：

```powershell
conda activate ai-quant
.\scripts\start_phase9_full_stack.ps1
```

默认端口：

- 后端 API：`http://127.0.0.1:8765`
- 前端页面：`http://127.0.0.1:3000`

如果 `3000` 已被占用，可以换一个前端端口：

```powershell
.\scripts\start_phase9_full_stack.ps1 -FrontendPort 3001
```

停止服务：

```powershell
.\scripts\stop_phase9_full_stack.ps1
```

脚本会把进程号写到 `data/_runtime/pids/`，日志写到 `data/_runtime/logs/`。
