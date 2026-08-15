import type { Metadata } from "next";
import { HermesWorkbenchShell } from "@/components/hermes/shell/HermesWorkbenchShell";
import { getHermesGatewayStatus } from "@/lib/api";
import {
  hermesChatAdmission,
  hermesFeatureFlags,
} from "@/lib/hermes/featureFlags";
import { getServerLocale } from "@/lib/serverLocale";

export const metadata: Metadata = {
  title: "值班 · 研究 · 模拟 · Hermes",
  description: "个人量化助手工作台：值班、研究、模拟三本账，接线远程账。",
};

export default async function HermesLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const locale = await getServerLocale();
  const flags = hermesFeatureFlags();
  const gateway = await getHermesGatewayStatus();
  const chatWriteReady = Boolean(gateway.chat_write_ready);
  const deliveryState = hermesChatAdmission(
    flags,
    chatWriteReady,
  ).deliveryState;

  return (
    <HermesWorkbenchShell
      chatWriteReady={chatWriteReady}
      deliveryState={deliveryState}
      locale={locale}
    >
      {children}
    </HermesWorkbenchShell>
  );
}
