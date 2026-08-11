"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Activity, Loader2, Plus, Plug, RefreshCw, Search, Trash2 } from "lucide-react";

import { apiClient } from "@/lib/api-client";
import { runtimeServices, type ProviderSummary } from "@/lib/runtime-services";

type CatalogProvider = {
  type: string;
  configured: boolean;
  enabled: boolean;
  status: string;
  runtime_mode: string;
  protocol: string;
  reason: string;
  models: Array<Record<string, unknown>>;
};

export default function AIProvidersPage() {
  const [items, setItems] = useState<CatalogProvider[]>([]);
  const [configured, setConfigured] = useState<ProviderSummary[]>([]);
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState("Loading provider catalog...");
  const [busy, setBusy] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [createType, setCreateType] = useState("openai");

  const load = useCallback(async () => {
    try {
      const [catalogRows, configuredRows] = await Promise.all([
        apiClient.get<CatalogProvider[]>("/ai/providers/catalog/supported"),
        runtimeServices.listProviders(),
      ]);
      setItems(catalogRows);
      setConfigured(configuredRows);
      setMessage(
        `Provider catalog synchronized: ${configuredRows.length} configured runtime provider(s).`,
      );
    } catch (error) {
      setItems([]);
      setConfigured([]);
      setMessage(error instanceof Error ? error.message : "Provider catalog is unavailable.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const visible = useMemo(
    () =>
      items.filter((item) =>
        `${item.type} ${item.protocol} ${item.runtime_mode}`.toLowerCase().includes(query.toLowerCase()),
      ),
    [items, query],
  );

  const creatableTypes = useMemo(
    () => items.filter((item) => item.runtime_mode === "agent").map((item) => item.type),
    [items],
  );

  async function createProvider(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const type = String(form.get("type") || "").trim();
    setBusy("create");
    try {
      await runtimeServices.createProvider({
        name: String(form.get("name") || "").trim(),
        type,
        api_key: type === "aws_bedrock" ? "" : String(form.get("api_key") || "").trim(),
        base_url: String(form.get("base_url") || "").trim() || undefined,
      });
      event.currentTarget.reset();
      setShowCreate(false);
      setMessage(`${type} provider created in the durable runtime.`);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Provider creation failed.");
    } finally {
      setBusy(null);
    }
  }

  async function testProvider(provider: ProviderSummary) {
    setBusy(`test:${provider.id}`);
    try {
      const result = await runtimeServices.testProvider(provider.id);
      setMessage(`${provider.name}: ${result.status} · ${result.message}`);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Provider test failed.");
    } finally {
      setBusy(null);
    }
  }

  async function deleteProvider(provider: ProviderSummary) {
    if (provider.managed_by === "server") return;
    if (!window.confirm(`Delete ${provider.name}? Server-managed credentials cannot be deleted here.`)) return;
    setBusy(`delete:${provider.id}`);
    try {
      await runtimeServices.deleteProvider(provider.id);
      setMessage(`${provider.name} deleted.`);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Provider deletion failed.");
    } finally {
      setBusy(null);
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
          <h1 className="text-2xl font-bold tracking-tight text-white">AI Providers</h1>
          <p className="mt-1 text-sm text-white/40">
            Executable provider protocols, truthful activation state, capabilities, and durable credentials.
          </p>
        </div>
        <button type="button" onClick={() => setShowCreate((value) => !value)} className="btn-primary">
          <Plus className="h-4 w-4" />Add provider
        </button>
      </motion.div>

      {showCreate && (
        <form onSubmit={createProvider} className="glass-card grid gap-3 p-5 md:grid-cols-2">
          <input name="name" required maxLength={160} placeholder="Provider display name" className="glass-input rounded-xl px-3 py-2.5 text-sm text-white" />
          <select
            name="type"
            required
            value={createType}
            onChange={(event) => setCreateType(event.target.value)}
            className="glass-input rounded-xl px-3 py-2.5 text-sm text-white"
          >
            {creatableTypes.map((type) => (
              <option key={type} value={type} className="bg-space-800">{type}</option>
            ))}
          </select>
          <input
            name="api_key"
            type="password"
            required={createType !== "ollama" && createType !== "aws_bedrock"}
            disabled={createType === "ollama" || createType === "aws_bedrock"}
            autoComplete="new-password"
            placeholder={createType === "aws_bedrock" ? "Uses protected server AWS credentials" : createType === "ollama" ? "No API key required" : "Provider API key"}
            className="glass-input rounded-xl px-3 py-2.5 text-sm text-white disabled:opacity-45"
          />
          <input
            name="base_url"
            type="url"
            required={createType === "ollama" || createType === "azure_openai"}
            disabled={createType === "aws_bedrock"}
            placeholder={createType === "azure_openai" ? "https://your-resource.openai.azure.com" : createType === "ollama" ? "http://127.0.0.1:11434" : "Optional official HTTPS base URL"}
            className="glass-input rounded-xl px-3 py-2.5 text-sm text-white disabled:opacity-45"
          />
          <div className="text-xs text-white/45 md:col-span-2">
            {createType === "aws_bedrock"
              ? "AWS Bedrock is server-managed and requires protected AWS credentials plus AWS_BEDROCK_REGION."
              : createType === "azure_openai"
                ? "Azure OpenAI requires an Azure AI endpoint and API key."
                : createType === "ollama"
                  ? "Ollama is restricted to a local/private runtime address."
                  : "If base URL is omitted, AIOS uses the provider's pinned official endpoint."}
          </div>
          <button disabled={busy === "create" || !creatableTypes.length} className="btn-primary md:col-span-2">
            {busy === "create" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Create provider
          </button>
        </form>
      )}

      <div className="glass-card p-4">
        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search providers and protocols..." className="glass-input w-full rounded-xl py-2.5 pl-10 pr-4 text-sm text-white outline-none" />
          </div>
          <button type="button" onClick={() => void load()} className="btn-primary">
            <RefreshCw className="h-4 w-4" />Refresh
          </button>
        </div>
        <div className="mt-3 flex items-center gap-2 text-xs text-electric-300"><Activity className="h-3.5 w-3.5" />{message}</div>
      </div>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-white">Configured runtime providers</h2>
        {!configured.length ? (
          <div className="glass-card p-5 text-sm text-white/45">No executable provider is configured for this organization.</div>
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {configured.map((provider) => (
              <div key={provider.id} className="glass-card p-5">
                <div className="flex items-start justify-between gap-4">
                  <div><div className="font-semibold text-white">{provider.name}</div><div className="mt-1 text-xs text-white/40">{provider.type} · {provider.managed_by === "server" ? "server-managed" : "database-managed"}</div></div>
                  <span className="rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-xs text-white/65">{provider.status}</span>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <button type="button" disabled={Boolean(busy) || provider.configured === false} onClick={() => void testProvider(provider)} className="glass rounded-lg px-3 py-2 text-xs text-white/70 disabled:opacity-40">
                    {busy === `test:${provider.id}` ? <Loader2 className="me-1 inline h-3.5 w-3.5 animate-spin" /> : <Activity className="me-1 inline h-3.5 w-3.5" />}
                    Test connection
                  </button>
                  {provider.managed_by !== "server" && (
                    <button type="button" disabled={Boolean(busy)} onClick={() => void deleteProvider(provider)} className="glass rounded-lg px-3 py-2 text-xs text-red-300 disabled:opacity-40">
                      <Trash2 className="me-1 inline h-3.5 w-3.5" />Delete
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-white">Provider capability matrix</h2>
        <div className="grid gap-4 xl:grid-cols-2">
          {visible.map((provider, index) => (
            <motion.section key={provider.type} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.02 }} className="glass-card p-5">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/[0.05]"><Plug className="h-5 w-5 text-electric-300" /></div><div><h3 className="font-semibold text-white">{provider.type}</h3><div className="text-xs text-white/40">{provider.models.length} model contract(s)</div></div></div>
                <span className="rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-xs text-white/65">{provider.configured ? (provider.enabled ? provider.status : "disabled") : provider.status}</span>
              </div>
              <div className="mt-4 grid grid-cols-3 gap-3 text-xs text-white/45"><div>Configured<br/><span className="text-white">{provider.configured ? "yes" : "no"}</span></div><div>Enabled<br/><span className="text-white">{provider.enabled ? "yes" : "no"}</span></div><div>Models<br/><span className="text-white">{provider.models.length}</span></div></div>
              <div className="mt-4 rounded-xl border border-white/10 bg-black/10 p-3 text-xs text-white/50"><div><span className="text-white/70">Runtime:</span> {provider.runtime_mode} · {provider.protocol}</div><div className="mt-1">{provider.reason}</div></div>
            </motion.section>
          ))}
        </div>
      </section>
    </div>
  );
}
