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

```powershell
quant-system serve --host 127.0.0.1 --port 8765
```

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
