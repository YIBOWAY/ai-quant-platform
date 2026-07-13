import {
  AutomationDetails,
  FocusedArtifactCard,
} from "@/components/hermes/artifacts";
import { Card } from "@/components/ui/primitives";
import { getHermesArtifacts, type HermesArtifact } from "@/lib/api";
import { getServerLocale } from "@/lib/serverLocale";

function pickLatestAutomation(
  items: HermesArtifact[],
): Extract<HermesArtifact, { kind: "automation_status" }> | null {
  const automationItems = items.filter(
    (item): item is Extract<HermesArtifact, { kind: "automation_status" }> =>
      item.kind === "automation_status",
  );
  if (automationItems.length === 0) return null;
  return automationItems.reduce((latest, item) =>
    item.occurred_at > latest.occurred_at ? item : latest,
  );
}

/**
 * F2 Tasks: current automation artifacts only.
 * Research task ledger remains unconnected — no mutation controls.
 */
export default async function HermesTasksPage() {
  const locale = await getServerLocale();
  const artifacts = await getHermesArtifacts();
  const automation = pickLatestAutomation(artifacts.items);
  const isZh = locale === "zh";

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
            ? "只读展示当前平台自动化状态。"
            : "Read-only platform automation status."}
        </p>
      </header>

      <Card className="border-info/30 bg-info/5" tone="info">
        <p className="font-body-sm font-semibold text-text-primary">
          {isZh ? "研究任务账本尚未接入" : "Research task ledger is not connected"}
        </p>
        <p className="mt-1 font-body-sm text-text-secondary">
          {isZh
            ? "本交付不能创建、提交或跟踪 Hermes 研究任务。下方仅反映平台 9H 自动化产物。"
            : "This delivery cannot create, submit, or track Hermes research tasks. Below reflects platform 9H automation artifacts only."}
        </p>
      </Card>

      {automation ? (
        <div className="space-y-3" data-hermes-tasks-automation>
          <FocusedArtifactCard artifact={automation} locale={locale} />
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
      ) : (
        <Card className="bg-[var(--color-stream-surface)]">
          <p className="font-body-sm text-text-secondary">
            {isZh
              ? "当前没有可用的自动化状态产物。"
              : "No automation status artifact is available."}
          </p>
        </Card>
      )}
    </section>
  );
}
