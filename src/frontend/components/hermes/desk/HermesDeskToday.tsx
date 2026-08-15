"use client";

/**
 * Hermes today = the three-ledger blotter, wired to the remote book
 * plus the existing research/result surfaces passed in as slots.
 */

import { useCallback, useMemo, useState, type ReactNode } from "react";
import {
  QueryClient,
  QueryClientProvider,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Send, Tag } from "lucide-react";
import { apiPost, apiRequest, ApiClientError } from "@/lib/apiClient";
import { useHermesDesk } from "./HermesDeskContext";

export type DeskLedger = "duty" | "research" | "paper";

type RemoteCandidate = {
  candidate_id: string;
  objective?: string;
  status?: string;
  sleeve_id?: string | null;
  source_digest?: string | null;
  factor_id?: string;
  universe?: string[];
  fossil?: boolean;
  official_observation?: boolean;
};

type RemoteRequest = {
  request_id: string;
  objective?: string;
  status?: string;
  job_key?: string | null;
  mode?: string;
};

type RemoteBook = {
  candidates?: RemoteCandidate[];
  requests?: RemoteRequest[];
  verified_count?: number;
  hung_count?: number;
  fossil_count?: number;
};

function digestShort(value?: string | null): string {
  if (!value || value.length < 12) return "无 digest";
  return value.slice(0, 12);
}

function errorText(error: unknown): string {
  if (error instanceof ApiClientError) return error.message;
  if (error instanceof Error) return error.message;
  return "请求失败";
}

export function HermesDeskToday(props: {
  dutyExtra?: ReactNode;
  researchExtra?: ReactNode;
}) {
  const [queryClient] = useState(() => new QueryClient());
  return (
    <QueryClientProvider client={queryClient}>
      <HermesDeskTodayBody {...props} />
    </QueryClientProvider>
  );
}

