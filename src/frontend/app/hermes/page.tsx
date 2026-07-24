import { Suspense } from "react";
import {
  HermesTodayOverviewSection,
  HermesTodaySecondarySection,
} from "./today-sections";
import {
  TodayOverviewSkeleton,
  TodaySecondarySkeleton,
} from "@/components/hermes/today";
import { getServerLocale } from "@/lib/serverLocale";

export default async function HermesWorkbenchPage() {
  const locale = await getServerLocale();

  return (
    <div className="flex flex-col gap-5 sm:gap-6">
      <Suspense fallback={<TodayOverviewSkeleton locale={locale} />}>
        <HermesTodayOverviewSection locale={locale} />
      </Suspense>
      <Suspense fallback={<TodaySecondarySkeleton locale={locale} />}>
        <HermesTodaySecondarySection locale={locale} />
      </Suspense>
    </div>
  );
}
