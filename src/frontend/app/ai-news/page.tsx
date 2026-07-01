import { AiNewsView } from "@/components/forms/AiNewsView";
import { getServerLocale } from "@/lib/serverLocale";

type AiNewsPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function AiNewsPage({ searchParams }: AiNewsPageProps) {
  const params = (await searchParams) ?? {};
  const locale = await getServerLocale(params);
  return <AiNewsView locale={locale} />;
}
