"use client";

import { type FormEvent, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  KeyRound,
  LockKeyhole,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";

import { useOwnerResource } from "@/hooks/use-owner-resource";

type SecretScope = "global" | "organization" | "project" | "service";

type SecretRecord = {
  id: string;
  name: string;
  scope: SecretScope;
  provider: string;
  reference: string;
  status: string;
  lastRotated: string;
  maskedValue: string;
};

type SecretReferenceForm = {
  name: string;
  provider: string;
  scope: SecretScope;
  reference: string;
};

const emptyReference: SecretReferenceForm = {
  name: "",
  provider: "",
  scope: "project",
  reference: "",
};

function statusClass(status: string) {
  if (status === "active")
    return "border-green-500/20 bg-green-500/10 text-green-400";
  if (status === "rotating")
    return "border-blue-500/20 bg-blue-500/10 text-blue-300";
  if (status === "expired")
    return "border-orange-500/20 bg-orange-500/10 text-orange-300";
  return "border-red-500/20 bg-red-500/10 text-red-400";
}

export default function OwnerSecretsPage() {
  const { items, loading, busy, message, execute, create } =
    useOwnerResource<SecretRecord>("secrets");
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<"all" | SecretScope>("all");
  const [showForm, setShowForm] = useState(false);
  const [referenceForm, setReferenceForm] =
    useState<SecretReferenceForm>(emptyReference);

  const filtered = useMemo(
    () =>
      items.filter((secret) => {
        const matchesQuery =
          `${secret.name} ${secret.provider} ${secret.reference}`
            .toLowerCase()
            .includes(query.toLowerCase());
        const matchesScope = scope === "all" || secret.scope === scope;
        return matchesQuery && matchesScope;
      }),
    [items, query, scope],
  );

  function markReferenceRotated(id: string) {
    void execute(id, "rotate");
  }

  function revokeSecretReference(id: string) {
    void execute(id, "revoke");
  }

  async function addSecretReference(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const payload = {
      name: referenceForm.name.trim(),
      provider: referenceForm.provider.trim(),
      scope: referenceForm.scope,
      reference: referenceForm.reference.trim(),
    };
    if (!payload.name || !payload.provider || !payload.reference) return;
    const created = await create(payload);
    if (created) {
      setReferenceForm(emptyReference);
      setShowForm(false);
    }
  }

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between"
      >
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300">
            <LockKeyhole className="h-3.5 w-3.5" /> Owner Secrets &amp; Keys
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            External Secret References
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Owner-only governance for references to credentials held by an
            external vault. Secret values are never entered or stored here.
          </p>
        </div>
        <button
          onClick={() => setShowForm((current) => !current)}
          disabled={busy}
          className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          {showForm ? <X className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
          {showForm ? "Cancel" : "Add external reference"}
        </button>
      </motion.div>

      {showForm && (
        <form
          onSubmit={(event) => void addSecretReference(event)}
          className="glass-card space-y-4 p-5"
        >
          <div>
            <h2 className="text-sm font-semibold text-white">
              Register an external vault reference
            </h2>
            <p className="mt-1 text-xs text-white/40">
              Provide only metadata and the external reference identifier. Do
              not paste a password, token, API key or secret value.
            </p>
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <label className="text-xs text-white/55">
              Name
              <input
                required
                value={referenceForm.name}
                onChange={(event) =>
                  setReferenceForm((current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
                placeholder="OPENAI_API_KEY"
                className="glass-input mt-1 w-full rounded-xl px-4 py-2.5 text-sm text-white outline-none"
              />
            </label>
            <label className="text-xs text-white/55">
              Provider
              <input
                required
                value={referenceForm.provider}
                onChange={(event) =>
                  setReferenceForm((current) => ({
                    ...current,
                    provider: event.target.value,
                  }))
                }
                placeholder="Vault, AWS Secrets Manager..."
                className="glass-input mt-1 w-full rounded-xl px-4 py-2.5 text-sm text-white outline-none"
              />
            </label>
            <label className="text-xs text-white/55">
              Scope
              <select
                value={referenceForm.scope}
                onChange={(event) =>
                  setReferenceForm((current) => ({
                    ...current,
                    scope: event.target.value as SecretScope,
                  }))
                }
                className="glass-input mt-1 w-full rounded-xl px-4 py-2.5 text-sm text-white outline-none"
              >
                <option value="global" className="bg-space-800">
                  Global
                </option>
                <option value="organization" className="bg-space-800">
                  Organization
                </option>
                <option value="project" className="bg-space-800">
                  Project
                </option>
                <option value="service" className="bg-space-800">
                  Service
                </option>
              </select>
            </label>
            <label className="text-xs text-white/55">
              External reference
              <input
                required
                value={referenceForm.reference}
                onChange={(event) =>
                  setReferenceForm((current) => ({
                    ...current,
                    reference: event.target.value,
                  }))
                }
                placeholder="vault://aionex/production/openai"
                className="glass-input mt-1 w-full rounded-xl px-4 py-2.5 text-sm text-white outline-none"
              />
            </label>
          </div>
          <button
            type="submit"
            disabled={
              busy ||
              !referenceForm.name.trim() ||
              !referenceForm.provider.trim() ||
              !referenceForm.reference.trim()
            }
            className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Plus className="h-4 w-4" />
            Save reference
          </button>
        </form>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[
          ["Total", items.length],
          ["Active", items.filter((item) => item.status === "active").length],
          [
            "Rotating",
            items.filter((item) => item.status === "rotating").length,
          ],
          [
            "Needs action",
            items.filter((item) => ["expired", "revoked"].includes(item.status))
              .length,
          ],
        ].map(([label, value]) => (
          <div key={String(label)} className="glass-card p-4">
            <KeyRound className="h-5 w-5 text-electric-300" />
            <div className="mt-3 text-2xl font-bold text-white">
              {String(value)}
            </div>
            <div className="text-xs text-white/35">{String(label)}</div>
          </div>
        ))}
      </div>

      <div className="glass-card p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="relative w-full max-w-xl">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search references and providers..."
              className="glass-input w-full rounded-xl py-2.5 pl-10 pr-4 text-sm text-white outline-none"
            />
          </div>
          <select
            value={scope}
            onChange={(event) => setScope(event.target.value as typeof scope)}
            className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"
          >
            <option value="all" className="bg-space-800">
              All scopes
            </option>
            <option value="global" className="bg-space-800">
              Global
            </option>
            <option value="organization" className="bg-space-800">
              Organization
            </option>
            <option value="project" className="bg-space-800">
              Project
            </option>
            <option value="service" className="bg-space-800">
              Service
            </option>
          </select>
        </div>
        <div className="mt-3 flex items-center gap-2 text-xs text-electric-300">
          <ShieldCheck className="h-3.5 w-3.5" />
          {loading ? "Loading external secret references..." : message}
        </div>
      </div>

      <div className="space-y-3">
        {!loading && filtered.length === 0 && (
          <div className="glass-card p-6 text-sm text-white/45">
            No external secret references match the current filters.
          </div>
        )}
        {filtered.map((secret, index) => (
          <motion.div
            key={secret.id}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.03 }}
            className="glass-card p-5"
          >
            <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
              <div>
                <h2 className="text-sm font-semibold text-white">
                  {secret.name}
                </h2>
                <p className="mt-1 text-xs text-white/40">
                  {secret.provider} · {secret.scope} · Last rotated{" "}
                  {secret.lastRotated}
                </p>
                <code className="mt-2 inline-block rounded-lg bg-black/20 px-3 py-1.5 text-xs text-white/50">
                  {secret.reference}
                </code>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={`rounded-full border px-2.5 py-1 text-xs ${statusClass(
                    secret.status,
                  )}`}
                >
                  {secret.status}
                </span>
                <button
                  onClick={() => markReferenceRotated(secret.id)}
                  disabled={busy || secret.status === "revoked"}
                  className="rounded-lg border border-blue-500/20 bg-blue-500/10 px-3 py-2 text-xs text-blue-300 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <RefreshCw className="mr-1 inline h-3.5 w-3.5" />
                  Record rotation
                </button>
                <button
                  onClick={() => revokeSecretReference(secret.id)}
                  disabled={busy || secret.status === "revoked"}
                  className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-300 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Trash2 className="mr-1 inline h-3.5 w-3.5" />
                  Revoke reference
                </button>
              </div>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
