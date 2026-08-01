'use client';

import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";

import {
  bootstrapOwnerSession,
  getOwnerSession,
  isOwnerSessionReady,
  OWNER_BOOTSTRAP_COMMAND,
  WorkspaceClientError,
} from "@/lib/hermes/workspaceClient";
import type { Locale } from "@/lib/locale";

type OwnerSessionState = "checking" | "required" | "submitting" | "ready";

export function OwnerSessionBootstrapPanel({
  locale,
  onBootstrapSuccess,
  onReadinessChange,
}: {
  locale: Locale;
  onBootstrapSuccess: () => void;
  onReadinessChange: (ready: boolean) => void;
}) {
  const isZh = locale === "zh";
  const [state, setState] = useState<OwnerSessionState>("checking");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [revealToken, setRevealToken] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const focusedRequiredRef = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    onReadinessChange(false);
    void getOwnerSession(controller.signal)
      .then((session) => {
        if (controller.signal.aborted) return;
        const ready = isOwnerSessionReady(session);
        setState(ready ? "ready" : "required");
        onReadinessChange(ready);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          isZh
            ? "无法检查本机授权状态，请确认后端服务可用后重试。"
            : "Unable to check local owner authorization. Confirm the backend is available and retry.",
        );
        setState("required");
        onReadinessChange(false);
      });
    return () => controller.abort();
  }, [isZh, onReadinessChange]);

  useEffect(() => {
    if (state !== "required" || focusedRequiredRef.current) return;
    focusedRequiredRef.current = true;
    headingRef.current?.focus();
  }, [state]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (state === "submitting") return;
    setError(null);
    setState("submitting");
    try {
      const session = await bootstrapOwnerSession(token);
      if (!isOwnerSessionReady(session)) {
        throw new WorkspaceClientError(
          "owner session is not mutation ready",
          503,
          "owner_session_not_ready",
        );
      }
      setToken("");
      setState("ready");
      onReadinessChange(true);
      onBootstrapSuccess();
    } catch (cause) {
      setError(
        cause instanceof WorkspaceClientError && cause.status === 401
          ? isZh
            ? "一次性 token 无效或已使用，请重新生成后再试。"
            : "The one-time token is invalid or already used. Generate a new token and retry."
          : cause instanceof WorkspaceClientError && cause.status === 429
            ? isZh
              ? "尝试次数过多，请稍后重新生成 token 再试。"
              : "Too many attempts. Wait, generate a new token, and retry."
            : isZh
              ? "本机授权失败，请确认后端服务可用后重试。"
              : "Local owner authorization failed. Confirm the backend is available and retry.",
      );
      setState("required");
      onReadinessChange(false);
    }
  }

  if (state === "checking" || state === "ready") {
    return null;
  }

  return (
    <section
      aria-labelledby="hermes-owner-bootstrap-title"
      className="mx-auto mb-4 mt-16 max-w-[480px] rounded-[var(--radius-card)] border border-border-subtle bg-bg-surface p-8 text-center"
    >
      <p aria-live="polite" className="sr-only" role="status">
        {isZh
          ? "需要完成首次使用授权，写入功能暂时锁定。"
          : "First-use authorization is required. Write controls are temporarily locked."}
      </p>
      <h2
        className="font-headline-lg text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
        id="hermes-owner-bootstrap-title"
        ref={headingRef}
        tabIndex={-1}
      >
        {isZh ? "首次使用授权" : "First-use authorization"}
      </h2>
      <p
        className="mt-3 font-body-sm text-text-secondary"
        id="hermes-owner-bootstrap-hint"
      >
        {isZh
          ? "在 Platform release checkout 根目录的后端终端运行以下命令，然后把一次性 token 粘贴到这里。token 只用于建立本机 owner 会话，不会保存到浏览器存储。"
          : "From the Platform release checkout root, run the command below in the backend terminal, then paste the one-time token here. It only establishes the local owner session and is not saved in browser storage."}
      </p>
      <code className="mt-4 block overflow-x-auto rounded-[var(--radius-card)] bg-bg-surface-muted px-3 py-2 text-left font-mono text-xs text-text-primary">
        {OWNER_BOOTSTRAP_COMMAND}
      </code>
      <form className="mt-4 flex flex-col gap-2" onSubmit={submit}>
        <label className="sr-only" htmlFor="hermes-owner-bootstrap-token">
          {isZh ? "一次性 bootstrap token" : "One-time bootstrap token"}
        </label>
        <div className="flex gap-2">
          <input
            aria-describedby={
              error
                ? "hermes-owner-bootstrap-hint hermes-owner-bootstrap-error"
                : "hermes-owner-bootstrap-hint"
            }
            autoComplete="one-time-code"
            className="app-touch-target min-w-0 flex-1 rounded-[var(--radius-card)] border border-border-subtle bg-bg-base px-3 py-2 font-mono text-sm text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
            disabled={state === "submitting"}
            id="hermes-owner-bootstrap-token"
            maxLength={256}
            minLength={32}
            name="owner_bootstrap_token"
            onChange={(event) => {
              setToken(event.target.value);
              if (error) setError(null);
            }}
            placeholder={isZh ? "粘贴一次性 token" : "Paste one-time token"}
            required
            spellCheck={false}
            type={revealToken ? "text" : "password"}
            value={token}
          />
          <button
            aria-label={
              revealToken
                ? isZh
                  ? "隐藏一次性 token"
                  : "Hide one-time token"
                : isZh
                  ? "显示一次性 token"
                  : "Show one-time token"
            }
            className="app-touch-target shrink-0 rounded-[var(--radius-card)] border border-border-subtle bg-bg-surface-muted px-3 py-2 font-body-sm text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info disabled:opacity-50"
            disabled={state === "submitting"}
            onClick={() => setRevealToken((visible) => !visible)}
            type="button"
          >
            {revealToken
              ? isZh
                ? "隐藏"
                : "Hide"
              : isZh
                ? "显示"
                : "Show"}
          </button>
        </div>
        <button
          className="app-touch-target w-full rounded-[var(--radius-card)] bg-[var(--color-hermes)] px-4 py-2 font-body-sm font-semibold text-white transition-opacity hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info disabled:opacity-50"
          disabled={state === "submitting"}
          type="submit"
        >
          {state === "submitting"
            ? isZh
              ? "授权中…"
              : "Authorizing…"
            : isZh
              ? "授权本机浏览器"
              : "Authorize this browser"}
        </button>
      </form>
      {error ? (
        <p
          className="mt-3 rounded-[var(--radius-card)] bg-bg-base px-2 py-1 font-body-sm text-danger"
          id="hermes-owner-bootstrap-error"
          role="alert"
        >
          {error}
        </p>
      ) : null}
    </section>
  );
}
