# Futu 故障排查

## OpenD 未运行

现象：

- API 返回连接错误。
- `scripts/verify_futu_connection.py` 无法创建行情上下文。

修复：

1. 启动 Futu OpenD GUI。
2. 确认已登录。
3. 确认 API 端口正在监听：

```powershell
Test-NetConnection 127.0.0.1 -Port 11111
```

预期：

```text
TcpTestSucceeded : True
```

## Conda 环境错误

现象：

- `ModuleNotFoundError: No module named 'futu'`

修复：

```powershell
conda activate ai-quant
python -m pip show futu-api
```

如果缺失：

```powershell
python -m pip install futu-api -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 权限被拒绝

现象：

- Futu 返回权限相关的错误。
- 股票数据正常，但期权字段为空。

修复：

1. 在 Futu 中确认市场行情权限。
2. 运行：

```powershell
python scripts/verify_futu_connection.py
```

3. 检查股票 K 线、期权到期日、期权链和期权快照是否各自返回数据。

## 数据为空

可能原因：

- ticker 无效
- 周末或市场休市日期范围
- 不支持的频率
- 标的没有期权
- 数据权限未覆盖所请求的历史区间

尝试：

```powershell
curl "http://127.0.0.1:8765/api/market-data/history?ticker=SPY&start=2024-01-02&end=2024-01-12&freq=1d&provider=futu"
```

## `data prices` 返回非零或超时

先直接复现严格只读 leaf：

```powershell
quant-system data prices --symbol AAPL --symbol SPY --start 2026-01-01 --end 2026-07-10 --provider futu --adjustment qfq --format json
```

- `historical_prices_invalid_request`（exit 2）：检查严格 `YYYY-MM-DD`、start/end 顺序、
  25-symbol 与 500-inclusive-date 上限，以及重复/非美股 symbol。
- `historical_prices_configuration_error`：检查 `QS_FUTU_PORT` 等配置类型与范围。
- `historical_prices_provider_unavailable` / `historical_prices_provider_error`：查看
  `provider_code`，确认 OpenD 已登录、权限和端口。
- `provider_timeout`：TCP 可达不代表 OpenD 协议握手正常。可检查 OpenD 日志，并按需调整
  正整数 `QS_FUTU_REQUEST_TIMEOUT_SECONDS`；它同时约束 TCP 探针、首连与查询。
- `historical_prices_contract_invalid`：Futu 返回缺标的、重复日期、非法价格或 provenance
  漂移；不要改用 sample/local 数据掩盖问题。

该命令的 stdout 应能作为一个完整 JSON 文档解析；Futu lifecycle 日志只在 stderr。

## 前端无法连接后端

检查后端是否在运行：

```powershell
curl http://127.0.0.1:8765/api/health
```

如果前端运行在 `3001` 端口，CORS 已为以下地址配置：

- `http://127.0.0.1:3001`
- `http://localhost:3001`

## 下拉框文字难以辨认

前端 select 菜单使用深色选项样式作为临时兼容性修复。

如果浏览器忽略选项样式，请使用键盘选择，或在后续前端清理中切换为自定义 Select 组件。

## 安全边界

不要通过添加交易上下文、账户解锁、订单提交或签名代码来排查问题。本集成仅为只读市场数据。
