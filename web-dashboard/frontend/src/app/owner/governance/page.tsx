"use client";

import { useState, type FormEvent } from "react";
import { motion } from "framer-motion";
import {
  CheckCircle2,
  Gavel,
  Landmark,
  Plus,
  Shield,
  XCircle,
} from "lucide-react";

import { useOwnerResource } from "@/hooks/use-owner-resource";

type GovernanceItem = {
  id: string;
  name: string;
  kind: string;
  status: "active" | "restricted" | "pending" | "approved" | "rejected";
  title: string;
  body: string;
};

export default function OwnerGovernancePage() {
  const { items, loading, busy, message, execute, create } =
    useOwnerResource<GovernanceItem>("governance");
  const [creating, setCreating] = useState(false);

  async function submitDecision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const name = String(form.get("name") ?? "").trim();
    const title = String(form.get("title") ?? "").trim();
    const body = String(form.get("body") ?? "").trim();
    if (name.length < 2 || title.length < 2) return;
    const created = await create({
      name,
      kind: "Owner decision",
      title,
      body,
      status: "pending",
    });
    if (created) {
      formElement.reset();
      setCreating(false);
    }
  }

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between"
      >
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-amber-500/20 bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-300">
            <Gavel className="h-3.5 w-3.5" />
            Owner Governance
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Owner Decision Registry
          </h1>
          <p className="mt-2 max-w-3xl text-sm text-white/45">
            Create durable owner decision records and persist their approval or
            rejection state.
          </p>
        </div>
        <button
          disabled={busy}
          onClick={() => setCreating((current) => !current)}
          className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus className="h-4 w-4" />
          New decision
        </button>
      </motion.div>

      {creating && (
        <form
          onSubmit={(event) => void submitDecision(event)}
          className="glass-card grid gap-3 p-5 lg:grid-cols-2"
        >
          <input
            name="name"
            required
            minLength={2}
            placeholder="Decision owner or body"
            className="glass-input rounded-xl px-4 py-3 text-sm text-white outline-none"
          />
          <input
            name="title"
            required
            minLength={2}
            placeholder="Decision title"
            className="glass-input rounded-xl px-4 py-3 text-sm text-white outline-none"
          />
          <textarea
            name="body"
            placeholder="Context for the owner decision"
            rows={3}
            className="glass-input rounded-xl px-4 py-3 text-sm text-white outline-none lg:col-span-2"
          />
          <button
            disabled={busy}
            type="submit"
            className="btn-primary w-fit disabled:cursor-not-allowed disabled:opacity-50"
          >
            Save decision
          </button>
        </form>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-4">
        {loading ? (
          <div className="glass-card p-8 text-center text-sm text-white/40 lg:col-span-2 xl:col-span-4">
            Loading live governance records…
          </div>
        ) : (
          items.map((body, index) => (
            <motion.section
              key={body.id}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.04 }}
              className="glass-card p-5"
            >
              <div className="flex items-center justify-between">
                <div className="rounded-xl bg-amber-500/10 p-2.5">
                  <Landmark className="h-5 w-5 text-amber-300" />
                </div>
                <span
                  className={`text-xs ${body.status === "active" ? "text-green-400" : "text-orange-400"}`}
                >
                  {body.status}
                </span>
              </div>
              <h2 className="mt-4 text-sm font-semibold text-white">
                {body.name}
              </h2>
              <p className="mt-1 text-xs text-white/35">{body.kind}</p>
              <p className="mt-4 text-xs leading-5 text-white/45">
                {body.title || body.body || "Owner decision record"}
              </p>
            </motion.section>
          ))
        )}
      </div>

      <section className="glass-card p-5">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-white">
              Owner Decision Queue
            </h2>
            <p className="mt-1 text-xs text-white/35">
              Durable owner decisions with explicit approval and rejection
              state.
            </p>
          </div>
          <Shield className="h-5 w-5 text-amber-300" />
        </div>
        <div className="mb-4 text-xs text-electric-300">{message}</div>
        <div className="space-y-3">
          {items.length === 0 && !loading ? (
            <div className="py-6 text-center text-sm text-white/40">
              No governance decisions are configured.
            </div>
          ) : (
            items.map((decision) => (
              <div
                key={decision.id}
                className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-4"
              >
                <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                  <div>
                    <h3 className="text-sm font-medium text-white">
                      {decision.title}
                    </h3>
                    <p className="mt-1 text-xs text-white/40">
                      {decision.body || "No additional context provided."}
                    </p>
                  </div>
                  {decision.status === "pending" ? (
                    <div className="flex gap-2">
                      <button
                        disabled={busy}
                        onClick={() => void execute(decision.id, "approve")}
                        className="inline-flex items-center gap-2 rounded-lg bg-green-500/15 px-3 py-2 text-xs text-green-300 hover:bg-green-500/20 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <CheckCircle2 className="h-4 w-4" />
                        Approve
                      </button>
                      <button
                        disabled={busy}
                        onClick={() => void execute(decision.id, "reject")}
                        className="inline-flex items-center gap-2 rounded-lg bg-red-500/15 px-3 py-2 text-xs text-red-300 hover:bg-red-500/20 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <XCircle className="h-4 w-4" />
                        Reject
                      </button>
                    </div>
                  ) : (
                    <span
                      className={`rounded-full px-3 py-1 text-xs ${decision.status === "active" || decision.status === "approved" ? "bg-green-500/10 text-green-400" : "bg-red-500/10 text-red-400"}`}
                    >
                      {decision.status}
                    </span>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="glass-card p-5">
        <div className="flex items-center gap-3">
          <Shield className="h-5 w-5 text-amber-300" />
          <div>
            <h2 className="text-sm font-semibold text-white">
              Governance Guardrails
            </h2>
            <p className="mt-1 text-xs text-white/40">
              This registry persists owner decisions. Each operational module
              remains responsible for enforcing its own protected actions.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
