import { Bot, Cpu, Network, ShieldCheck } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { AgentTaskForm } from "@/components/forms/AgentTaskForm";
import { getAgentCandidates, getAgentLlmConfig, getFactors } from "@/lib/api";

export default async function AgentStudio() {
  const [candidates, factors, llmConfig] = await Promise.all([
    getAgentCandidates(),
    getFactors(),
    getAgentLlmConfig(),
  ]);
  const latestCandidate = candidates.candidates[0];

  return (
    <div className="flex h-full w-full overflow-hidden bg-base">
      <aside className="flex h-full w-[300px] shrink-0 flex-col border-r border-border-subtle bg-surface">
        <div className="border-b border-border-subtle bg-surface-dim p-4">
          <h1 className="font-headline-lg text-text-primary">Agent Studio</h1>
          <p className="mt-1 font-body-sm text-text-secondary">
            Candidates are inert files until manual review.
          </p>
          <p className="mt-2 font-data-mono text-[10px] uppercase text-text-secondary">
            llm={llmConfig.provider} model={llmConfig.model ?? "none"} key=
            {llmConfig.has_api_key ? "set" : "unset"}
          </p>
        </div>
        <div className="flex-1 overflow-y-auto">
          <div className="border-b border-border-subtle p-4">
            <h3 className="mb-3 font-label-caps text-text-secondary">Candidate Pool</h3>
            {candidates.candidates.length ? (
              <ul className="space-y-2">
                {candidates.candidates.map((candidate) => (
                  <li
                    key={candidate.candidate_id}
                    className="rounded border border-border-subtle bg-surface-container-high p-3"
                  >
                    <div className="flex items-center gap-2">
                      <Cpu size={14} className="text-primary" />
                      <span className="truncate font-body-sm text-text-primary">
                        {candidate.candidate_id}
                      </span>
                    </div>
                    <div className="mt-2 font-data-mono text-[10px] uppercase text-text-secondary">
                      {candidate.artifact_type} · {candidate.status}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                title="No candidates"
                description="Run an agent task to create a pending candidate."
              />
            )}
          </div>
          <div className="p-4">
            <h3 className="mb-3 font-label-caps text-text-secondary">Registry Context</h3>
            <div className="flex items-center gap-2 rounded border border-border-subtle bg-surface-variant p-3">
              <Network size={14} className="text-info" />
              <span className="font-body-sm text-text-secondary">
                Registered factors: {factors.factors.length}
              </span>
            </div>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="border-b border-border-subtle bg-surface px-4 py-3">
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2 font-data-mono text-sm text-text-primary">
                <Bot size={16} className="text-primary" />
                {latestCandidate?.candidate_id ?? "No candidate selected"}
              </div>
              <p className="mt-1 font-body-sm text-text-secondary">
                Source preview is read as text only. It is never imported or executed.
              </p>
            </div>
            <span className="flex items-center gap-1 rounded border border-warning/40 bg-warning/10 px-2 py-1 font-data-mono text-[10px] uppercase text-warning">
              <ShieldCheck size={12} /> manual review required
            </span>
          </div>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          <AgentTaskForm candidates={candidates.candidates} />
          <EmptyState
            title="Source preview not loaded"
            description="Candidate source is shown only after loading a specific candidate detail as plain text."
          />
          <EmptyState
            title="Audit timeline pending"
            description="Structured audit log viewing is scheduled separately."
          />
        </div>
      </div>
    </div>
  );
}
