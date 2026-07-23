import { HermesWorkbenchShell } from "@/components/hermes/shell/HermesWorkbenchShell";
import { getHermesGatewayStatus } from "@/lib/api";
import {
  hermesChatAdmission,
  hermesFeatureFlags,
} from "@/lib/hermes/featureFlags";
import { getServerLocale } from "@/lib/serverLocale";

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
