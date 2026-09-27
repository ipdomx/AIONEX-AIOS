"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { MessageSquareText, Plus, RefreshCw, Send, Timer } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/use-auth";
import { ApiError, listProjects } from "@/lib/api";
import { conversationApi, type Conversation, type ConversationAgent, type ConversationHistory, type ConversationUsage } from "@/lib/project-conversations";
import type { Project } from "@/types";

export function ConversationsClient() {
  const t = useTranslations("conversations");
  const locale = useLocale();
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [threads, setThreads] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState("");
  const [history, setHistory] = useState<ConversationHistory | null>(null);
  const [policy, setPolicy] = useState<ConversationUsage | null>(null);
  const [agents, setAgents] = useState<ConversationAgent[]>([]);
  const [agentId, setAgentId] = useState("");
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [external, setExternal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [now, setNow] = useState(0);
  const [accessDenied, setAccessDenied] = useState(false);
  const observedAt = useRef(0);
  const selection = useRef("");
  const createIntent = useRef<{ key: string; id: string } | null>(null);
  const sendIntent = useRef<{ key: string; id: string } | null>(null);

  const reportError = useCallback((cause: unknown) => {
    if (cause instanceof ApiError && [401, 403].includes(cause.status)) setAccessDenied(true);
    setError(cause instanceof Error ? cause.message : t("error"));
  }, [t]);

  const load = useCallback(async () => {
    try {
      const [p, c, u, a] = await Promise.all([
        listProjects(), conversationApi.list(), conversationApi.policy(), conversationApi.agents(),
      ]);
      setProjects(p.filter((x) => !["deleted", "archived", "cancelled"].includes(x.status)));
      setThreads(c); setPolicy(u); setAgents(a); setAccessDenied(false);
      setProjectId((old) => old || new URLSearchParams(window.location.search).get("project") || p[0]?.id || "");
      setAgentId((old) => a.some((x) => x.id === old) ? old : a[0]?.id || "");
      setError("");
    } catch (cause) { reportError(cause); }
    finally { setLoading(false); }
  }, [reportError]);

  useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace(`/${locale}/login`);
    if (!isLoading && isAuthenticated) void load();
  }, [isAuthenticated, isLoading, locale, router, load]);

  useEffect(() => {
    const tick = window.setInterval(() => setNow(performance.now()), 1000);
    return () => window.clearInterval(tick);
  }, []);

  useEffect(() => {
    selection.current = selected;
    setHistory(null);
    if (!selected || !isAuthenticated) return;
    let stopped = false;
    let pending = false;
    const refresh = async () => {
      if (pending) return;
      pending = true;
      try {
        const [next, usage] = await Promise.all([conversationApi.history(selected), conversationApi.policy()]);
        if (!stopped && selection.current === selected) {
          observedAt.current = performance.now(); setNow(observedAt.current);
          setHistory(next); setPolicy(usage); setAccessDenied(false);
        }
      } catch (cause) { if (!stopped) reportError(cause); }
      finally { pending = false; }
    };
    void refresh();
    // Polling retrieves durable results; it never resubmits a turn.
    const interval = window.setInterval(() => void refresh(), 3000);
    return () => { stopped = true; window.clearInterval(interval); };
  }, [selected, isAuthenticated, reportError]);

  async function createConversation(event: FormEvent) {
    event.preventDefault();
    if (!projectId || !title.trim() || busy) return;
    const key = `${projectId}\0${title.trim()}`;
    if (createIntent.current?.key !== key) createIntent.current = { key, id: crypto.randomUUID() };
    setBusy(true); setError("");
    try {
      const created = await conversationApi.create(projectId, title.trim(), createIntent.current.id);
      createIntent.current = null;
      setTitle(""); setSelected(created.id); await load();
    } catch (cause) { reportError(cause); }
    finally { setBusy(false); }
  }

  async function sendMessage(event: FormEvent) {
    event.preventDefault();
    if (!selected || !message.trim() || !agentId || busy) return;
    const key = `${selected}\0${agentId}\0${message.trim()}`;
    if (sendIntent.current?.key !== key) sendIntent.current = { key, id: crypto.randomUUID() };
    setBusy(true); setError("");
    try {
      await conversationApi.send(selected, message.trim(), agentId, sendIntent.current.id, external);
      sendIntent.current = null;
      setMessage("");
      const id = selected;
      const next = await conversationApi.history(id);
      if (selection.current === id) { observedAt.current = performance.now(); setNow(observedAt.current); setHistory(next); }
      setPolicy(await conversationApi.policy());
    } catch (cause) { reportError(cause); }
    finally { setBusy(false); }
  }

  async function closeConversation() {
    if (!selected || busy || !window.confirm(t("closeConfirm"))) return;
    setBusy(true); setError("");
    try { await conversationApi.close(selected); const next = await conversationApi.history(selected); observedAt.current = performance.now(); setNow(observedAt.current); setHistory(next); await load(); }
    catch (cause) { reportError(cause); }
    finally { setBusy(false); }
  }

  const agent = agents.find((item) => item.id === agentId);
  const current = history?.conversation;
  // Derive the display from the server's remaining duration and a monotonic
  // elapsed interval, never from the browser's potentially incorrect wall clock.
  const seconds = current ? Math.max(0, current.seconds_remaining - Math.floor(Math.max(0, now - observedAt.current) / 1000)) : 0;
  const waiting = history?.messages.some((item) => ["queued", "running"].includes(item.status)) ?? false;
  const needsReview = history?.messages.at(-1)?.status === "needs_review";
  const canSend = Boolean(current && current.status === "open" && seconds > 0 && policy?.values.enabled && !accessDenied &&
    policy.usage.day_messages < policy.values.messages_per_day &&
    (policy.values.lifetime_message_credits < 0 || policy.usage.total_message_credits < policy.values.lifetime_message_credits) &&
    current.messages_used < current.messages_allowed && !waiting && !needsReview && agent &&
    (!agent.external_processing || external) && !busy);
  const statusLabel = (state: string) => ["open", "paused", "closed", "expired", "queued", "running", "completed", "failed", "cancelled", "needs_review"].includes(state)
    ? t(`status.${state}`) : state;

  if (isLoading || !isAuthenticated || loading) return <div className="site-container py-16" role="status">{t("loading")}</div>;
  return (
    <section className="site-container space-y-6 py-10" dir={locale === "ar" ? "rtl" : "ltr"}>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div><span className="eyebrow"><MessageSquareText className="h-4 w-4" />AIONEX</span>
          <h1 className="mt-4 text-3xl font-semibold">{t("title")}</h1>
          <p className="mt-3 max-w-3xl text-sm leading-7 text-white/60">{t("description")}</p></div>
        <Button variant="secondary" onClick={() => void load()} disabled={busy}><RefreshCw className="h-4 w-4" />{t("refresh")}</Button>
      </header>
      {error && <p role="alert" className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm">{error}</p>}
      {policy && <div className="grid gap-3 sm:grid-cols-3">
        <div className="glass-panel rounded-2xl p-4"><p className="text-xs text-white/50">{t("daily")}</p><p className="mt-2 text-xl">{policy.usage.day_messages} / {policy.values.messages_per_day}</p></div>
        <div className="glass-panel rounded-2xl p-4"><p className="text-xs text-white/50">{t("credits")}</p><p className="mt-2 text-xl">{policy.values.lifetime_message_credits < 0 ? t("unlimited") : Math.max(0, policy.values.lifetime_message_credits - policy.usage.total_message_credits)}</p></div>
        <div className="glass-panel rounded-2xl p-4"><p className="text-xs text-white/50">{t("concurrent")}</p><p className="mt-2 text-xl">{policy.values.max_open_conversations}</p></div>
      </div>}
      {policy && !policy.values.enabled && <p role="alert">{t("suspended")}</p>}
      <div className="grid items-start gap-5 lg:grid-cols-[19rem_minmax(0,1fr)]">
        <aside className="glass-panel space-y-5 rounded-2xl p-5">
          <form onSubmit={createConversation} className="space-y-3">
            <label className="block text-sm">{t("project")}<select value={projectId} onChange={(event) => setProjectId(event.target.value)} className="input-field mt-2 w-full" required>
              <option value="">{t("chooseProject")}</option>{projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select></label>
            <label className="block text-sm">{t("name")}<input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={240} required className="input-field mt-2 w-full" /></label>
            <Button type="submit" disabled={busy || accessDenied || !policy?.values.enabled || !projectId}><Plus className="h-4 w-4" />{t("new")}</Button>
          </form>
          <nav aria-label={t("title")} className="max-h-[32rem] space-y-2 overflow-y-auto">
            {threads.length === 0 && <p className="text-sm text-white/50">{t("empty")}</p>}
            {threads.map((item) => <button key={item.id} type="button" disabled={busy} onClick={() => { setSelected(item.id); setMessage(""); sendIntent.current = null; }}
              aria-current={selected === item.id ? "page" : undefined}
              className={`block w-full rounded-xl border p-3 text-start ${selected === item.id ? "border-electric-400 bg-electric-500/10" : "border-white/10 hover:bg-white/5"}`}>
              <span className="block truncate text-sm font-medium">{item.title}</span>
              <span className="mt-1 block text-xs text-white/50">{projects.find((p) => p.id === item.project_id)?.name || item.project_id} · {statusLabel(item.effective_status)}</span>
            </button>)}
          </nav>
        </aside>
        <div className="glass-panel min-w-0 rounded-2xl p-5 sm:p-6">
          {!current || !history ? <p className="py-20 text-center text-white/50">{selected ? t("loading") : t("chooseConversation")}</p> : <>
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-white/10 pb-4">
              <div><h2 className="text-xl font-semibold">{current.title}</h2><p className="mt-2 flex items-center gap-2 text-xs text-white/60"><Timer className="h-4 w-4" />{t("remaining")} {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")} · {current.messages_used}/{current.messages_allowed}</p></div>
              <Button variant="secondary" disabled={busy || current.status === "closed"} onClick={() => void closeConversation()}>{t("close")}</Button>
            </div>
            <div className="max-h-[34rem] min-h-48 space-y-4 overflow-y-auto py-5" aria-live="polite" aria-relevant="additions text">
              {history.messages.length === 0 && <p className="text-sm text-white/50">{t("firstMessage")}</p>}
              {history.messages.map((item) => <article key={item.id} className="space-y-2">
                <div className="rounded-2xl border border-white/10 bg-white/5 p-4"><p className="mb-2 text-xs text-white/40">{t("you")} · {item.ordinal}</p><p className="whitespace-pre-wrap break-words text-sm leading-7">{item.user_message}</p></div>
                <div className="rounded-2xl border border-electric-500/20 bg-electric-500/5 p-4"><p className="mb-2 text-xs text-electric-200">{t("assistant")} · {statusLabel(item.status)}</p>
                  <p className="whitespace-pre-wrap break-words text-sm leading-7">{item.assistant_message || (item.status === "needs_review" ? t("review") : item.error || t("pending"))}</p></div>
              </article>)}
            </div>
            <form onSubmit={sendMessage} className="space-y-3 border-t border-white/10 pt-4">
              <label className="block text-sm">{t("assistant")}<select className="input-field mt-2 w-full" value={agentId} onChange={(event) => { setAgentId(event.target.value); setExternal(false); }}>
                <option value="">{t("chooseAssistant")}</option>{agents.map((a) => <option key={a.id} value={a.id}>{a.name} · {a.model}</option>)}
              </select></label>
              {agents.length === 0 && <p className="text-sm text-amber-200">{t("notConfigured")}</p>}
              {agent?.external_processing && <label className="flex gap-2 text-xs leading-6"><input type="checkbox" checked={external} onChange={(event) => setExternal(event.target.checked)} />{t("externalConsent")}</label>}
              <label className="block text-sm">{t("message")}<textarea value={message} onChange={(event) => setMessage(event.target.value)} rows={4} maxLength={policy?.values.max_message_characters || 12000} className="input-field mt-2 w-full resize-y" disabled={!canSend} required /></label>
              <div className="flex flex-wrap items-center justify-between gap-3"><p className="max-w-lg text-xs leading-6 text-white/40">{t("creditsNote")}</p><Button type="submit" disabled={!canSend || !message.trim()}><Send className="h-4 w-4" />{busy ? t("sending") : t("send")}</Button></div>
              {(seconds === 0 || current.status !== "open") && <p className="text-sm text-amber-200">{t("inactive")}</p>}
              {needsReview && <p className="text-sm text-amber-200">{t("review")}</p>}
            </form>
          </>}
        </div>
      </div>
    </section>
  );
}
