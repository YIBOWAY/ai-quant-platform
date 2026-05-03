# Polymarket 历史快照采集说明

## 1. 这份文档讲什么

这份文档只讲一件事：

如何把 Polymarket 的公开只读数据持续采下来，并存成本地可回放的历史样本。

---

## 2. 安全边界

采集器只有只读能力：

- 只调用公开 GET 接口
- 不接钱包
- 不接私钥
- 不签名
- 不下单

如果环境里出现疑似 Polymarket 凭据变量，采集器会直接拒绝启动。

---

## 3. 落盘结构

```text
data/prediction_market/history/
  date=YYYY-MM-DD/
    market_id=<market_id>/
      market.json
      token_id=<token_id>.jsonl
```

说明：

- `market.json` 保存市场级信息
- `token_id=...jsonl` 追加保存每个 token 的时间快照

---

## 4. 一次性采集

```powershell
conda activate ai-quant
quant-system prediction-market collect --provider sample --duration 0 --limit 10
```

适合：

- 本地联调
- 验证路径和写盘逻辑

---

## 5. 短窗口真实采集

```powershell
conda activate ai-quant
quant-system prediction-market collect --provider polymarket --duration 0 --limit 5
```

如果你想短时间多轮采集：

```powershell
conda activate ai-quant
quant-system prediction-market collect --provider polymarket --duration 60 --interval 15 --limit 5
```

---

## 6. 断点续采

这套目录是追加写入：

- 同一天会继续追加到已有文件
- 新的一天会自动写到新的 `date=...` 分区

所以中断后直接重跑即可，不需要先清空。

---

## 7. 清理策略

如果你只是本地试验：

- 直接删掉整个 `history/` 目录即可重置

如果你要保留研究样本：

- 优先按 `date=...` 分区删旧数据
- 不建议零散删除单个 token 文件

---

## 8. 推荐使用顺序

1. 先用 sample 跑通
2. 再用 polymarket 做短窗口采集
3. 采完立刻跑一次时间回放
4. 再看图和报告

---

## 9. 常见问题

### 为什么采集成功了，但没有“收益”结果

因为采集只负责抓数据，不负责回放。

### 为什么采集比较慢

因为它要遵守公开接口的限速、重试和超时设置。

### 为什么文件是按 token 分开的

因为回放时需要按市场重组，但采集时按 token 追加写入更稳，也更容易保留完整深度。
