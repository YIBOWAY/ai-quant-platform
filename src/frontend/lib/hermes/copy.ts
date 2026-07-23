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
      title: "Hermes write capabilities are not connected in this delivery",
      body: "Chat, execution, full unified-results cutover, and legacy redirects stay off. This is a fixed delivery fact for this slice, not a live gateway probe.",
    },
    local_mutation_authorized: {
      title: "Local mutation path is authorized on this install",
      body: "Composer can submit on the single-user loopback path via L2a-Send (owner cookie + CSRF + submit-turn). Live trading stays behind kill_switch/paper/dry_run. Public chat write cutover remains closed.",
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
    placeholder: "Hermes write capability is not connected in this delivery",
    placeholderOpen: "Message Hermes… (local dark; 16 KiB max)",
    unavailable: "Composer cannot submit research tasks in this delivery",
    sendDisabled: "Send (disabled)",
    sendEnabled: "Send",
    retrySame: "Retry same send",
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
      title: "本交付未连接 Hermes 写入能力",
      body: "对话、执行、完整统一结果切换与旧重定向保持关闭。这是本切片的固定交付事实，不是实时网关探测结果。",
    },
    local_mutation_authorized: {
      title: "本机已授权本地 mutation 路径",
      body: "单用户 loopback 下撰写区可通过 L2a-Send 提交（owner cookie + CSRF + submit-turn）。实盘交易仍受 kill_switch / paper / dry_run 约束。公开 chat 写入切换仍关闭。",
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
    placeholder: "真实 Hermes 写入能力尚未通过",
    placeholderOpen: "给 Hermes 发消息…（本机 dark；上限 16 KiB）",
    unavailable: "本交付中撰写区不能提交研究任务",
    sendDisabled: "发送（已禁用）",
    sendEnabled: "发送",
    retrySame: "重试同一次发送",
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
