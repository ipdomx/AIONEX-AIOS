"use client";

import { useMemo, useState, type FormEvent } from "react";
import { motion } from "framer-motion";
import {
  CheckCircle2,
  FileCog,
  PauseCircle,
  PlayCircle,
  Plus,
  Search,
  ShieldCheck,
} from "lucide-react";

import { useOwnerResource } from "@/hooks/use-owner-resource";

type PolicyStatus = "active" | "draft" | "paused";
type PolicyScope = "global" | "organization" | "project";

type Policy = {
  id: string;
  name: string;
  description: string;
  scope: PolicyScope;
  target: string;
  status: PolicyStatus;
  enforcement: "mandatory" | "advisory";
};

const statusClass: Record<PolicyStatus, string> = {
  active: "border-green-500/20 bg-green-500/10 text-green-400",
  draft: "border-blue-500/20 bg-blue-500/10 text-blue-300",
  paused: "border-orange-500/20 bg-orange-500/10 text-orange-300",
};

export default function OwnerPoliciesPage() {
  const {
    items: policies,
    loading,
    busy,
    message,
    execute,
    create,
  } = useOwnerResource<Policy>("policies");
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<"all" | PolicyScope>("all");
  const [showCreateForm, setShowCreateForm] = useState(false);

  const visible = useMemo(
    () =>
      policies.filter((policy) => {
        const matchesQuery =
          policy.name.toLowerCase().includes(query.toLowerCase()) ||
          policy.description.toLowerCase().includes(query.toLowerCase());
        const matchesScope = scope === "all" || policy.scope === scope;
        return matchesQuery && matchesScope;
      }),
    [policies, query, scope],
  );

  async function addPolicy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const succeeded = await create({
      name: String(data.get("name") ?? "").trim(),
      description: String(data.get("description") ?? "").trim(),
      scope: String(data.get("scope") ?? "global"),
      target: String(data.get("target") ?? "").trim(),
      enforcement: String(data.get("enforcement") ?? "mandatory"),
      status: "draft",
    });
    if (succeeded) {
      form.reset();
      setShowCreateForm(false);
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
            <ShieldCheck className="h-3.5 w-3.5" /> Owner Policy Registry
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Global Governance Policies
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Create, approve, pause and audit durable governance declarations.
            Automated enforcement applies only in consumers that explicitly
            integrate the recorded policy.
          </p>
        </div>
        <button
          disabled={busy}
          onClick={() => setShowCreateForm((current) => !current)}
          className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus className="h-4 w-4" />
          {showCreateForm ? "Cancel" : "New policy"}
        </button>
      </motion.div>

      {showCreateForm && (
        <form
          onSubmit={(event) => void addPolicy(event)}
          className="glass-card grid gap-3 p-5 md:grid-cols-2"
        >
          <div className="md:col-span-2">
            <h2 className="text-sm font-semibold text-white">
              Create owner policy
            </h2>
            <p className="mt-1 text-xs text-white/35">
              The policy will be persisted as a draft and can be activated after
              review.
            </p>
          </div>
          <input
            required
            minLength={2}
            name="name"
            placeholder="Policy name"
            className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"
          />
          <input
            required
            minLength={2}
            name="target"
            placeholder="Target"
            className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"
          />
          <textarea
            required
            minLength={3}
            name="description"
            placeholder="Description"
            className="glass-input min-h-24 rounded-xl px-4 py-2.5 text-sm text-white outline-none md:col-span-2"
          />
          <select
            name="scope"
            defaultValue="global"
            className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"
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
          </select>
          <select
            name="enforcement"
            defaultValue="mandatory"
            className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"
          >
            <option value="mandatory" className="bg-space-800">
              Mandatory
            </option>
            <option value="advisory" className="bg-space-800">
              Advisory
            </option>
          </select>
          <button
            disabled={busy}
            type="submit"
            className="btn-primary md:col-span-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Plus className="h-4 w-4" />
            Create draft policy
          </button>
        </form>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[
          ["Total Policies", policies.length],
          [
            "Active",
            policies.filter((item) => item.status === "active").length,
          ],
          ["Draft", policies.filter((item) => item.status === "draft").length],
          [
            "Mandatory",
            policies.filter((item) => item.enforcement === "mandatory").length,
          ],
        ].map(([label, value]) => (
          <div key={String(label)} className="glass-card p-4">
            <div className="text-2xl font-bold text-white">{String(value)}</div>
            <div className="mt-1 text-xs text-white/35">{String(label)}</div>
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
              placeholder="Search policies..."
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
          </select>
        </div>
        <div className="mt-3 flex items-center gap-2 text-xs text-electric-300">
          <FileCog className="h-3.5 w-3.5" />
          {message}
        </div>
      </div>

      <div className="space-y-3">
        {loading ? (
          <div className="glass-card p-8 text-center text-sm text-white/40">
            Loading live policies…
          </div>
        ) : visible.length === 0 ? (
          <div className="glass-card p-8 text-center text-sm text-white/40">
            No policies match the selected filters.
          </div>
        ) : (
          visible.map((policy, index) => (
            <motion.div
              key={policy.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.03 }}
              className="glass-card p-5"
            >
              <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                <div className="max-w-3xl">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-electric-300" />
                    <h2 className="text-sm font-semibold text-white">
                      {policy.name}
                    </h2>
                  </div>
                  <p className="mt-2 text-xs leading-relaxed text-white/40">
                    {policy.description}
                  </p>
                  <p className="mt-2 text-xs text-white/30">
                    Scope: {policy.scope} · Target: {policy.target} · Declared
                    mode: {policy.enforcement}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`rounded-full border px-2.5 py-1 text-xs ${statusClass[policy.status]}`}
                  >
                    {policy.status}
                  </span>
                  <button
                    disabled={busy || policy.status === "active"}
                    onClick={() => void execute(policy.id, "activate")}
                    className="rounded-lg border border-green-500/20 bg-green-500/10 px-3 py-2 text-xs text-green-300 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <PlayCircle className="mr-1 inline h-3.5 w-3.5" />
                    Activate
                  </button>
                  <button
                    disabled={busy || policy.status === "paused"}
                    onClick={() => void execute(policy.id, "pause")}
                    className="rounded-lg border border-orange-500/20 bg-orange-500/10 px-3 py-2 text-xs text-orange-300 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <PauseCircle className="mr-1 inline h-3.5 w-3.5" />
                    Pause
                  </button>
                </div>
              </div>
            </motion.div>
          ))
        )}
      </div>
    </div>
  );
}
