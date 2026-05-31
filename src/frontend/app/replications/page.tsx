import { ReversalMomentumReplicationForm } from "@/components/forms/ReversalMomentumReplicationForm";
import { getServerLocale } from "@/lib/serverLocale";

export default async function ReplicationsPage() {
  const locale = await getServerLocale();
  return <ReversalMomentumReplicationForm locale={locale} />;
}
