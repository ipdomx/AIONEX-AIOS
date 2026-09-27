"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { MessageCircle, RefreshCw, Save, ShieldCheck } from "lucide-react";
import { useLanguageVoice } from "@/components/providers/LanguageVoiceProvider";
import { translateInterfaceText } from "@/lib/interface-translations";
import { governanceApi, type ConversationLimits, type GovernedConversation, type GovernedUsage, type GovernanceDirectory, type GovernanceScope } from "@/lib/conversation-governance";

type NumericKey = Exclude<keyof ConversationLimits, "enabled" | "default_agent_id">;
const limits: { key: NumericKey; label: string; min: number; max: number }[] = [
  { key: "max_projects", label: "Projects per user", min: 0, max: 100000 },
  { key: "max_open_conversations", label: "Concurrent conversations per user", min: 0, max: 1000 },
  { key: "max_open_conversations_per_project", label: "Concurrent conversations per project", min: 0, max: 1000 },
  { key: "conversation_seconds", label: "Conversation duration in seconds", min: 1, max: 31536000 },
  { key: "messages_per_conversation", label: "Messages per conversation", min: 0, max: 100000 },
  { key: "messages_per_day", label: "Messages per UTC day", min: 0, max: 1000000 },
  { key: "lifetime_message_credits", label: "Lifetime message credits (-1 = unlimited)", min: -1, max: 1000000000 },
  { key: "max_message_characters", label: "Characters per message", min: 1, max: 50000 },
  { key: "priority", label: "Dispatch priority (0–100)", min: 0, max: 100 },
];
const PLAN_IDENTIFIER_PATTERN = "[a-z][a-z0-9_-]{0,49}";
const input = "mt-2 w-full rounded-xl border border-white/10 bg-slate-950 p-3 text-sm text-white";
const button = "rounded-xl border border-white/10 px-4 py-2 text-sm text-white/80 hover:bg-white/10 disabled:opacity-40";

