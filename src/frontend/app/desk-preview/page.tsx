import type { Metadata } from "next";
import DeskPreview from "./DeskPreview";

export const metadata: Metadata = {
  title: "桌面打样 · 预览态 · Hermes 本地研究",
  description:
    "一次性视觉打样路由（现行计划 §9）：blotter 桌面 + 右栏 Hermes 会话。假数据，非真实账户。",
  robots: { index: false, follow: false },
};

export default function DeskPreviewPage() {
  return <DeskPreview />;
}
