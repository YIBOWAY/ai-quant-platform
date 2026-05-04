import { BuySideOptionsAssistant } from "@/components/forms/BuySideOptionsAssistant";

type BuySideOptionsPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function BuySideOptionsPage({ searchParams }: BuySideOptionsPageProps) {
  const params = (await searchParams) ?? {};
  const locale = params.lang === "zh" ? "zh" : "en";

  return <BuySideOptionsAssistant locale={locale} />;
}
