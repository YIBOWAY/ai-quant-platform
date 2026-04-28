# Phase 5 学习文档

## 当前阶段核心概念

Phase 5 的目标是把“研究和回测”往“可控的模拟交易系统”推进一步。

本阶段新增：

- 交易前风控
- 交易后状态记录
- 订单生命周期
- paper broker
- 部分成交模拟
- 交易日志
- 风控违规日志
- paper trading 报告

当前仍然不会接真实券商，也不会真实下单。

## 从零解释知识点

### 风控引擎

风控引擎是交易系统里的独立守门人。

策略或实验可以提出订单，但订单必须先经过风控检查。

本阶段检查：

- kill switch
- 单票最大仓位
- 单笔订单最大金额
- 最大日内亏损
- 最大回撤
- allowed symbols
- blocked symbols

### 订单生命周期

订单不是只有“买了”或“没买”。

本阶段支持：

- created：订单创建
- submitted：提交到 broker
- partially_filled：部分成交
- filled：全部成交
- cancelled：取消
- rejected：被拒绝

每次状态变化都会写入订单事件日志。

### Paper Broker

Paper broker 是一个模拟券商。

它不会连接真实市场，也不会动真实资金。

它和未来 live broker 使用同一种接口，这样 Phase 6 可以开始做 adapter，而不用重写上层订单管理逻辑。

### 部分成交

真实交易中，订单不一定一次成交完。

本阶段支持一个最小模拟：每次市场数据到来时，只成交订单的一部分，剩余部分等待下一次处理。

### 风控违规日志

被拒绝的订单不会消失。

系统会记录：

- 哪条规则触发
- 哪个 symbol
- 哪个 order_id
- 触发时间
- 拒绝原因

## 代码和概念如何对应

- `src/quant_system/risk/models.py`：风控配置、风控上下文、风控违规记录。
- `src/quant_system/risk/engine.py`：执行风控检查。
- `src/quant_system/execution/models.py`：订单、成交、订单状态。
- `src/quant_system/execution/order_manager.py`：订单创建、提交、拒绝、取消和状态日志。
- `src/quant_system/execution/paper_broker.py`：模拟 broker 和部分成交。
- `src/quant_system/execution/portfolio.py`：模拟账户现金和持仓。
- `src/quant_system/execution/pipeline.py`：样例 paper trading loop。
- `src/quant_system/execution/storage.py`：保存订单、成交和风控日志。
- `src/quant_system/execution/reporting.py`：生成 paper trading 报告。
- `src/quant_system/cli.py`：提供 `paper run-sample` 命令。

## 常见错误

1. 策略绕过风控直接下单。

   当前系统的订单必须经过 `OrderManager`，而 `OrderManager` 会先调用 `RiskEngine`。

2. kill switch 只是一条日志。

   当前 kill switch 会直接拒绝所有新订单。

3. 被拒绝订单仍然提交给 broker。

   当前 rejected 订单不会进入 paper broker。

4. 只记录成交，不记录订单状态。

   当前订单状态变化会进入 `order_events.parquet`。

5. paper broker 和未来 live broker 接口不一致。

   当前有 `BrokerAdapter` 协议，paper broker 按这个接口实现。

## 自检清单

- 风控拒单是否有测试？
- kill switch 是否有测试？
- 部分成交是否有测试？
- 正常成交是否更新现金和持仓？
- 被拒绝订单是否没有提交给 broker？
- CLI 是否生成订单日志、成交日志、风控日志和报告？
- `python -m pytest` 是否通过？
- `ruff check .` 是否通过？

## 下一阶段如何复用

Phase 6 会复用：

- broker adapter 接口
- order manager
- order lifecycle
- risk engine
- paper broker 的行为测试

未来接真实券商时，live broker adapter 必须遵守同样的订单入口和状态记录规则。
