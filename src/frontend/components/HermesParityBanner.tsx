import type { Locale } from "@/lib/locale";
import { hermesHomeHref } from "@/lib/hermes/routes";

const copy = {
  en: {
    body: "The Hermes workbench is the default research entry; this page still keeps full capability. Merge/redirect is not complete and does not mean this page is retired.",
    link: "Open Hermes workbench",
  },
  zh: {
    body: "Hermes 工作台是默认研究入口；本页仍保留完整能力。合并/redirect 未完成，不代表本页已退役。",
    link: "打开 Hermes 工作台",
  },
} as const;

export type HermesParityBannerProps = {
  locale: Locale;
};

/**
 * Soft honesty notice on legacy research pages.
 * Not dismissible; does not redirect or retire page capability.
 */
export function HermesParityBanner({ locale }: HermesParityBannerProps) {
  const text = copy[locale];

  return (
    <div
      role="status"
      data-testid="hermes-parity-banner"
      className="rounded-lg border border-info/40 bg-info/10 px-3 py-2 font-body-sm text-info"
    >
      <p>{text.body}</p>
      <a
        href={hermesHomeHref(locale, {})}
        className="mt-1 inline-flex font-semibold text-info underline underline-offset-2 hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
      >
        {text.link}
      </a>
    </div>
  );
}
