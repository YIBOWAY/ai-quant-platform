import { LibraryWorkbench } from "@/components/library/LibraryWorkbench";
import { PageHeader } from "@/components/ui/primitives";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    eyebrow: "Verified research",
    title: "Candidate Library",
    subtitle:
      "Only research-verified candidates not yet enabled for simulated running appear here. Enabling simulated running remains bound to the exact source fingerprint.",
  },
  zh: {
    eyebrow: "已验证研究",
    title: "候选库",
    subtitle: "这里只展示尚未启用模拟运行的已验证候选。技术身份会继续用精确来源指纹校验。",
  },
} as const;

export default async function LibraryPage({ searchParams }: { searchParams?: Promise<Record<string, string | string[] | undefined>> }) {
  const params = (await searchParams) ?? {};
  const locale = await getServerLocale();
  const text = copy[locale];

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-bg-base">
      <section className="flex w-full flex-col gap-4 p-4 lg:p-6">
        <PageHeader eyebrow={text.eyebrow} subtitle={text.subtitle} title={text.title} />
        <LibraryWorkbench locale={locale} initialCandidate={typeof params.candidate === "string" ? params.candidate : undefined} />
      </section>
    </div>
  );
}
