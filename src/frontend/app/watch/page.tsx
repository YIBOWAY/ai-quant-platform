import { WatchMonitor } from "@/components/watch/WatchMonitor";
import { getServerLocale } from "@/lib/serverLocale";

type WatchPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function WatchPage({ searchParams }: WatchPageProps) {
  const params = (await searchParams) ?? {};
  const locale = await getServerLocale(params);
  return <WatchMonitor locale={locale} params={params} />;
}
