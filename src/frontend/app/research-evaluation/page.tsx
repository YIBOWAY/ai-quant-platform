import { ResearchEvaluationView } from "@/components/research/ResearchEvaluationView";
import { getServerLocale } from "@/lib/serverLocale";

export default async function ResearchEvaluationPage({ searchParams }: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = (await searchParams) ?? {};
  const locale = await getServerLocale(params);
  const key = typeof params.key === "string" && /^research:(?:artifact-[a-zA-Z0-9_-]+|strategy-[0-9a-f]{24})$/.test(params.key)
    ? params.key : null;
  const factor = typeof params.factor === "string" ? params.factor : undefined;
  const tab = typeof params.tab === "string" ? params.tab : undefined;
  return <main className="h-full min-h-0 overflow-y-auto bg-bg-base">
    <ResearchEvaluationView locale={locale} researchKey={key} initialFactor={factor} initialTab={tab}/>
  </main>;
}
