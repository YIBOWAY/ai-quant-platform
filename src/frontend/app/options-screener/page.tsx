import { OptionsScreenerForm } from "@/components/forms/OptionsScreenerForm";

type OptionsScreenerPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function OptionsScreenerPage({ searchParams }: OptionsScreenerPageProps) {
  const params = (await searchParams) ?? {};
  const locale = params.lang === "zh" ? "zh" : "en";

  return <OptionsScreenerForm locale={locale} />;
}
