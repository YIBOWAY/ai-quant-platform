'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Radio } from 'lucide-react';
import { Card, TerminalToolbarButton } from '@/components/ui/primitives';
import { apiPost, apiRequest } from '@/lib/apiClient';

type Locale = 'en' | 'zh';

type RemoteCandidate = {
  candidate_id: string;
  objective?: string;
  status?: string;
  sleeve_id?: string | null;
  source?: string;
};

type RemoteRequest = {
  request_id: string;
  objective?: string;
  status?: string;
  hang_if_pass?: boolean;
};

type RemoteBook = {
  candidates?: RemoteCandidate[];
  requests?: RemoteRequest[];
  verified_count?: number;
  hung_count?: number;
};

const copy = {
  en: {
    title: 'Chat remote',
    desc: 'Dispatch research and hang are two commands. A verified candidate is not hung.',
    ask: 'Research ask',
    send: 'Dispatch research',
    sending: 'Dispatching…',
    hangIfPass: 'Hang if it passes',
    hangIfPassHelp: 'Only check this when you wrote “hang if it passes” on this ask.',
    verified: 'Verified candidates',
    hung: 'Hung',
    hang: 'Hang',
    hanging: 'Hanging…',
    none: 'No verified candidate yet. Dispatch does not invent one.',
    requests: 'Requests',
  },
  zh: {
    title: '聊天遥控',
    desc: '派研究和挂仓是两件事。已验证候选不是挂上。',
    ask: '研究需求',
    send: '派研究',
    sending: '入队中…',
    hangIfPass: '过了就挂',
    hangIfPassHelp: '只有你在这次需求里写明「过了就挂」才勾。勾了也不是现在挂仓。',
    verified: '已验证候选',
    hung: '已挂上',
    hang: '挂上',
    hanging: '挂仓中…',
    none: '还没有已验证候选。派研究不会编一个出来。',
    requests: '研究请求',
  },
} as const;

export function AssistantRemotePanel({ locale = 'zh' }: { locale?: Locale }) {
  const text = copy[locale];
  const queryClient = useQueryClient();
  const [objective, setObjective] = useState('');
  const [hangIfPass, setHangIfPass] = useState(false);
  const bookQuery = useQuery({
    queryKey: ['assistant-remote-book'],
    queryFn: () => apiRequest<RemoteBook>('/api/assistant/remote/book'),
  });
  const book = bookQuery.data;
  const dispatchMutation = useMutation({
    mutationFn: () =>
      apiPost('/api/assistant/remote/dispatch', {
        objective: objective.trim(),
        hang_if_pass: hangIfPass,
      }),
    onSuccess: async () => {
      setObjective('');
      setHangIfPass(false);
      await queryClient.invalidateQueries({ queryKey: ['assistant-remote-book'] });
    },
  });
  const hangMutation = useMutation({
    mutationFn: (candidateId: string) =>
      apiPost('/api/assistant/remote/hang', { candidate_id: candidateId }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['assistant-remote-book'] });
      await queryClient.invalidateQueries({ queryKey: ['paper-strategy-ops-status'] });
    },
  });
  const canDispatch = objective.trim().length >= 8 && !dispatchMutation.isPending;

  return (
    <Card>
      <div className="mb-3 flex items-center gap-2">
        <Radio size={15} className="text-accent-success" />
        <h2 className="font-headline-sm text-text-primary">{text.title}</h2>
      </div>
      <p className="mb-4 text-sm text-text-secondary">{text.desc}</p>
      <label className="mb-3 flex flex-col gap-1 font-body-sm text-text-primary">
        {text.ask}
        <textarea
          className="min-h-20 rounded-lg border border-border-subtle bg-bg-base px-3 py-2 text-text-primary"
          maxLength={4000}
          onChange={(event) => setObjective(event.target.value)}
          value={objective}
        />
      </label>
      <label className="mb-3 flex items-start gap-2 text-sm text-text-secondary">
        <input
          checked={hangIfPass}
          onChange={(event) => setHangIfPass(event.target.checked)}
          type="checkbox"
        />
        <span>
          <span className="text-text-primary">{text.hangIfPass}</span>
          <span className="mt-1 block">{text.hangIfPassHelp}</span>
        </span>
      </label>
      <TerminalToolbarButton
        disabled={!canDispatch}
        onClick={() => dispatchMutation.mutate()}
        tone="info"
      >
        {dispatchMutation.isPending ? text.sending : text.send}
      </TerminalToolbarButton>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <div>
          <p className="mb-2 font-label-caps text-text-secondary">
            {text.verified} · {book?.verified_count ?? 0}
          </p>
          {(book?.candidates ?? []).filter((item) => item.status === 'verified').length === 0 ? (
            <p className="text-sm text-text-secondary">{text.none}</p>
          ) : (
            <ul className="space-y-2">
              {(book?.candidates ?? [])
                .filter((item) => item.status === 'verified')
                .map((item) => (
                  <li
                    className="rounded-lg border border-border-subtle bg-bg-base p-3"
                    key={item.candidate_id}
                  >
                    <p className="font-data-mono text-xs text-text-primary">{item.candidate_id}</p>
                    <p className="mt-1 text-sm text-text-secondary">{item.objective}</p>
                    <TerminalToolbarButton
                      className="mt-2"
                      disabled={hangMutation.isPending}
                      onClick={() => hangMutation.mutate(item.candidate_id)}
                    >
                      {hangMutation.isPending ? text.hanging : text.hang}
                    </TerminalToolbarButton>
                  </li>
                ))}
            </ul>
          )}
        </div>
        <div>
          <p className="mb-2 font-label-caps text-text-secondary">
            {text.requests} · {book?.requests?.length ?? 0} · {text.hung} {book?.hung_count ?? 0}
          </p>
          <ul className="space-y-2">
            {(book?.requests ?? []).slice(0, 6).map((item) => (
              <li className="font-data-mono text-xs text-text-secondary" key={item.request_id}>
                {item.status} {item.hang_if_pass ? '· hang_if_pass' : ''} · {item.objective}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Card>
  );
}
