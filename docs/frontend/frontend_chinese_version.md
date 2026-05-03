# Frontend Chinese Version

## Approach

The first Chinese version uses a lightweight query-parameter switch instead of a full i18n framework.

Supported pages:

- Market Data: `/data-explorer?lang=zh`
- Options Screener: `/options-screener?lang=zh`

English remains the default:

- `/data-explorer`
- `/options-screener`

This keeps business logic shared and avoids duplicating pages.

## Translated Areas

Market Data:

- 市场数据
- 数据源
- 股票代码
- 日期范围
- 周期
- 加载数据
- 历史 K 线
- 只读行情

Options Screener:

- 期权筛选器
- 卖出看跌
- 备兑看涨 / 卖出看涨
- 到期日
- 权利金
- 行权价
- 隐含波动率
- 历史波动率
- 趋势过滤
- 评级
- 只读研究模式
- 不会真实下单

## Why Not A Full i18n Framework Yet

The current frontend is local-first and small. A full i18n routing layer would add more structure than needed for the current scope.

If more pages need translation later, migrate to:

- shared dictionaries
- locale-aware routing
- language persistence in local storage

## Manual Verification

```text
http://127.0.0.1:3001/data-explorer?lang=zh
http://127.0.0.1:3001/options-screener?lang=zh
```

Check:

- Chinese labels render correctly.
- Layout remains the same.
- English pages still work.
- Buttons still trigger the same backend calls.

## Safety Copy

The Chinese UI keeps the same safety message:

```text
只读研究模式：不会真实下单，不会解锁账户，不会进行实盘交易。
```
