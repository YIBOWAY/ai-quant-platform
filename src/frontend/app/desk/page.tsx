import type { Metadata } from "next";
import { OfficialDesk } from "@/components/desk/OfficialDesk";

export const metadata: Metadata = {
  title: "值班 · 研究 · 模拟 · 个人量化助手",
  description: "正式桌面，接线远程账。",
};

export default function OfficialDeskPage() {
  return <OfficialDesk />;
}
