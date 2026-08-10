"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Bot,
  CheckCircle2,
  Clock,
  Loader2,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  XCircle,
} from "lucide-react";

import {
  runtimeServices,
  type AgentSummary,
  type ProviderSummary,
} from "@/lib/runtime-services";

export default function AIAgentsPage() {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [providers, setProviders] = useState<ProviderSummary[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("Loading durable AI agent state...");
  const [showCreate, setShowCreate] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [agentRows, providerRows] = await Promise.all([
        runtimeServices.listAgents({ limit: 100 }),
        runtimeServices.listProviders(),
      ]);
      setAgents(agentRows);
      setProviders(providerRows);
      setMessage(
        `Synchronized ${agentRows.length} agent(s) and ${providerRows.length} configured provider(s).`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "AI runtime load failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const filteredAgents = useMemo(
    () =>
      agents.filter((agent) => {
        const needle = searchQuery.toLowerCase();
        const matchesSearch =
          !needle ||
          agent.name.toLowerCase().includes(needle) ||
          agent.role.toLowerCase().includes(needle) ||
          agent.provider.toLowerCase().includes(needle) ||
          agent.model.toLowerCase().includes(needle);
        const matchesStatus = statusFilter === "all" || agent.status === statusFilter;
        return matchesSearch && matchesStatus;
      }),
    [agents, searchQuery, statusFilter],
  );

  async function createAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy("create");
    try {
      await runtimeServices.createAgent({
        name: String(form.get("name") || "").trim(),
        role: String(form.get("role") || "").trim(),
        department: String(form.get("department") || "").trim(),
        provider_id: String(form.get("provider_id") || ""),
        model: String(form.get("model") || "").trim(),
        system_prompt: String(form.get("system_prompt") || "").trim() || undefined,
      });
      event.currentTarget.reset();
      setShowCreate(false);
      setMessage("Agent created in the durable runtime.");
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Agent creation failed");
    } finally {
      setBusy(null);
    }
  }

  async function execute(agent: AgentSummary) {
    const prompt = window.prompt(`Execution prompt for ${agent.name}`)?.trim();
    if (!prompt) return;
    setBusy(`execute:${agent.id}`);
    try {
      const job = await runtimeServices.executeAgent(agent.id, prompt);
      setMessage(`Execution ${job.id} queued. Refresh to observe durable status.`);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Agent execution failed");
    } finally {
      setBusy(null);
    }
  }

  async function togglePause(agent: AgentSummary) {
    setBusy(`state:${agent.id}`);
    try {
      const nextStatus = agent.status === "paused" ? "idle" : "paused";
      await runtimeServices.updateAgent(agent.id, { status: nextStatus });
      setMessage(`${agent.name} is now ${nextStatus}.`);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Agent state update failed");
    } finally {
      setBusy(null);
    }
  }

  async function remove(agent: AgentSummary) {
    if (!window.confirm(`Delete ${agent.name}? This audited action cannot be undone.`)) return;
    setBusy(`delete:${agent.id}`);
    try {
      await runtimeServices.deleteAgent(agent.id);
      setMessage(`${agent.name} deleted.`);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Agent deletion failed");
    } finally {
      setBusy(null);
    }
  }

  function statusClass(status: string) {
    switch (status) {
      case "running":
        return "bg-green-500/10 text-green-400 border-green-500/20";
      case "idle":
        return "bg-blue-500/10 text-blue-400 border-blue-500/20";
      case "paused":
        return "bg-orange-500/10 text-orange-400 border-orange-500/20";
      case "error":
        return "bg-red-500/10 text-red-400 border-red-500/20";
      default:
        return "bg-white/10 text-white/40 border-white/20";
    }
  }

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"
      >
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">AI Agents</h1>
          <p className="mt-1 text-sm text-white/40">
            Durable provider-backed agents. No local placeholder state or synthetic execution success.
          </p>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={() => void load()} disabled={loading} className="glass rounded-xl px-3 py-2 text-sm text-white/70 disabled:opacity-50">
            <RefreshCw className="me-2 inline h-4 w-4" />Refresh
          </button>
          <button type="button" onClick={() => setShowCreate((value) => !value)} className="btn-primary">
            <Plus className="h-4 w-4" />New Agent
          </button>
        </div>
      </motion.div>

      <div className="glass-card p-4 text-sm text-white/60">{message}</div>

      {showCreate && (
        <form onSubmit={createAgent} className="glass-card grid gap-3 p-5 md:grid-cols-2">
          <input name="name" required maxLength={200} placeholder="Agent name" className="glass-input rounded-xl px-3 py-2.5 text-sm text-white" />
          <input name="role" required maxLength={120} placeholder="Role" className="glass-input rounded-xl px-3 py-2.5 text-sm text-white" />
          <input name="department" required maxLength={120} placeholder="Department" className="glass-input rounded-xl px-3 py-2.5 text-sm text-white" />
          <select name="provider_id" required className="glass-input rounded-xl px-3 py-2.5 text-sm text-white">
            <option value="" className="bg-space-800">Select configured provider</option>
            {providers.filter((provider) => provider.configured !== false && provider.enabled).map((provider) => (
              <option key={provider.id} value={provider.id} className="bg-space-800">{provider.name} · {provider.type}</option>
            ))}
          </select>
          <input name="model" required maxLength={160} placeholder="Exact provider model ID" className="glass-input rounded-xl px-3 py-2.5 text-sm text-white" />
          <input name="system_prompt" maxLength={20000} placeholder="Optional system prompt" className="glass-input rounded-xl px-3 py-2.5 text-sm text-white" />
          <button disabled={busy === "create" || !providers.some((provider) => provider.enabled && provider.configured !== false)} className="btn-primary md:col-span-2">
            {busy === "create" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}Create durable agent
          </button>
        </form>
      )}

      <div className="glass-card p-4">
        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" />
            <input value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="Search agents..." className="glass-input w-full rounded-xl py-2.5 pl-10 pr-4 text-sm text-white outline-none" />
          </div>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none">
            <option value="all" className="bg-space-800">All statuses</option>
            <option value="running" className="bg-space-800">Running</option>
            <option value="idle" className="bg-space-800">Idle</option>
            <option value="paused" className="bg-space-800">Paused</option>
            <option value="error" className="bg-space-800">Error</option>
          </select>
        </div>
      </div>

      {loading ? (
        <div className="glass-card flex min-h-48 items-center justify-center text-white/45"><Loader2 className="me-2 h-5 w-5 animate-spin" />Loading durable agents…</div>
      ) : !filteredAgents.length ? (
        <div className="glass-card p-8 text-center text-sm text-white/45">No durable agents match the current filter.</div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
          {filteredAgents.map((agent, index) => (
            <motion.section key={agent.id} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.03 }} className="glass-card p-5">
              <div className="mb-4 flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-white/[0.08] bg-gradient-to-br from-purple-500/20 to-blue-500/20"><Bot className="h-5 w-5 text-purple-400" /></div>
                  <div><h2 className="text-sm font-semibold text-white">{agent.name}</h2><p className="text-xs text-white/40">{agent.role} · {agent.department}</p></div>
                </div>
                <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${statusClass(agent.status)}`}>{agent.status}</span>
              </div>
              <div className="mb-4 grid grid-cols-2 gap-3">
                <div className="rounded-lg bg-white/[0.02] p-2.5"><div className="mb-1 flex items-center gap-1.5"><CheckCircle2 className="h-3 w-3 text-green-400" /><span className="text-[10px] uppercase tracking-wider text-white/40">Completed</span></div><span className="text-sm font-bold text-white">{agent.tasks_completed.toLocaleString()}</span></div>
                <div className="rounded-lg bg-white/[0.02] p-2.5"><div className="mb-1 flex items-center gap-1.5"><XCircle className="h-3 w-3 text-red-400" /><span className="text-[10px] uppercase tracking-wider text-white/40">Failed</span></div><span className="text-sm font-bold text-white">{agent.tasks_failed.toLocaleString()}</span></div>
                <div className="rounded-lg bg-white/[0.02] p-2.5"><div className="mb-1 flex items-center gap-1.5"><Clock className="h-3 w-3 text-orange-400" /><span className="text-[10px] uppercase tracking-wider text-white/40">Latency</span></div><span className="text-sm font-bold text-white">{agent.latency} ms</span></div>
                <div className="rounded-lg bg-white/[0.02] p-2.5"><div className="mb-1 text-[10px] uppercase tracking-wider text-white/40">Tokens</div><span className="text-sm font-bold text-white">{agent.tokens_used.toLocaleString()}</span></div>
              </div>
              <div className="mb-3 text-xs text-white/35">{agent.provider} · {agent.model}</div>
              <div className="flex gap-2 border-t border-white/[0.06] pt-3">
                <button type="button" disabled={Boolean(busy) || agent.status === "paused" || agent.status === "disabled"} onClick={() => void execute(agent)} className="glass flex flex-1 items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-xs text-white/70 disabled:opacity-35"><Play className="h-3.5 w-3.5" />Execute</button>
                <button type="button" disabled={Boolean(busy) || agent.status === "running"} onClick={() => void togglePause(agent)} className="glass flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs text-white/70 disabled:opacity-35"><Pause className="h-3.5 w-3.5" />{agent.status === "paused" ? "Resume" : "Pause"}</button>
                <button type="button" disabled={Boolean(busy) || agent.status === "running"} onClick={() => void remove(agent)} className="glass rounded-lg p-2 text-red-300 disabled:opacity-35" aria-label={`Delete ${agent.name}`}><Trash2 className="h-3.5 w-3.5" /></button>
              </div>
            </motion.section>
          ))}
        </div>
      )}
    </div>
  );
}