function HermesDeskTodayBody({
  dutyExtra,
  researchExtra,
}: {
  dutyExtra?: ReactNode;
  researchExtra?: ReactNode;
}) {
  const { ledger } = useHermesDesk();
  const queryClient = useQueryClient();
  const [objective, setObjective] = useState("");
  const [formula, setFormula] = useState("");
  const [universeText, setUniverseText] = useState("");
  const [hangId, setHangId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const bookQuery = useQuery({
    queryKey: ["assistant-remote-book"],
    queryFn: () => apiRequest<RemoteBook>("/api/assistant/remote/book"),
    refetchInterval: 15_000,
  });
  const book = bookQuery.data;
  const candidates = book?.candidates ?? [];
  const official = candidates.filter(
    (item) => item.fossil !== true && item.official_observation !== false,
  );
  const verified = official.filter((item) => item.status === "verified");
  const hung = official.filter((item) => item.status === "hung");
  const fossils = candidates.filter(
    (item) => item.fossil === true || item.official_observation === false,
  );
  const requests = book?.requests ?? [];

  const flash = useCallback((text: string) => {
    setToast(text);
    window.setTimeout(() => setToast(null), 3600);
  }, []);

  const dispatchMutation = useMutation({
    mutationFn: () =>
      apiPost("/api/assistant/remote/dispatch", {
        objective: objective.trim(),
        hang_if_pass: false,
      }),
    onSuccess: async () => {
      setObjective("");
      await queryClient.invalidateQueries({ queryKey: ["assistant-remote-book"] });
      flash("已派出研究。默认停在已验证候选，不会自动挂上。");
    },
  });

  const intakeMutation = useMutation({
    mutationFn: () => {
      const universe = universeText
        .split(/[\s,，]+/)
        .map((item) => item.trim().toUpperCase())
        .filter(Boolean);
      return apiPost("/api/assistant/remote/intake", {
        note: objective.trim(),
        formula: formula.trim() || null,
        universe: universe.length ? universe : null,
        hang_if_pass: false,
      });
    },
    onSuccess: async () => {
      setObjective("");
      setFormula("");
      setUniverseText("");
      await queryClient.invalidateQueries({ queryKey: ["assistant-remote-book"] });
      flash("材料已入研究账。缺公式或缺股票池会被拒绝，不会编一个出来。");
    },
  });

  const hangMutation = useMutation({
    mutationFn: (candidateId: string) =>
      apiPost("/api/assistant/remote/hang", { candidate_id: candidateId }),
    onSuccess: async () => {
      setHangId(null);
      await queryClient.invalidateQueries({ queryKey: ["assistant-remote-book"] });
      flash("已挂上：仓绑定该候选 digest，仅模拟。");
    },
  });

  const hero = useMemo(() => {
    if (bookQuery.isError) return "远程账读不到。下面不会用预览假数据顶上。";
    if (verified.length > 0) return `有 ${verified.length} 条已验证候选等你决定挂不挂。`;
    if (hung.length > 0) return `已挂上 ${hung.length} 条。还没有新的已验证候选。`;
    return "研究账空着。派研究或投入材料；缺公式或缺股票池会停下来。";
  }, [bookQuery.isError, hung.length, verified.length]);

  return (
    <>
      <div className="dp-main dp-scroll" style={{ minWidth: 0 }}>
        <section className="dp-hero">
          <div className="dp-hero-kicker">
            <span className="dp-caps">Hermes · 值班 / 研究 / 模拟</span>
            <span className="dp-caps" style={{ color: "var(--dp-up)" }}>
              公开 composer 关
            </span>
          </div>
          <h1 className="dp-hero-title">{hero}</h1>
          <div className="dp-hero-sub">
            <span>
              已验证候选 <span className="dp-num">{book?.verified_count ?? 0}</span>
            </span>
            <span>
              已挂上 <span className="dp-num">{book?.hung_count ?? 0}</span>
            </span>
            <span>
              化石仓（不计入效果）{" "}
              <span className="dp-num">{book?.fossil_count ?? fossils.length}</span>
            </span>
            {bookQuery.isFetching ? <span>对账中…</span> : null}
            {bookQuery.isError ? <span>账本错误：{errorText(bookQuery.error)}</span> : null}
          </div>
        </section>

        <div className="dp-sechead">
          <h2>
            {ledger === "duty" ? "策略状态" : ledger === "research" ? "研究账" : "模拟账"}
          </h2>
          <span className="count dp-num">
            {ledger === "research"
              ? `请求 ${requests.length} · 候选 ${verified.length}`
              : ledger === "paper"
                ? `已挂上 ${hung.length}`
                : `已挂 ${hung.length} · 候选 ${verified.length}`}
          </span>
        </div>

        <div className="dp-blotter">
          <table>
            <thead>
              <tr>
                <th style={{ width: 96 }}>状态</th>
                <th>条目</th>
                <th style={{ minWidth: 240 }}>说明</th>
                <th>宇宙 / digest</th>
                <th>动作</th>
              </tr>
            </thead>
            <tbody>
              {ledger !== "research"
                ? (ledger === "paper" ? hung : [...hung, ...verified]).map((item) => (
                    <tr className="dp-row" key={item.candidate_id}>
                      <td>
                        <span
                          className="dp-status"
                          data-kind={item.status === "hung" ? "hung" : "candidate"}
                        >
                          {item.status === "hung" ? "已挂上" : "未挂上"}
                        </span>
                      </td>
                      <td>
                        <div className="dp-strat-name">{item.factor_id || item.candidate_id}</div>
                        <div className="dp-strat-sub">{item.candidate_id}</div>
                      </td>
                      <td className="wrap">
                        <div className="dp-summary">{item.objective || "—"}</div>
                      </td>
                      <td>
                        {(item.universe ?? []).join(" · ") || "—"}
                        <div className="dp-strat-sub">{digestShort(item.source_digest)}</div>
                      </td>
                      <td>
                        {item.status === "verified" ? (
                          <button
                            type="button"
                            className="dp-hangbtn"
                            disabled={hangMutation.isPending}
                            onClick={() => setHangId(item.candidate_id)}
                          >
                            <Tag size={11} aria-hidden="true" />
                            挂上
                          </button>
                        ) : (
                          <span className="dp-strat-sub">{item.sleeve_id || "已挂"}</span>
                        )}
                      </td>
                    </tr>
                  ))
                : null}
              {ledger === "research"
                ? requests.map((item) => (
                    <tr className="dp-row" key={item.request_id}>
                      <td>
                        <span className="dp-status" data-kind="paused">
                          {item.status || "requested"}
                        </span>
                      </td>
                      <td>
                        <div className="dp-strat-name">{item.request_id}</div>
                        <div className="dp-strat-sub">{item.mode || "book_only"}</div>
                      </td>
                      <td className="wrap">
                        <div className="dp-summary">{item.objective}</div>
                      </td>
                      <td className="dp-strat-sub">{item.job_key || "未入队作业"}</td>
                      <td className="dp-strat-sub">派研究 · 不挂</td>
                    </tr>
                  ))
                : null}
              {ledger === "research"
                ? verified.map((item) => (
                    <tr className="dp-row" key={item.candidate_id}>
                      <td>
                        <span className="dp-status" data-kind="candidate">
                          已验证候选
                        </span>
                      </td>
                      <td>
                        <div className="dp-strat-name">{item.factor_id || item.candidate_id}</div>
                        <div className="dp-strat-sub">{item.candidate_id}</div>
                      </td>
                      <td className="wrap">
                        <div className="dp-summary">{item.objective}</div>
                      </td>
                      <td>
                        {(item.universe ?? []).join(" · ")}
                        <div className="dp-strat-sub">{digestShort(item.source_digest)}</div>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="dp-hangbtn"
                          onClick={() => setHangId(item.candidate_id)}
                        >
                          <Tag size={11} aria-hidden="true" />
                          挂上
                        </button>
                      </td>
                    </tr>
                  ))
                : null}
              {ledger === "paper" && fossils.length > 0
                ? fossils.map((item) => (
                    <tr className="dp-row" data-dim="true" key={`fossil-${item.candidate_id}`}>
                      <td>
                        <span className="dp-status" data-kind="paused">
                          化石
                        </span>
                      </td>
                      <td>
                        <div className="dp-strat-name">{item.candidate_id}</div>
                        <div className="dp-strat-sub">种子/无 digest · 不计效果</div>
                      </td>
                      <td className="wrap">
                        <div className="dp-summary">
                          {item.objective || "预览种子仓，不是每日观察"}
                        </div>
                      </td>
                      <td>—</td>
                      <td className="dp-strat-sub">不计入 P&L</td>
                    </tr>
                  ))
                : null}
              {(ledger === "duty" && hung.length + verified.length === 0) ||
              (ledger === "research" && requests.length + verified.length === 0) ||
              (ledger === "paper" && hung.length + fossils.length === 0) ? (
                <tr className="dp-row">
                  <td colSpan={5}>
                    <div className="dp-summary">这一本账现在是空的。没有用预览假数据填充。</div>
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        {ledger === "duty" && dutyExtra ? <div className="dp-embed">{dutyExtra}</div> : null}
        {ledger === "research" && researchExtra ? (
          <div className="dp-embed">{researchExtra}</div>
        ) : null}
      </div>

      <aside className="dp-rail" data-open="true" aria-label="本地遥控">
        <div className="dp-rail-head">
          <span className="title">遥控</span>
          <span className="dp-live">
            <span className="dp-dot" data-tone="ok" aria-hidden="true" />
            公开 composer 关
          </span>
        </div>
        <div className="dp-transcript dp-scroll">
          <div className="dp-msg" data-role="hermes">
            <div className="head">
              <span className="who">Hermes</span>
            </div>
            <div className="body">
              这就是工作台。派研究和挂仓是两条命令，走同一本远程账。材料缺公式或缺股票池会失败。
            </div>
          </div>
          {requests.slice(0, 8).map((item) => (
            <div className="dp-receipt" key={item.request_id}>
              <Send aria-hidden="true" />
              <div>
                <div className="rt">
                  {item.status} · {item.request_id}
                </div>
                <div className="rs">{item.objective}</div>
              </div>
            </div>
          ))}
        </div>
        <div className="dp-composer">
          <div className="dp-composer-box">
            <textarea
              rows={3}
              placeholder="研究需求（至少 8 个字）。要走材料闸，再填公式和股票池。"
              value={objective}
              onChange={(event) => setObjective(event.target.value)}
            />
            <input
              value={formula}
              onChange={(event) => setFormula(event.target.value)}
              placeholder="可证伪公式（材料闸必填）"
              style={{
                width: "100%",
                border: 0,
                background: "transparent",
                color: "var(--dp-text)",
                padding: "0 10px 6px",
                outline: "none",
              }}
            />
            <input
              value={universeText}
              onChange={(event) => setUniverseText(event.target.value)}
              placeholder="股票池，逗号分隔，例如 SPY,QQQ"
              style={{
                width: "100%",
                border: 0,
                background: "transparent",
                color: "var(--dp-text)",
                padding: "0 10px 8px",
                outline: "none",
              }}
            />
            <div className="dp-composer-tools">
              <button
                type="button"
                className="dp-btn"
                disabled={objective.trim().length < 8 || dispatchMutation.isPending}
                onClick={() => dispatchMutation.mutate()}
              >
                派研究
              </button>
              <button
                type="button"
                className="dp-send"
                disabled={objective.trim().length < 8 || intakeMutation.isPending}
                onClick={() => intakeMutation.mutate()}
                aria-label="材料入账"
              >
                <Send aria-hidden="true" />
              </button>
            </div>
          </div>
          <div className="dp-composer-hint">
            <span>材料入账要公式+宇宙</span>
            <span>·</span>
            <span>派研究只记需求</span>
          </div>
          {dispatchMutation.isError ? (
            <div className="dp-composer-hint">{errorText(dispatchMutation.error)}</div>
          ) : null}
          {intakeMutation.isError ? (
            <div className="dp-composer-hint">{errorText(intakeMutation.error)}</div>
          ) : null}
        </div>
      </aside>

      {hangId ? (
        <div className="dp-toast" role="dialog" aria-label="确认挂上">
          <div>挂上必须绑该候选 digest。确定挂 {hangId}？</div>
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button type="button" className="dp-btn" onClick={() => setHangId(null)}>
              取消
            </button>
            <button
              type="button"
              className="dp-btn"
              data-variant="accent"
              disabled={hangMutation.isPending}
              onClick={() => hangMutation.mutate(hangId)}
            >
              确认挂上
            </button>
          </div>
          {hangMutation.isError ? <div>{errorText(hangMutation.error)}</div> : null}
        </div>
      ) : null}
      {toast ? (
        <div className="dp-toast" role="status">
          {toast}
        </div>
      ) : null}
    </>
  );
}
