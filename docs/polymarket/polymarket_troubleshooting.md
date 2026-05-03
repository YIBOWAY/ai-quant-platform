# Polymarket 故障排查

## 1. `provider_timeout`

公开接口在超时前没有返回。

处理办法：

- 先用 `provider=sample`
- 降低 `limit`
- 稍后重试

---

## 2. `provider_invalid_response`

公开接口返回结构变了，或者缺了关键字段。

处理办法：

- 先跑本地测试
- 再手动确认公开接口返回
- 不要直接改解析逻辑赌运气

---

## 3. `Credential-like fields are not accepted`

请求里带了不允许的凭据字段。

处理办法：

- 删除 `polymarket_api_key`
- 删除任何带 `key / secret / token / password / private` 的字段

---

## 4. `no historical prediction-market snapshots matched the requested range`

意思是：你给的时间区间内，本地没有历史快照。

处理办法：

1. 先跑一次 collect
2. 或者把开始结束时间留空，先用当前已有样本跑
3. 或者检查历史目录是否真的写进去了数据

---

## 5. 前端点了历史回放没结果

先查三件事：

1. 采集有没有成功
2. 回放时间区间和采集时间是不是对得上
3. 页面返回的是 404 还是 400

如果你刚采完样本，最稳的做法是让页面直接用采集返回的时间范围。

---

## 6. 真实 Polymarket 采集拿不到数据

这通常不是代码没写，而是公开接口本身波动、超时或者临时拒绝。

处理办法：

- 先确认 sample 能跑通
- 再做短窗口真实采集
- 保留本地历史缓存，避免每次都从零开始

---

## 7. 页面看起来像是真交易

如果你担心界面文案误导，检查页面上是否还保留这些提醒：

- read-only
- simulated
- no real fills
- no live trading

如果少了其中任何一条，都应该补回去
