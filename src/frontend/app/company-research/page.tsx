import { CompanyResearchView } from "@/components/research/CompanyResearchView";
import { getServerLocale } from "@/lib/serverLocale";

export default async function CompanyResearchPage({ searchParams }: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = (await searchParams) ?? {};
  const locale = await getServerLocale(params);
  return <div className="h-full min-h-0 overflow-y-auto bg-bg-base">
    <CompanyResearchView locale={locale} initialSymbol={typeof params.symbol === "string" ? params.symbol : ""}
      initialTab={typeof params.tab === "string" ? params.tab : undefined} />
  </div>;
}
