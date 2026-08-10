import { MarketCrossSectionView } from "@/components/market-cross-section/MarketCrossSectionDashboard";
import { getServerLocale } from "@/lib/serverLocale";

type MarketCrossSectionPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function MarketCrossSectionPage({ searchParams }: MarketCrossSectionPageProps) {
  const params = (await searchParams) ?? {};
  const locale = await getServerLocale(params);
  return <MarketCrossSectionView locale={locale} />;
}
