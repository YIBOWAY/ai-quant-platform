/**
 * Desk-preview fixtures. 全部是预览态假数据，只为视觉打样服务：
 * 不代表任何真实账户、真实观察日或真实候选。禁止当「今日效果」引用。
 */

export type StrategyStatus = "hung" | "candidate" | "paused";

export type StrategyEvent = {
  time: string;
  label: string;
  detail?: string;
};

export type Strategy = {
  id: string;
  name: string;
  status: StrategyStatus;
  statusNote: string;
  artifact: string;
  sleeve?: string;
  digestVerified?: boolean;
  universe: string;
  /** 最近观察日的日收益（%）。未挂上/已暂停给空数组 = 诚实的「暂无」。 */
  obsDays: number[];
  todayPnlUsd: number | null;
  todayPnlPct: number | null;
  todayNote: string;
  events: StrategyEvent[];
};

export const STRATEGIES: Strategy[] = [
  {
    id: "sleeve-c42a91e",
    name: "横截面动量 Top-N",
    status: "hung",
    statusNote: "已挂上 · 观察中",
    artifact: "c42a91e",
    sleeve: "c42a91e",
    digestVerified: true,
    universe: "SPY · QQQ · IWM · DIA",
    obsDays: [0.42, -0.18, 0.77, 0.31, -0.09, 0.24, 0.31],
    todayPnlUsd: 312.4,
    todayPnlPct: 0.31,
    todayNote: "开盘再平衡 · 2 笔成交",
    events: [
      { time: "09:31", label: "开盘再平衡成交", detail: "买 QQQ 12 股 @ 448.12 · 卖 IWM 9 股 @ 224.05" },
      { time: "09:30", label: "信号生成", detail: "Top-3：QQQ · SPY · DIA" },
      { time: "08:45", label: "digest 校验通过", detail: "sleeve = candidate c42a91e ✓" },
    ],
  },
  {
    id: "sleeve-74bd109",
    name: "均值回归 Top-N",
    status: "hung",
    statusNote: "已挂上 · 观察中",
    artifact: "74bd109",
    sleeve: "74bd109",
    digestVerified: true,
    universe: "SPY · QQQ · IWM · DIA",
    obsDays: [-0.12, 0.2, -0.33, 0.15, 0.08, -0.21, -0.04],
    todayPnlUsd: -41.07,
    todayPnlPct: -0.04,
    todayNote: "今日无信号 · 持仓未动",
    events: [
      { time: "09:30", label: "信号生成", detail: "无换仓：偏离度未触发阈值" },
      { time: "08:45", label: "digest 校验通过", detail: "sleeve = candidate 74bd109 ✓" },
    ],
  },
  {
    id: "candidate-8f3c2a7",
    name: "20 日均线反转",
    status: "candidate",
    statusNote: "已验证候选 · 未挂上",
    artifact: "8f3c2a7",
    digestVerified: true,
    universe: "美股大盘 ETF ×4",
    obsDays: [],
    todayPnlUsd: null,
    todayPnlPct: null,
    todayNote: "双引擎已通过（08-12） · 等你决定",
    events: [
      { time: "08-12 22:41", label: "双引擎回测通过", detail: "平台引擎 + Qlib 对照差 < 1bp" },
      { time: "08-12 22:14", label: "研究任务 R-248 完成", detail: "源码 digest 8f3c2a7 已归档" },
    ],
  },
  {
    id: "sleeve-9d21f44",
    name: "低波动质量因子",
    status: "paused",
    statusNote: "已暂停 · 08-11 手动",
    artifact: "9d21f44",
    sleeve: "9d21f44",
    digestVerified: true,
    universe: "美股大盘 ETF ×4",
    obsDays: [0.05, -0.02, 0.11, -0.4, 0.02, 0.0, 0.0],
    todayPnlUsd: null,
    todayPnlPct: null,
    todayNote: "暂停中 · 不生成信号",
    events: [
      { time: "08-11 15:02", label: "手动暂停", detail: "回撤连续 3 日超阈值，等复盘" },
    ],
  },
];

export type LedgerEvent = {
  time: string;
  level: "成交" | "观察" | "研究" | "数据" | "摘要" | "系统";
  source: string;
  text: string;
  artifact?: string;
};

export const LEDGER_EVENTS: LedgerEvent[] = [
  { time: "09:31:12", level: "成交", source: "sleeve.c42a91e", text: "开盘再平衡：买 QQQ 12 股 @ 448.12，卖 IWM 9 股 @ 224.05", artifact: "c42a91e" },
  { time: "09:30:04", level: "系统", source: "orchestrator", text: "2 条已挂策略完成信号生成；候选与暂停仓不参与" },
  { time: "08:45:20", level: "系统", source: "authority", text: "digest 复核：2 条已挂仓源码摘要一致 ✓" },
  { time: "08:30:02", level: "数据", source: "futu", text: "行情通道恢复在线（昨夜 23:41 起中断 47 分钟）" },
  { time: "08:17:00", level: "摘要", source: "digest", text: "今日晨报已生成：观察 2 · 候选 1 · 待决定 1", artifact: "brief-0814" },
  { time: "08:03:11", level: "研究", source: "R-249", text: "论文复现任务已派出 · 默认停在已验证候选", artifact: "R-249" },
  { time: "08:01:47", level: "研究", source: "R-247", text: "财报动量假设：诚实失败——材料无法证伪化，未产生候选" },
  { time: "昨 16:00", level: "观察", source: "valuation", text: "观察日估值完成：横截面动量 +0.31% · 均值回归 −0.04%" },
];

export type ChatRole = "user" | "hermes";

export type ChatReceipt = {
  icon: "tool" | "dispatch" | "doc";
  title: string;
  status: "完成" | "已派出" | "已读取";
  sub?: string;
  time: string;
};

export type ChatMessage = {
  id: string;
  role: ChatRole;
  time: string;
  text?: string;
  attachment?: { name: string; size: string };
  receipts?: ChatReceipt[];
};

export const CHAT_OPENING: ChatMessage[] = [
  {
    id: "m1",
    role: "hermes",
    time: "08:02",
    text: "早上好。昨夜观察日已完成：横截面动量 +0.31%，均值回归 −0.04%。有 1 条已验证候选（20 日均线反转）等你决定是否挂上。",
  },
  { id: "m2", role: "user", time: "08:05", text: "均值回归昨晚为什么是负的？" },
  {
    id: "m3",
    role: "hermes",
    time: "08:05",
    text: "主因是 DIA 隔夜跳空 −0.6%，仓内其余持仓平淡；无异常成交。收据：观察日估值 obs-0813。",
    receipts: [
      { icon: "doc", title: "观察日估值 · obs-0813", status: "已读取", sub: "2 条已挂仓 · 无异常", time: "08:05" },
    ],
  },
  {
    id: "m4",
    role: "user",
    time: "08:06",
    text: "这篇复现一下",
    attachment: { name: "论文 · 20日反转说明.pdf", size: "243 KB" },
  },
  {
    id: "m5",
    role: "hermes",
    time: "08:06",
    receipts: [
      { icon: "tool", title: "读取材料 · 抽取可证伪公式", status: "完成", time: "08:06" },
      { icon: "dispatch", title: "研究任务 R-249 · 已派出", status: "已派出", sub: "默认停在已验证候选", time: "08:07" },
    ],
    text: "已派出 R-249。双引擎通过后会出现在候选列表，不会自动挂上。",
  },
];

export const PREVIEW_REPLY =
  "（预览态）这条会话还没有接线。正式版本里，这里是本地 owner 的受管 Hermes 会话流：自由输入、模型自选工具、事事有收据。";
