import { OptionsRadarView } from "@/components/forms/OptionsRadarView";

type OptionsRadarPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function OptionsRadarPage({ searchParams }: OptionsRadarPageProps) {
  const params = (await searchParams) ?? {};
  const locale = params.lang === "zh" ? "zh" : "en";
  return <OptionsRadarView locale={locale} />;
}
