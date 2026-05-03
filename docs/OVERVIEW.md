# 平台总览

这是一套本地运行的量化研究和模拟交易平台。

它现在主要分成两部分：

1. 股票研究主链  
   数据、因子、回测、实验、风控、paper trading。

2. 预测市场研究主链  
   只读获取公开数据、扫描、历史采集、时间序列回放、图表和报告。

它不是实盘系统，也不会帮你连接钱包或下真实订单。

---

## 现在能做什么

- 跑真实历史股票数据研究
- 生成因子结果
- 跑股票回测
- 跑股票模拟交易
- 管理实验结果
- 让 AI 助手生成候选研究产物
- 只读研究 Polymarket
- 采集 Polymarket 历史快照
- 跑 Polymarket 时间序列 simulated replay

---

## 安全边界

下面这些边界一直有效：

- `dry_run = true`
- `paper_trading = true`
- `live_trading_enabled = false`
- `kill_switch = true`

另外还有几条硬限制：

- AI Agent 不能直接改因子库或注册策略
- AI Agent 产物只会进入候选区，必须人工确认
- 预测市场模块只读，不签名、不连钱包、不下单
- API 不提供真实下单入口

---

## How to start the API server

项目提供了一个本地 HTTP API，主要给前端页面读结果和触发本地任务用。

```powershell
conda activate ai-quant
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[api]"
quant-system serve --host 127.0.0.1 --port 8765
```

这条命令本质上还是启动后端服务，只是用项目自己的命令包装了一层，方便统一入口。

如果你更习惯直接启动，也可以这样：

```powershell
python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765
```

健康检查：

```powershell
curl http://127.0.0.1:8765/api/health
```

默认只绑定本机 `127.0.0.1`。

---

## 下一步读什么

- 想看整体设计：读 [SYSTEM_DESIGN_RESEARCH.md](SYSTEM_DESIGN_RESEARCH.md)
- 想按阶段看：读 [INDEX.md](INDEX.md)
- 想直接上手：读各阶段 `execution/` 文档
- 想理解为什么这么设计：读各阶段 `learning/` 文档
