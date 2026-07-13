import { HermesWorkbenchShell } from "@/components/hermes/shell/HermesWorkbenchShell";
import { getServerLocale } from "@/lib/serverLocale";

export default async function HermesLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const locale = await getServerLocale();

  return (
    <HermesWorkbenchShell deliveryState="blocked_in_this_slice" locale={locale}>
      {children}
    </HermesWorkbenchShell>
  );
}
