import type { Locale } from "@/lib/locale";
import type { HermesDeliveryState } from "./types";

export type HermesWorkbenchCopy = {
  nav: {
    landmark: string;
    today: string;
    sessions: string;
    tasks: string;
    approvals: string;
    results: string;
  };
  capability: {
    blocked_in_this_slice: {
      title: string;
      body: string;
    };
    local_mutation_authorized: {
      title: string;
      body: string;
    };
  };
  labels: {
    researchApproval: string;
    marketPrediction: string;
    automationHealthy: string;
    automationAttention: string;
    automationUnavailable: string;
    technicalDetails: string;
    attention: string;
    hqaConclusions: string;
    unifiedResults: string;
    unifiedResultsEmpty: string;
    unifiedResultsUnavailable: string;
    unifiedResultsDegraded: string;
    unifiedResultsIndependentTruth: string;
    viewUnifiedResults: string;
    openMorningBrief: string;
    openMorningBriefAria: string;
  };
  states: {
    empty: string;
    normal: string;
    degraded: string;
    offline: string;
  };
  composer: {
    label: string;
    placeholder: string;
    /** Placeholder when local chat unlock is on (L2a network path). */
    placeholderOpen: string;
    unavailable: string;
    sendDisabled: string;
    sendEnabled: string;
    retrySame: string;
  };
  /** UI-1 Direction A today-page copy. */
  today: {
    greeting: {
      morning: string;
      afternoon: string;
      evening: string;
    };
    summary: {
      allClear: string;
      normalWithAttention: (count: number) => string;
      attentionClause: (count: number) => string;
      degradedPrefix: string;
      degradedAllClear: string;
      offline: string;
      empty: string;
    };
    status: {
      hermesOnline: string;
      hermesDegraded: string;
      hermesOffline: string;
      sourcesLabel: string;
      sourcesAll: string;
      sourcesPartial: string;
      sourcesUnavailable: string;
      sourcesEmpty: string;
      automationLabel: string;
      automationUnavailable: string;
      ledgerLabel: string;
      ledgerOk: string;
      ledgerAttention: string;
      ledgerUnknown: string;
      systemStatusLink: string;
      systemStatusAria: string;
    };
    attention: {
      title: string;
      gate2Tag: string;
      approvalOnceTag: string;
      review: string;
      viewAutomation: string;
      openTasks: string;
      approvalTitle: string;
      approvalDesc: string;
      expiresPrefix: string;
      allowOnce: string;
      deny: string;
      submitting: string;
      candidateFeedUnavailable: string;
    };
    running: {
      title: string;
      viewAll: string;
      waitingReceipt: string;
      attempts: (count: number) => string;
      startedPrefix: string;
    };
    results: {
      title: string;
      viewAll: string;
      delayed: string;
      unavailable: string;
      independentFeedNote: string;
      empty: string;
    };
    automation: {
      title: string;
      lastSuccessPrefix: string;
      lastSuccessNever: string;
    };
  };
};