export default function ConversationGovernancePage() {
  const { locale } = useLanguageVoice();
  const t = useCallback((text: string) => translateInterfaceText(text, locale), [locale]);
  const [data, setData] = useState<GovernanceDirectory | null>(null);
  const [scope, setScope] = useState<GovernanceScope>("global");
  const [identifier, setIdentifier] = useState("default");
  const [dirty, setDirty] = useState<Partial<ConversationLimits>>({});
  const [conversations, setConversations] = useState<GovernedConversation[]>([]);
  const [filter, setFilter] = useState("");
  const [usage, setUsage] = useState<GovernedUsage | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const selectedPolicy = data?.policies.find((p) => p.scope === scope && p.identifier === identifier);
  const effective = useMemo(() => {
    if (!data) return null;
    const global = data.policies.find((p) => p.scope === "global" && p.identifier === "default");
    const user = data.users.find((u) => u.id === identifier);
    const plan = data.policies.find((p) => p.scope === "plan" && p.identifier === (scope === "user" ? user?.plan : identifier));
    return { ...data.defaults, ...global?.values, ...(scope !== "global" ? plan?.values : {}), ...selectedPolicy?.values, ...dirty };
  }, [data, dirty, identifier, scope, selectedPolicy]);

  const fail = useCallback((cause: unknown) => setError(cause instanceof Error ? cause.message : t("Governance request failed.")), [t]);
  const load = useCallback(async () => {
    setLoading(true);
    try { setData(await governanceApi.get()); setConversations(await governanceApi.conversations()); setError(""); }
    catch (cause) { fail(cause); }
    finally { setLoading(false); }
  }, [fail]);
  useEffect(() => { void load(); }, [load]);

  function chooseScope(value: GovernanceScope) {
    setScope(value); setDirty({}); setMessage("");
    setIdentifier(value === "global" ? "default" : value === "plan" ? "free" : data?.users[0]?.id || "");
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!identifier.trim() || !Object.keys(dirty).length || busy) return;
    setBusy(true); setError(""); setMessage("");
    try {
      await governanceApi.update(scope, identifier.trim(), selectedPolicy?.version || 0, dirty);
      setDirty({}); await load(); setMessage(t("Policy saved with an audited version. Usage counters were not reset."));
    } catch (cause) { fail(cause); }
    finally { setBusy(false); }
  }
  async function reset() {
    if (!selectedPolicy || busy || !window.confirm(t("Reset this policy to inherited values? Existing usage remains charged."))) return;
    setBusy(true); setError(""); setMessage("");
    try { await governanceApi.reset(scope, identifier, selectedPolicy.version); setDirty({}); await load(); setMessage(t("Policy override reset. Usage history was retained.")); }
    catch (cause) { fail(cause); }
    finally { setBusy(false); }
  }
  async function inspectUser() {
    setBusy(true); setError(""); setUsage(null);
    try {
      setConversations(await governanceApi.conversations(filter || undefined));
      if (filter) setUsage(await governanceApi.usage(filter));
    } catch (cause) { fail(cause); }
    finally { setBusy(false); }
  }
  async function act(item: GovernedConversation, action: "pause" | "resume" | "close") {
    if (busy || !window.confirm(t("Apply this conversation action? Its original age and counters are retained."))) return;
    setBusy(true); setError(""); setMessage("");
    try { await governanceApi.control(item, action, note); setConversations(await governanceApi.conversations(filter || undefined)); setMessage(t("Conversation control recorded in the owner audit.")); }
    catch (cause) { fail(cause); }
    finally { setBusy(false); }
  }

  return <div className="space-y-6">
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div><p className="mb-3 flex items-center gap-2 text-xs text-electric-300"><ShieldCheck className="h-4 w-4" />{t("Super Owner")}</p>
        <h1 className="flex items-center gap-3 text-2xl font-bold"><MessageCircle className="h-6 w-6" />{t("Conversation Governance")}</h1>
        <p className="mt-3 max-w-3xl text-sm leading-7 text-white/50">{t("Set global, plan and user conversation limits. All enforcement and counters are server-side.")}</p></div>
      <button className={button} disabled={busy || loading} onClick={() => void load()}><RefreshCw className="me-2 inline h-4 w-4" />{t("Refresh")}</button>
    </header>
    {error && <p role="alert" className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm">{error}</p>}
    {message && <p role="status" className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm">{message}</p>}
    {loading && !data ? <p role="status">{t("Loading conversation governance…")}</p> : data && effective && <>
      <form onSubmit={save} className="glass-card space-y-5 p-5 sm:p-6">
        <div className="grid gap-4 md:grid-cols-2">
          <label className="text-sm">{t("Policy scope")}<select className={input} value={scope} disabled={busy} onChange={(e) => chooseScope(e.target.value as GovernanceScope)}>
            <option value="global">{t("Global defaults")}</option><option value="plan">{t("Plan override")}</option><option value="user">{t("User override")}</option>
          </select></label>
          <label className="text-sm">{t("Policy target")}{scope === "user" ? <select className={input} value={identifier} disabled={busy} onChange={(e) => { setIdentifier(e.target.value); setDirty({}); }}>
            <option value="">{t("Select a user")}</option>{data.users.map((u) => <option key={u.id} value={u.id}>{u.name} · {u.email} · {u.plan}</option>)}
          </select> : <input className={input} value={identifier} disabled={busy || scope === "global"} required pattern={scope === "plan" ? PLAN_IDENTIFIER_PATTERN : undefined} onChange={(e) => { setIdentifier(e.target.value); setDirty({}); }} />}</label>
        </div>
        <p className="text-xs leading-6 text-white/45">{t("Numeric overrides use global → plan → user precedence. A suspended layer cannot be overridden by a lower layer. Only edited fields are saved.")}</p>
        <label className="flex items-center gap-3 rounded-xl border border-white/10 p-4 text-sm"><input type="checkbox" checked={effective.enabled} disabled={busy} onChange={(e) => setDirty((old) => ({ ...old, enabled: e.target.checked }))} />{t("Allow governed conversations and new work")}</label>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{limits.map((field) => <label key={field.key} className="text-sm">{t(field.label)}
          <input type="number" className={input} min={field.min} max={field.max} step={1} required value={effective[field.key]} disabled={busy}
            onChange={(e) => { const value = e.currentTarget.valueAsNumber; if (Number.isFinite(value)) setDirty((old) => ({ ...old, [field.key]: value })); }} />
        </label>)}</div>
        <label className="block text-sm">{t("Default platform assistant")}<select className={input} disabled={busy} value={effective.default_agent_id} onChange={(e) => setDirty((old) => ({ ...old, default_agent_id: e.target.value }))}>
          <option value="">{t("No shared assistant")}</option>{data.assistants.map((a) => <option key={a.id} value={a.id} disabled={!a.configured}>{a.name} · {a.provider} · {a.model}</option>)}
        </select></label>
        <p className="text-xs leading-6 text-white/45">{t("Free accounts can use only a configured local assistant. Paid users must confirm external processing. No simulated replies are substituted.")}</p>
        <p className="text-xs leading-6 text-white/45">{t("Credits count accepted user turns, not money. Lowering limits does not erase usage. External work already dispatched cannot be recalled.")}</p>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-xs text-white/40">{t("Policy version")}: {selectedPolicy?.version || 0}</span>
          <div className="flex gap-2"><button type="button" onClick={() => void reset()} disabled={busy || !selectedPolicy} className={button}>{t("Reset override")}</button>
            <button type="submit" disabled={busy || !Object.keys(dirty).length || !identifier} className={`${button} bg-electric-500/20`}><Save className="me-2 inline h-4 w-4" />{t("Save policy")}</button></div>
        </div>
      </form>
      <section className="glass-card space-y-4 p-5 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-lg font-semibold">{t("Conversation control")}</h2><Link href="/users" className="text-sm text-electric-300">{t("Account suspension and roles")}</Link></div>
        <div className="flex flex-wrap items-end gap-3"><label className="min-w-64 flex-1 text-sm">{t("User filter")}<select className={input} value={filter} onChange={(e) => setFilter(e.target.value)} disabled={busy}>
          <option value="">{t("All users")}</option>{data.users.map((u) => <option key={u.id} value={u.id}>{u.name} · {u.email}</option>)}
        </select></label><button type="button" className={button} disabled={busy} onClick={() => void inspectUser()}>{t("Inspect usage and conversations")}</button></div>
        {usage && <div className="grid gap-3 rounded-xl border border-white/10 p-4 text-sm sm:grid-cols-3">
          <p>{t("Messages today")}: {usage.usage.day_messages}/{usage.values.messages_per_day}</p>
          <p>{t("Used message credits")}: {usage.usage.total_message_credits}</p>
          <p>{t("Conversation duration in seconds")}: {usage.values.conversation_seconds}</p>
        </div>}
        <label className="block text-sm">{t("Audit note")}<input className={input} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} disabled={busy} /></label>
        {!conversations.length && <p className="py-6 text-sm text-white/50">{t("No conversations match this view.")}</p>}
        <div className="max-h-[40rem] space-y-3 overflow-y-auto">{conversations.map((item) => <article key={item.id} className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-white/10 p-4">
          <div className="min-w-0"><h3 className="break-words font-medium">{item.title}</h3><p className="mt-2 text-xs text-white/45">{data.users.find((u) => u.id === item.user_id)?.name || item.user_id} · {item.messages_used} · {t(item.status === "open" ? "Open" : item.status === "paused" ? "Paused" : "Closed")}</p><p className="mt-1 break-all text-xs text-white/35">{item.project_id}</p></div>
          <div className="flex flex-wrap gap-2"><button type="button" className={button} disabled={busy || item.status !== "open"} onClick={() => void act(item, "pause")}>{t("Pause")}</button>
            <button type="button" className={button} disabled={busy || item.status === "open"} onClick={() => void act(item, "resume")}>{t("Resume")}</button>
            <button type="button" className={button} disabled={busy || item.status === "closed"} onClick={() => void act(item, "close")}>{t("Close")}</button></div>
        </article>)}</div>
      </section>
    </>}
  </div>;
}
