import { redirect } from "next/navigation";
import { LegacyDashboard } from "@/components/dashboard/LegacyDashboard";
import { hermesFeatureFlags } from "@/lib/hermes/featureFlags";
import {
  hermesHomeHref,
  type HermesSearchParams,
} from "@/lib/hermes/routes";
import { getServerLocale } from "@/lib/serverLocale";

type HomePageProps = {
  searchParams: Promise<HermesSearchParams>;
};

export default async function HomePage({ searchParams }: HomePageProps) {
  if (!hermesFeatureFlags().shell) {
    return <LegacyDashboard />;
  }
  const resolvedSearchParams = await searchParams;
  const locale = await getServerLocale(resolvedSearchParams);
  redirect(hermesHomeHref(locale, resolvedSearchParams));
}
