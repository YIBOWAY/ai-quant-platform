import {
  MarketCrossSectionView,
  type MarketCrossSectionBasket,
} from "@/components/market-cross-section/MarketCrossSectionDashboard";
import { getServerLocale } from "@/lib/serverLocale";

const VALID_BASKETS: ReadonlySet<string> = new Set(["ai_watch", "us_sectors"]);

type MarketCrossSectionPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function MarketCrossSectionPage({ searchParams }: MarketCrossSectionPageProps) {
  const params = (await searchParams) ?? {};
  const locale = await getServerLocale(params);
  // Deep link: ?basket=us_sectors seeds the initial basket; unknown values
  // fall back to the default basket. Used only as the useState initial value,
  // so it does not trigger an extra request.
  const rawBasket = params.basket;
  const candidate = Array.isArray(rawBasket) ? rawBasket[0] : rawBasket;
  const initialBasket: MarketCrossSectionBasket | undefined =
    candidate && VALID_BASKETS.has(candidate)
      ? (candidate as MarketCrossSectionBasket)
      : undefined;
  return <MarketCrossSectionView initialBasket={initialBasket} locale={locale} />;
}
