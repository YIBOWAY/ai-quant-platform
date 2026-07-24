import { HermesWorkbenchShell } from "@/components/hermes/shell/HermesWorkbenchShell";
import { hermesFeatureFlags } from "@/lib/hermes/featureFlags";
import { getServerLocale } from "@/lib/serverLocale";

export default async function HermesLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const locale = await getServerLocale();
  const deliveryState = hermesFeatureFlags().deliveryState;

  return (
    <HermesWorkbenchShell deliveryState={deliveryState} locale={locale}>
      {children}
    </HermesWorkbenchShell>
  );
}
