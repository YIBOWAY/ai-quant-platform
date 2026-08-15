import { redirect } from "next/navigation";
import { hermesHomeHref } from "@/lib/hermes/routes";
import { getServerLocale } from "@/lib/serverLocale";

export default async function DeskAliasPage() {
  const locale = await getServerLocale();
  redirect(hermesHomeHref(locale, {}));
}
