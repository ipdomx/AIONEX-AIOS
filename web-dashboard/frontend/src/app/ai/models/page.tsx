"use client";

import { useEffect, useMemo, useState } from "react";
import { Brain, Search } from "lucide-react";
import { apiClient } from "@/lib/api-client";

type CatalogProvider = { type: string; configured: boolean; enabled: boolean; status: string; models: Array<Record<string, unknown>> };

type ModelRow = { provider: string; model: string; tasks: string[]; supports_tools: boolean; supports_vision: boolean; supports_audio: boolean; local: boolean; max_context_tokens: number };

export default function AIModelsPage() {
  const [providers, setProviders] = useState<CatalogProvider[]>([]);
  const [query, setQuery] = useState("");
  useEffect(() => { apiClient.get<CatalogProvider[]>("/ai/providers/catalog/supported").then(setProviders).catch(() => setProviders([])); }, []);
  const models = useMemo<ModelRow[]>(() => providers.flatMap((p) => p.models.map((raw) => ({ provider: String(raw.provider ?? p.type), model: String(raw.model ?? "unknown"), tasks: Array.isArray(raw.tasks) ? raw.tasks.map(String) : [], supports_tools: Boolean(raw.supports_tools), supports_vision: Boolean(raw.supports_vision), supports_audio: Boolean(raw.supports_audio), local: Boolean(raw.local), max_context_tokens: Number(raw.max_context_tokens ?? 0) }))).filter((m) => `${m.provider} ${m.model} ${m.tasks.join(" ")}`.toLowerCase().includes(query.toLowerCase())), [providers, query]);
  return <div className="space-y-6"><div><h1 className="text-2xl font-bold text-white">AI Models</h1><p className="mt-1 text-sm text-white/40">Discovered model contracts, capabilities, locality and context limits.</p></div><div className="relative max-w-xl"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30"/><input value={query} onChange={(e)=>setQuery(e.target.value)} placeholder="Search models and capabilities..." className="glass-input w-full rounded-xl py-2.5 pl-10 pr-4 text-sm text-white outline-none"/></div><div className="grid gap-4 xl:grid-cols-2">{models.map((m)=><section key={`${m.provider}:${m.model}`} className="glass-card p-5"><div className="flex items-center gap-3"><Brain className="h-5 w-5 text-electric-300"/><div><h2 className="font-semibold text-white">{m.model}</h2><div className="text-xs text-white/40">{m.provider} · {m.local ? "local" : "cloud"}</div></div></div><div className="mt-4 text-xs text-white/45">Tasks: {m.tasks.join(", ") || "not declared"}</div><div className="mt-2 text-xs text-white/45">Tools: {m.supports_tools ? "yes" : "no"} · Vision: {m.supports_vision ? "yes" : "no"} · Audio: {m.supports_audio ? "yes" : "no"}</div><div className="mt-2 text-xs text-white/45">Context: {m.max_context_tokens.toLocaleString()} tokens</div></section>)}</div></div>;
}
