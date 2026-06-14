type ErrorBannerProps = {
  messages: Array<string | undefined>;
  locale?: "en" | "zh";
};

export function ErrorBanner({ messages, locale = "en" }: ErrorBannerProps) {
  const activeMessages = messages.filter(Boolean);
  if (activeMessages.length === 0) {
    return null;
  }
  const prefix = locale === "zh" ? "后端异常：" : "Backend issue: ";

  return (
    <div className="rounded-lg border border-danger/40 bg-danger/10 p-3 font-body-sm text-danger">
      {prefix}
      {activeMessages.join(" · ")}
    </div>
  );
}
