# 富途环境配置

## 1. 目的

本指南用于验证本项目所使用的本地只读富途行情数据环境。

涵盖内容：

- 激活正确的 conda 环境
- 检查 OpenD GUI 是否已在运行
- 在 `ai-quant` 中验证 Python SDK
- 运行安全的仅行情验证脚本

本指南**不会**启用交易功能。

## 2. 安全边界

本配置仅用于**只读行情数据**。

请勿：

- 解锁交易
- 创建交易上下文
- 下单
- 改单
- 暴露凭证

## 3. 官方技能在本 Codex 环境中的状态

官方富途 OpenD 技能已安装到全局 Codex 技能目录：

- `C:\Users\86189\.codex\skills\futuapi`
- `C:\Users\86189\.codex\skills\install-futu-opend`

已安装的 `futuapi` 技能同时包含行情与交易辅助脚本。本项目仅使用行情/只读部分。

用于仓库验证的等效手动流程：

1. 先验证已有的本地 OpenD GUI
2. 在 `ai-quant` 中验证 Python 包
3. 仅在缺失时将 `futu-api` 安装到 `ai-quant`
4. 运行本地只读验证脚本

## 4. 激活正确的环境

```powershell
conda activate ai-quant
python -V
python -c "import sys; print(sys.executable)"
```

预期结果：

- Python 指向 `D:\anaconda3\envs\ai-quant\python.exe`
- 版本为 Python 3.11+

## 5. 确认 OpenD GUI 正在运行

### 5.1 可视化检查

打开已安装的 GUI 并确认已登录：

`E:\Quant_data\Futu_OpenD_10.4.6408_Windows\Futu_OpenD-GUI_10.4.6408_Windows`

### 5.2 进程检查

```powershell
conda activate ai-quant
Get-Process | Where-Object { $_.ProcessName -like '*OpenD*' -or $_.ProcessName -like '*Futu*' } | Select-Object ProcessName,Id,Path
```

### 5.3 端口检查

```powershell
conda activate ai-quant
Test-NetConnection -ComputerName 127.0.0.1 -Port 11111 | Select-Object ComputerName,RemotePort,TcpTestSucceeded
```

预期结果：

- `TcpTestSucceeded = True`

## 6. 在 `ai-quant` 中安装 / 验证 Python SDK

首先检查：

```powershell
conda activate ai-quant
python -m pip show futu-api
```

若缺失，使用所需镜像源安装：

```powershell
conda activate ai-quant
python -m pip install futu-api -i https://pypi.tuna.tsinghua.edu.cn/simple
```

官方包参考：

- 富途文档展示了通过 `pip install futu-api` 进行 Python 安装

## 7. 运行验证脚本

脚本：

- `scripts/verify_futu_connection.py`

命令：

```powershell
conda activate ai-quant
python scripts/verify_futu_connection.py
```

默认检查项：

- SDK 导入
- 行情上下文创建
- OpenD 全局状态
- 以下标的的历史日 K 线：
  - `US.AAPL`
  - `US.NVDA`
  - `US.MSFT`
  - `US.SPY`
- `US.AAPL` 的期权到期日列表
- 某个到期日的期权链
- 某个期权合约的期权快照

## 8. 成功输出示例

脱敏示例：

```text
verify_futu_connection
host=127.0.0.1 port=11111
tickers=US.AAPL,US.NVDA,US.MSFT,US.SPY
global_state=qot_logined=True qot_connect_status=None
history_kline_checks
  US.AAPL: rows=9 first={'code': 'US.AAPL', 'time_key': '2024-01-02 00:00:00', ...}
  US.NVDA: rows=9 first={...}
  US.MSFT: rows=9 first={...}
  US.SPY: rows=9 first={...}
options_checks
  expiries=rows=26 selected_expiry=2026-05-08 distance=6
  chain_rows=148 first={'code': 'US.AAPL260508C110000', ...}
  option_snapshot={'code': 'US.AAPL260508C110000', 'bid_price': ..., 'ask_price': ...}
PASS read_only_quote_connectivity
```

## 9. 常见错误

### 9.1 `Package(s) not found: futu-api`

含义：

- SDK 未安装在 `ai-quant` 中

修复：

```powershell
conda activate ai-quant
python -m pip install futu-api -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 9.2 无法连接到 `127.0.0.1:11111`

含义：

- OpenD GUI 未运行
- 或其监听在不同的主机/端口

修复：

- 启动 OpenD GUI
- 确认登录已完成
- 确认 API 端口为 `11111`

### 9.3 行情登录为 false / 权限错误

含义：

- OpenD 已打开，但行情服务未完全登录
- 或该账户缺少所需的行情数据权限

检查：

- 美股 LV3 权限
- 美股期权 LV1 权限

### 9.4 股票数据为空

可能原因：

- 标的格式无效
- 请求的日期范围内没有 K 线数据
- 权限 / 行情数据延迟问题

使用富途标的格式：

- `US.AAPL`
- `US.NVDA`
- `US.MSFT`
- `US.SPY`

### 9.5 期权字段缺失或为零

可能原因：

- 返回的行情中未包含该字段
- 权限层级未开放该字段
- 所选合约已过时 / 已到期 / 流动性差

平台必须将缺失的期权字段视为缺失数据，而不是凭空捏造。

## 10. 权限验证清单

应手动检查的内容：

- 返回了美股历史 K 线
- 返回了美股期权到期日
- 返回了美股期权链
- 在可用时，bid/ask/volume 等快照字段返回真实值

如果某些合约的 IV / 希腊值 / 未平仓量缺失或为零，请将其记录为数据限制，而不是猜测。

## 11. 本仓库说明

- 所有验证必须在 `ai-quant` 中运行
- 如果 OpenD GUI 已正常工作，应复用
- 本阶段保持只读
- 不应向代码库添加任何交易上下文

## 12. 官方参考资料

- OpenD 概览: https://openapi.futunn.com/futu-api-doc/en/opend/opend-intro.html
- Python 环境与安装: https://openapi.futunn.com/futu-api-doc/en/quick/env.html
- Python 示例安装说明: https://openapi.futunn.com/futu-api-doc/en/quick/demo.html
- 历史 K 线: https://openapi.futunn.com/futu-api-doc/en/quote/request-history-kline.html
- 期权到期日: https://openapi.futunn.com/futu-api-doc/en/quote/get-option-expiration-date.html
- 期权链: https://openapi.futunn.com/futu-api-doc/en/quote/get-option-chain.html
