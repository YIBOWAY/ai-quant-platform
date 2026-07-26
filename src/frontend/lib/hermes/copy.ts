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
