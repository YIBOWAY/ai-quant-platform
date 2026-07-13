import type { Locale } from "@/lib/locale";
import type { HermesDeliveryState } from "./types";

export type HermesWorkbenchCopy = {
  nav: {
    landmark: string;
    today: string;
    conversation: string;
    conversationUnavailable: string;
    tasks: string;
    approvals: string;
    results: string;
  };
  capability: {
    blocked_in_this_slice: {
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
    recentResults: string;
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
    unavailable: string;
    sendDisabled: string;
  };
};

const en: HermesWorkbenchCopy = {
  nav: {
    landmark: "Hermes workbench",
    today: "Today",
    conversation: "Conversation",
    conversationUnavailable: "Conversation unavailable in this delivery",
    tasks: "Tasks",
    approvals: "Approvals",
    results: "Results",
  },
  capability: {
    blocked_in_this_slice: {
      title: "Hermes write capabilities are not connected in this delivery",
      body: "Chat, execution, unified dynamic results, and legacy redirects stay off. This is a fixed delivery fact for this slice, not a live gateway probe.",
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
    recentResults: "Recent results",
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
    unavailable: "Composer cannot submit research tasks in this delivery",
    sendDisabled: "Send (disabled)",
  },
};

const zh: HermesWorkbenchCopy = {
  nav: {
    landmark: "Hermes 工作台",
    today: "今日",
    conversation: "对话",
    conversationUnavailable: "本交付未开放对话",
    tasks: "任务",
    approvals: "审批",
    results: "结果",
  },
  capability: {
    blocked_in_this_slice: {
      title: "本交付未连接 Hermes 写入能力",
      body: "对话、执行、统一动态结果与旧重定向保持关闭。这是本切片的固定交付事实，不是实时网关探测结果。",
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
    recentResults: "最近结果",
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
    unavailable: "本交付中撰写区不能提交研究任务",
    sendDisabled: "发送（已禁用）",
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
