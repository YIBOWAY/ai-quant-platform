# 前端双语 (English / 中文) 支持

前端内置全站级的英文 / 中文语言切换。顶部栏的单个开关即可翻转整个 UI，
且所选语言会在多次访问之间被记住。

> 更新于 2026-06-04。本文取代了此前仅依赖 cookie 的切换方案以及基于
> 查询参数的原型。所有主页面均已双语化，可通过 `/en/...` 或 `/zh/...`
> 路径打开。

## 如何使用

1. 在 `http://127.0.0.1:3001` 打开应用。
2. 点击顶部栏中的 **EN** 或 **中文**。
3. 浏览器会跳转到对应的本地化路径，例如
   `/en/options-radar` 或 `/zh/options-radar`。
4. 所选语言会被记住，供后续无前缀访问使用。

语言设置在当前页面路径下是全站级的。带语言前缀的 URL 是分享特定语言视图的
推荐方式。

## 工作原理

语言来源可以是语言路径前缀 (`/en` 或 `/zh`)、旧版的 `?lang=`
查询参数，或名为 `qs_lang` 的 cookie (`en` 或 `zh`，有效期 1 年，
`path=/`，`samesite=lax`)。服务端组件优先采用路径前缀，
其次是 `?lang=`，再次是 cookie，最后回退到英文。

| 文件 | 角色 |
|---|---|
| `src/frontend/lib/locale.ts` | `Locale` 类型、cookie 名称、`resolveLocale()`。 |
| `src/frontend/lib/serverLocale.ts` | 供服务端组件使用的 `getServerLocale()`。优先级：语言路径头 > `?lang` 覆盖 > cookie > `en`。 |
| `src/frontend/components/LocaleProvider.tsx` | 客户端上下文 + `useLocale()` hook，以根布局中解析出的服务端语言作为初始值。 |
| `src/frontend/components/LocaleToggle.tsx` | 顶部栏开关。设置 cookie 并导航至对应的 `/en/...` 或 `/zh/...` 路径。 |
| `src/frontend/middleware.ts` | 将带语言前缀的路径重写为既有的应用路由，并通过请求头传递语言信息。 |

页面文案存放在各组件自有的文案字典中：在模块级定义
`const copy = { en: { ... }, zh: { ... } }`，然后在组件内部使用
`const text = copy[locale]`。服务端页面调用 `getServerLocale()`，并将
`locale` 向下传递给客户端子组件，子组件各自维护自己的文案字典。

无前缀路径仍然可用。它们在存在已保存 cookie 时使用该 cookie，否则回退
到英文。内部链接和表单导航应当保留当前激活的语言；这包括回测和模拟交易的
运行详情链接、持仓地图的快捷入口、详情页的返回链接，以及预测市场的筛选
提交。

## 覆盖范围

共享框架 (侧边栏、顶部栏、安全提示条) 以及所有主页面及其表单均已翻译，
包括：仪表盘、数据浏览器、期权筛选器、期权雷达、期权工具、买方期权、
因子实验室、回测器、复现、实验、模拟交易、智能体工作室、订单簿、
持仓地图，以及设置。

少量底层表单校验消息和数据提供方枚举值 (例如 `futu` / `sample` /
`tiingo`) 按设计保留英文。

## 新手友好的提示

术语行话 (APR、IV、IV rank、delta、theta burn、IV crush、break-even、
net debit、spread、open interest、market regime 等) 通过
`src/frontend/components/InfoTip.tsx` 提供内联术语表提示。术语表为
双语，并跟随当前激活的语言。

## 安全文案

只读的安全提示信息被翻译而非移除。两种语言保持相同含义，例如：

```text
EN: Paper only · Live trading disabled · Kill switch on
ZH: 仅模拟 · 实盘交易已禁用 · 熔断开关 开
```

## 手动验证

```text
http://127.0.0.1:3001
```

检查项：

- 顶部栏开关在 `/en/...` 与 `/zh/...` 之间切换。
- 在导航到其他页面以及重新加载后，所选语言仍然保持。
- 直接访问 `/zh/options-radar` 和 `/en/options-radar` 渲染出
  预期的语言。
- 从 `/zh/backtest`、`/zh/paper-trading` 和 `/zh/position-map` 进入时，运行详情
  链接保留 `/zh/...` 前缀，且详情页的返回链接回到本地化的列表页。
- 在 `/zh/order-book` 上提交控件后，浏览器仍停留在
  `/zh/order-book?...`。
- 两种语言下布局均保持完整。
- 按钮仍然触发相同的后端调用。
- 安全文案在两种语言下均存在。