const en: HermesWorkbenchCopy = {
  nav: {
    landmark: "Hermes workbench",
    today: "Today",
    sessions: "Sessions",
    tasks: "Tasks",
    approvals: "Approvals",
    results: "Results",
  },
  capability: {
    blocked_in_this_slice: {
      title: "Hermes chat is currently unavailable",
      body: "The composer is locked because this installation has not passed its current write admission. Read-only sessions and results remain available; the composer opens automatically when admission is ready.",
    },
    local_mutation_authorized: {
      title: "Hermes chat is ready",
      body: "This installation may submit through the managed Hermes Session path (owner cookie + CSRF + submit-turn). Trading remains constrained by kill_switch, paper, and dry_run.",
    },
  },
  labels: {
    researchApproval: "Research approval item",
    marketPrediction: "Market prediction proposals",
    automationHealthy: "Automation healthy",
    automationAttention: "Automation needs attention",
    automationUnavailable: "Automation source unavailable",
    technicalDetails: "Technical details",
    attention: "Needs attention",
    hqaConclusions: "HQA conclusion artifacts",
    unifiedResults: "Recent platform / unified results",
    unifiedResultsEmpty: "No platform or unified results have been recorded yet.",
    unifiedResultsUnavailable: "Unified result status is unknown",
    unifiedResultsDegraded: "The unified result catalog is degraded; shown items remain read-only.",
    unifiedResultsIndependentTruth:
      "HQA conclusion artifacts below remain available from their independent read-only feed.",
    viewUnifiedResults: "View unified results",
    openMorningBrief: "Morning Brief",
    openMorningBriefAria: "Open morning brief",
  },
  states: {
    empty: "No research activity yet",
    normal: "Research posture is healthy",
    degraded: "Research posture is degraded",
    offline: "Hermes artifact sources unavailable",
  },
  composer: {
    label: "Talk with Hermes",
    placeholder: "Hermes chat is currently unavailable",
    placeholderOpen: "Message Hermes… (16 KiB max)",
    unavailable: "The composer cannot submit while write admission is closed",
    sendDisabled: "Send (disabled)",
    sendEnabled: "Send",
    retrySame: "Retry same send",
  },
  today: {
    greeting: {
      morning: "Good morning",
      afternoon: "Good afternoon",
      evening: "Good evening",
    },
    summary: {
      allClear: "All clear — nothing needs your attention",
      normalWithAttention: (count) =>
        `Systems normal — ${count} item${count === 1 ? "" : "s"} need your attention`,
      attentionClause: (count) =>
        `${count} item${count === 1 ? "" : "s"} need your attention`,
      degradedPrefix: "Systems partially degraded",
      degradedAllClear: "Systems partially degraded",
      offline: "Hermes data sources are offline; rendering degraded read-only state",
      empty: "No research activity yet today",
    },
    status: {
      hermesOnline: "Hermes on duty",
      hermesDegraded: "Hermes on duty (degraded)",
      hermesOffline: "Hermes off duty",
      sourcesLabel: "Sources",
      sourcesAll: "all healthy",
      sourcesPartial: "partially degraded",
      sourcesUnavailable: "unavailable",
      sourcesEmpty: "no sources",
      automationLabel: "Automation",
      automationUnavailable: "unavailable",
      ledgerLabel: "Database",
      ledgerOk: "healthy",
      ledgerAttention: "attention",
      ledgerUnknown: "unknown",
      systemStatusLink: "System status →",
      systemStatusAria: "Open technical system status details",
    },
    attention: {
      title: "Needs your action",
      gate2Tag: "Gate 2",
      approvalOnceTag: "Approval · one-shot",
      review: "Review",
      viewAutomation: "View automation",
      openTasks: "Open tasks",
      approvalTitle: "Hermes requests a one-shot execution approval",
      approvalDesc:
        "A bounded call runs only after your confirmation; nothing is auto-approved.",
      expiresPrefix: "valid until",
      allowOnce: "Allow once",
      deny: "Deny",
      submitting: "Submitting…",
      candidateFeedUnavailable: "Candidate source unavailable",
    },
    running: {
      title: "Running",
      viewAll: "All tasks →",
      waitingReceipt: "Delivered — waiting for the Hermes receipt",
      attempts: (count) => `attempt ${count}`,
      startedPrefix: "started",
    },
    results: {
      title: "Recent results",
      viewAll: "View all →",
      delayed: "may be delayed",
      unavailable: "The result catalog is currently unavailable",
      independentFeedNote:
        "Entries below come from the independent read-only artifact feed.",
      empty: "No new research results yet today.",
    },
    automation: {
      title: "Automation",
      lastSuccessPrefix: "last success",
      lastSuccessNever: "no successful run yet",
    },
  },
};

