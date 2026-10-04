type ErrorBannerProps = {
  messages: Array<string | undefined>;
  locale?: "en" | "zh";
};

export function ErrorBanner({ messages, locale = "en" }: ErrorBannerProps) {
  const activeMessages = [...new Set(messages.filter((message): message is string => Boolean(message?.trim())))];
  if (activeMessages.length === 0) {
    return null;
  }
  const networkIssue = activeMessages.some(message => /provider_unavailable|opend_unavailable|network|网络中断|ECONN|timeout/i.test(message));

  return (
    <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 p-3 font-body-sm text-danger">
      <p>{locale === "zh"
        ? networkIssue ? "部分数据连接暂时中断，已取得的内容仍会显示；请留意各项数据的时间和缺失提示。" : "部分资料暂时无法读取，当前页面可能不完整。具体原因可在下方查看。"
        : networkIssue ? "Some data connections are temporarily unavailable. Available content is retained; check its timestamps and missing-data notes." : "Some data could not be loaded. Available content is retained; details are below."}</p>
      <details className="mt-2 text-xs">
        <summary className="cursor-pointer">{locale === "zh" ? `查看具体原因（${activeMessages.length}项）` : `Technical details (${activeMessages.length})`}</summary>
        <ul className="mt-2 space-y-1 break-words">{activeMessages.map((message, index) => <li key={index}>{message}</li>)}</ul>
      </details>
    </div>
  );
}
