import { OptionsToolsWorkbench } from "@/components/forms/OptionsToolsWorkbench";
import { getServerLocale } from "@/lib/serverLocale";

type OptionsToolsPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function OptionsToolsPage({ searchParams }: OptionsToolsPageProps) {
  const params = (await searchParams) ?? {};
  const locale = await getServerLocale(params);

  return <OptionsToolsWorkbench locale={locale} />;
}