const zh: HermesWorkbenchCopy = {
  nav: {
    landmark: "Hermes 工作台",
    today: "今日",
    sessions: "会话记录",
    tasks: "任务",
    approvals: "审批",
    results: "结果",
  },
  capability: {
    blocked_in_this_slice: {
      title: "Hermes 对话当前不可用",
      body: "当前安装尚未通过写入准入，因此撰写区保持锁定。只读会话和结果仍可使用；准入就绪后撰写区会自动开放。",
    },
    local_mutation_authorized: {
      title: "Hermes 对话已就绪",
      body: "当前安装可通过受管 Hermes Session 路径提交（owner cookie + CSRF + submit-turn）。交易仍受 kill_switch、paper 和 dry_run 约束。",
    },
  },
  labels: {
    researchApproval: "研究审批项",
    marketPrediction: "市场预测提案",
    automationHealthy: "自动化正常",
    automationAttention: "自动化需要关注",
    automationUnavailable: "自动化源不可用",
    technicalDetails: "技术细节",
    attention: "需要关注",
    hqaConclusions: "HQA 结论产物",
    unifiedResults: "最近平台 / 统一结果",
    unifiedResultsEmpty: "尚未记录平台或统一结果。",
    unifiedResultsUnavailable: "统一结果状态未知",
    unifiedResultsDegraded: "统一结果目录已降级；当前条目仍为只读。",
    unifiedResultsIndependentTruth: "下方 HQA 结论产物仍以独立只读源为准。",
    viewUnifiedResults: "查看统一结果",
    openMorningBrief: "每日晨报",
    openMorningBriefAria: "打开每日晨报",
  },
  states: {
    empty: "今日尚无研究活动",
    normal: "研究态势正常",
    degraded: "研究态势已降级",
    offline: "Hermes 产物源不可用",
  },
  composer: {
    label: "和 Hermes 对话",
    placeholder: "Hermes 对话当前不可用",
    placeholderOpen: "给 Hermes 发消息…（上限 16 KiB）",
    unavailable: "写入准入关闭时，撰写区不能提交研究任务",
    sendDisabled: "发送（已禁用）",
    sendEnabled: "发送",
    retrySame: "重试同一次发送",
  },
  today: {
    greeting: {
      morning: "早上好",
      afternoon: "下午好",
      evening: "晚上好",
    },
    summary: {
      allClear: "一切正常，没有需要你处理的事",
      normalWithAttention: (count) => `系统正常，有 ${count} 件事需要你处理`,
      attentionClause: (count) => `有 ${count} 件事需要你处理`,
      degradedPrefix: "系统部分降级",
      degradedAllClear: "系统部分降级",
      offline: "Hermes 数据源离线，以下为降级只读呈现",
      empty: "今天还没有研究活动",
    },
    status: {
      hermesOnline: "Hermes 正在值班",
      hermesDegraded: "Hermes 值班中（部分降级）",
      hermesOffline: "Hermes 暂时离岗",
      sourcesLabel: "数据源",
      sourcesAll: "全部正常",
      sourcesPartial: "部分降级",
      sourcesUnavailable: "不可用",
      sourcesEmpty: "无数据源",
      automationLabel: "自动化",
      automationUnavailable: "不可用",
      ledgerLabel: "数据库",
      ledgerOk: "正常",
      ledgerAttention: "异常",
      ledgerUnknown: "未知",
      systemStatusLink: "系统状态 →",
      systemStatusAria: "打开系统技术状态详情",
    },
    attention: {
      title: "待我处理",
      gate2Tag: "Gate 2",
      approvalOnceTag: "审批 · 单次",
      review: "去评审",
      viewAutomation: "查看自动化",
      openTasks: "打开任务页",
      approvalTitle: "Hermes 请求一次执行授权",
      approvalDesc: "一次受限调用经你确认后才会执行；不会自动放行。",
      expiresPrefix: "有效至",
      allowOnce: "允许一次",
      deny: "拒绝",
      submitting: "提交中…",
      candidateFeedUnavailable: "候选源不可用",
    },
    running: {
      title: "运行中",
      viewAll: "全部任务 →",
      waitingReceipt: "已送达，等待 Hermes 回执",
      attempts: (count) => `第 ${count} 次尝试`,
      startedPrefix: "开始于",
    },
    results: {
      title: "最近结果",
      viewAll: "查看全部 →",
      delayed: "可能延迟",
      unavailable: "结果目录当前不可用",
      independentFeedNote: "以下条目来自独立的只读产物 feed。",
      empty: "今天还没有新的研究结果。",
    },
    automation: {
      title: "自动化",
      lastSuccessPrefix: "上次成功",
      lastSuccessNever: "尚无成功运行",
    },
  },
};

const byLocale: Record<Locale, HermesWorkbenchCopy> = { en, zh };

export function hermesWorkbenchCopy(locale: Locale): HermesWorkbenchCopy {
  return byLocale[locale] ?? en;
}

export function hermesCapabilityCopy(
  locale: Locale,
  deliveryState: HermesDeliveryState,
): { title: string; body: string } {
  return hermesWorkbenchCopy(locale).capability[deliveryState];
}

/**
 * UI-1 Direction A: command kind → human title dictionary. Unknown kinds
 * pass through unchanged so the event stream never invents a label.
 */
export function hermesCommandKindTitle(
  kind: string | null | undefined,
  locale: Locale,
): string {
  const key = (kind ?? "").trim();
  const zh: Record<string, string> = {
    "conversation.turn": "Hermes 对话任务",
  };
  const enMap: Record<string, string> = {
    "conversation.turn": "Hermes conversation turn",
  };
  const table = locale === "zh" ? zh : enMap;
  return table[key] ?? key;
}
