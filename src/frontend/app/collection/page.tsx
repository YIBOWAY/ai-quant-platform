import { ErrorBanner } from "@/components/ErrorBanner";
import { CollectionWorkbench } from "@/components/collection/CollectionWorkbench";
import { getCollectionCatalog } from "@/lib/api";
import { getServerLocale } from "@/lib/serverLocale";

export default async function CollectionPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = (await searchParams) ?? {};
  const locale = await getServerLocale();
  const data = await getCollectionCatalog();
  return (
    <main className="h-full min-h-0 overflow-y-auto bg-bg-base">
      <ErrorBanner
        locale={locale}
        messages={[data.apiError, ...(data.errors ?? [])]}
      />
      <CollectionWorkbench
        data={data}
        locale={locale}
        initialKey={typeof params.item === "string" ? params.item : undefined}
      />
    </main>
  );
}
