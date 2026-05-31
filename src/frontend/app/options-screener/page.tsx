import { OptionsScreenerForm } from "@/components/forms/OptionsScreenerForm";
import { getServerLocale } from "@/lib/serverLocale";

type OptionsScreenerPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function OptionsScreenerPage({ searchParams }: OptionsScreenerPageProps) {
  const params = (await searchParams) ?? {};
  const locale = await getServerLocale(params);

  return <OptionsScreenerForm locale={locale} />;
}
