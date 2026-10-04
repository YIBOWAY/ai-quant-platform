import { StrategyLibraryPanel } from "@/components/research/StrategyLibraryPanel";
import { getServerLocale } from "@/lib/serverLocale";

export default async function StrategyLibraryPage() {
  const locale = await getServerLocale();
  return <main className="h-full min-h-0 overflow-y-auto bg-bg-base"><StrategyLibraryPanel locale={locale}/></main>;
}
