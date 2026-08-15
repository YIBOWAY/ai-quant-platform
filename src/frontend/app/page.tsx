import type { Metadata } from "next";
import { OfficialDesk } from "@/components/desk/OfficialDesk";
import { LegacyDashboard } from "@/components/dashboard/LegacyDashboard";
import { hermesFeatureFlags } from "@/lib/hermes/featureFlags";

export const metadata: Metadata = {
  title: "值班 · 研究 · 模拟 · 个人量化助手",
  description: "三本账桌面：值班、研究、模拟。接线远程账，不是预览假数据。",
};

export default function HomePage() {
  if (!hermesFeatureFlags().shell) {
    return <LegacyDashboard />;
  }
  return <OfficialDesk />;
}
