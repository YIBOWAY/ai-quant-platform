import { BuySideOptionsAssistant } from "@/components/forms/BuySideOptionsAssistant";
import { getServerLocale } from "@/lib/serverLocale";

type BuySideOptionsPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function BuySideOptionsPage({ searchParams }: BuySideOptionsPageProps) {
  const params = (await searchParams) ?? {};
  const locale = await getServerLocale(params);

  return <BuySideOptionsAssistant locale={locale} />;
}
