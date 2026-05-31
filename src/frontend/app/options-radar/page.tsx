import { OptionsRadarView } from "@/components/forms/OptionsRadarView";
import { getServerLocale } from "@/lib/serverLocale";

type OptionsRadarPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function OptionsRadarPage({ searchParams }: OptionsRadarPageProps) {
  const params = (await searchParams) ?? {};
  const locale = await getServerLocale(params);
  const initialDate = single(params.date);
  return <OptionsRadarView initialDate={initialDate} locale={locale} />;
}

function single(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value ?? "";
}
