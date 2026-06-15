# 短期反转与长期动量复现

本文档描述以下论文在本地平台上的复现：

Short-Term Reversals and Longer-Term Momentum around the World: Theory and
Evidence. DOI: `10.1093/rfs/hhaf057`。

用于实现评审的本地 PDF 文件为：

```text
C:\Users\86189\Desktop\Short-Term Reversals and Longer-Term Momentum around the world.pdf
```

## 平台实现了什么

所实现的工作流复现了论文核心的月度组合检验：

1. 从所选只读数据源拉取日频 OHLCV 数据。
2. 将日收盘价转换为月末收盘价。
3. 剔除上月末股价低于 `US$1` 的信号观测值。
4. 根据过去 1 个月的收益率计算短期反转信号。
5. 根据 `t-12` 到 `t-2` 月份计算长期动量信号。
6. 构建默认的十分位多空组合。
7. 衡量后续一个月的组合收益。

反转腿做多上月输家、做空上月赢家。动量腿做多 12-2 动量较高的标的，
做空 12-2 动量较低的标的。

UI 还会报告一个本地的复合策略，融合反转排名与动量排名。该复合策略
是平台为便于检视而提供的功能；论文的主要检验是分别研究反转腿与动量腿。

## 在哪里使用

前端：

```text
http://127.0.0.1:3001/replications
```

后端：

```http
POST /api/replications/reversal-momentum/run
GET  /api/replications/reversal-momentum/{run_id}
```

请求体示例：

```json
{
  "symbols": ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLV", "XLY", "XLP", "XLE"],
  "start": "2023-01-01",
  "end": "2026-05-22",
  "provider": "futu",
  "initial_cash": 1.0
}
```

运行响应会包含 `run_id`（形如 `replication-YYYYMMDDTHHMMSSZ-xxxxxxxx`）、
`paths` 和 `artifact_path`。后端会把结果保存到：

```text
data/api_runs/replications/<run_id>/metadata.json
data/api_runs/replications/<run_id>/result.json
```

前端运行完成后会显示 **Open replication / 打开复现**，进入：

```text
http://127.0.0.1:3001/replications/<run_id>
```

该详情页读取 `GET /api/replications/reversal-momentum/{run_id}`，并复用策略目录的
指标卡、权益曲线、方法学、诊断、月度收益和持仓表渲染。复现 run 目前不写入可选
PostgreSQL run index；文件目录和详情接口是事实来源。

## 数据说明

- 使用 `provider=futu` 获取本地真实的 Futu OpenD 数据。
- 仅在稳定的本地冒烟测试中使用 `provider=sample`。
- 论文采用广泛的全球股票池。小型 ETF 篮子对于验证平台流程很有用，
  但并非完整的学术复现。
- 本地实现大约需要 14 个月的月末收盘价，才能产生 12-2 动量信号。

## 当前范围限制

现已实现：

- 过去 1 个月反转信号。
- 过去 2 至 12 个月动量信号。
- 上月股价低于 `US$1` 的过滤。
- 默认十分位多空组合构建。
- 一个月持有期。
- 月度收益表、复合权益曲线、持仓与诊断信息。

尚未实现：

- 完整的逐国家全球股票池。
- NYSE 10% 规模分界点过滤。
- 盈余公告衰减检验。
- 机构持股与散户订单失衡检验。
- 完整的论文表格与跨国回归。

## 安全性

本复现仅用于研究。它会拉取市场数据并计算组合收益。它不会创建订单、
解锁账户、提交交易，也不会削弱平台仅纸面交易（paper-only）的安全设置。
