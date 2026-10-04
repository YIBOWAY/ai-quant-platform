import type { Metadata } from "next";
import { HermesWorkbenchShell } from "@/components/hermes/shell/HermesWorkbenchShell";
import { getHermesGatewayStatus } from "@/lib/api";
import {
  hermesChatAdmission,
  hermesFeatureFlags,
} from "@/lib/hermes/featureFlags";
import { getServerLocale } from "@/lib/serverLocale";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getServerLocale();
  if (locale === "zh") {
    return {
      title: "今日 · 研究 · 模拟 · Hermes 助手",
      description: "个人量化助手：今日、研究、模拟三本账，接线远程账。",
    };
  }
  return {
    title: "Today · Research · Paper · Hermes Assistant",
    description:
      "Personal quant assistant: today, research, and paper ledgers wired to the remote book.",
  };
}

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
      sessionReadReady={gateway.connected === true && gateway.session_api_available === true && gateway.read_status === "available"}
      deliveryState={deliveryState}
      locale={locale}
    >
      {children}
    </HermesWorkbenchShell>
  );
}
