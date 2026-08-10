import { AsiaRadarView } from "@/components/asia-radar/AsiaRadarDashboard";
import { getServerLocale } from "@/lib/serverLocale";

type AsiaRadarPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function AsiaRadarPage({ searchParams }: AsiaRadarPageProps) {
  const params = (await searchParams) ?? {};
  const locale = await getServerLocale(params);
  return <AsiaRadarView locale={locale} />;
}

