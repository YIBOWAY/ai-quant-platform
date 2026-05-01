type ErrorBannerProps = {
  messages: Array<string | undefined>;
};

export function ErrorBanner({ messages }: ErrorBannerProps) {
  const activeMessages = messages.filter(Boolean);
  if (activeMessages.length === 0) {
    return null;
  }

  return (
    <div className="rounded border border-danger/40 bg-danger/10 p-3 font-body-sm text-danger">
      Backend issue: {activeMessages.join(" · ")}
    </div>
  );
}
