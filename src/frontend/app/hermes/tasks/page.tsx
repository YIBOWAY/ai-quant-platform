import {
  ArtifactFeed,
  AutomationDetails,
  FocusedArtifactCard,
  OpportunitySummary,
  WeeklyReviewSummary,
  artifactFeedReadState,
} from "@/components/hermes/artifacts";
import { Card } from "@/components/ui/primitives";
import { getHermesArtifacts } from "@/lib/api";
import {
  pickLatestArtifactByKind,
  pickLatestAutomation,
} from "@/lib/hermes/viewModel";
import { getServerLocale } from "@/lib/serverLocale";

/**
 * Hermes Tasks: platform evidence read model from Hermes artifacts.
 * Research task write ledger remains unconnected — no create/submit mutation.
 */
export default async function HermesTasksPage() {
  const locale = await getServerLocale();
  const artifacts = await getHermesArtifacts();
  const automation = pickLatestAutomation(artifacts.items);
  const weekly = pickLatestArtifactByKind(artifacts.items, "weekly_review");
  const opportunities = pickLatestArtifactByKind(
    artifacts.items,
    "opportunity_summary",
  );
  const isZh = locale === "zh";
  const feedReadState = artifactFeedReadState(artifacts);
  const feedHasIssue =
    feedReadState === "degraded" || feedReadState === "unavailable";

  return (
    <section aria-labelledby="hermes-tasks-title" className="space-y-4" data-hermes-tasks>
      <header className="space-y-2">
        <p className="font-label-caps uppercase text-text-secondary">
          {isZh ? "任务" : "Tasks"}
        </p>
        <h1 className="font-headline-lg text-text-primary" id="hermes-tasks-title">
          {isZh ? "任务" : "Tasks"}
        </h1>
        <p className="font-body-sm text-text-secondary">
          {isZh
            ? "只读平台证据：自动化、周报与机会摘要。"
            : "Read-only platform evidence: automation, weekly review, and opportunities."}
        </p>
      </header>

      <div data-hermes-tasks-write-ledger-banner>
        <Card className="border-info/30 bg-info/5" tone="info">
          <p className="font-body-sm font-semibold text-text-primary">
            {isZh
              ? "Hermes 研究任务写入账本尚未接入"
              : "Hermes research task write ledger is not connected"}
          </p>
          <p className="mt-1 font-body-sm text-text-secondary">
            {isZh
              ? "本页不能创建、提交或跟踪 Hermes 研究任务。下方仅为平台 Hermes 产物证据（自动化/周报/机会），不是研究任务写入账本。"
              : "This page cannot create, submit, or track Hermes research tasks. Below is platform Hermes artifact evidence only (automation / weekly review / opportunities) — not a research-task write ledger."}
          </p>
        </Card>
      </div>

      {feedHasIssue ? (
        <div data-hermes-tasks-feed-issue={feedReadState}>
          <ArtifactFeed envelope={artifacts} locale={locale} />
        </div>
      ) : null}

      {automation ? (
        <div className="space-y-3" data-hermes-tasks-automation>
          <h2 className="font-label-caps text-text-secondary">
            {isZh ? "自动化状态" : "Automation status"}
          </h2>
          <FocusedArtifactCard artifact={automation} locale={locale} />
          <div data-hermes-tasks-automation-jobs>
            <Card className="bg-[var(--color-stream-surface)]">
              <h2 className="font-label-caps text-text-secondary">
                {isZh ? "平台自动化作业" : "Automation jobs"}
              </h2>
              <ul className="mt-3 space-y-3">
                {automation.data.jobs.map((job) => (
                  <li
                    className="rounded-lg border border-border-subtle bg-bg-base p-3"
                    key={job.job_id}
                  >
                    <AutomationDetails
                      job={job}
                      locale={locale}
                      open={
                        job.status === "failed" ||
                        job.status === "stale" ||
                        job.status === "never_run"
                      }
                    />
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        </div>
      ) : feedHasIssue ? null : (
        <div data-hermes-tasks-automation-empty>
          <Card className="bg-[var(--color-stream-surface)]">
            <p className="font-body-sm text-text-secondary">
              {isZh
                ? "当前没有可用的自动化状态产物。"
                : "No automation status artifact is available."}
            </p>
          </Card>
        </div>
      )}

      {weekly ? (
        <div className="space-y-2" data-hermes-tasks-weekly-review>
          <h2 className="font-label-caps text-text-secondary">
            {isZh ? "周报复核摘要" : "Weekly review summary"}
          </h2>
          <WeeklyReviewSummary artifact={weekly} locale={locale} />
        </div>
      ) : null}

      {opportunities ? (
        <div className="space-y-2" data-hermes-tasks-opportunity-summary>
          <h2 className="font-label-caps text-text-secondary">
            {isZh ? "机会摘要计数" : "Opportunity summary counts"}
          </h2>
          <OpportunitySummary artifact={opportunities} locale={locale} />
        </div>
      ) : null}

      {!feedHasIssue && !automation && !weekly && !opportunities ? (
        <Card className="bg-[var(--color-stream-surface)]">
          <p className="font-body-sm text-text-secondary">
            {isZh
              ? "当前没有可用的平台任务相关产物。"
              : "No platform task-related artifacts are available."}
          </p>
        </Card>
      ) : null}
    </section>
  );
}
