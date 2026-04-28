# Phase 9 API Learning

## 核心概念

Phase 9 的 API 是“本地工具入口”，不是交易服务。它让前端可以读取数据、触发 sample 回测、查看 Agent 候选和 prediction market dry proposal。

## 为什么是薄包装

已有 Phase 1-8 已经有可测试的核心函数。API 只负责：

- 接收 HTTP 请求
- 调用已有函数
- 把结果整理成 JSON
- 追加安全状态

这样不会出现 CLI 和 API 各写一套逻辑、结果不一致的问题。

## 为什么不做后台任务

当前 sample 数据量小，回测和 paper trading 可以同步跑完。后台队列会引入更多状态、失败恢复和清理问题，Phase 9 不需要。

## 为什么不做 WebSocket

前端当前需要的是读结果和触发本地任务，不是实时盘口。Prediction market 真实 WebSocket 接入属于后续高级阶段。

## 为什么默认只绑定本机

这个工具没有登录系统，也不应该暴露给公网。默认 `127.0.0.1` 可以让浏览器前端访问，同时避免局域网或外部机器误触发本地任务。

## 常见错误

- 把 `/api/paper/run` 当成真实下单：错误，它只跑本地 paper broker。
- 给 prediction market API 传 Polymarket key：会被拒绝。
- 以为 Agent approve 会注册因子：错误，它只写 lock 文件。
- 公开绑定但没有环境确认：会被 CLI 拒绝。

## 自检清单

- `/api/health` 有 `safety`
- `/api/settings` 看不到明文 key
- `/api/orders/submit` 不存在
- Agent candidate 源码只读不执行
- Prediction market 只产生 proposal JSON
