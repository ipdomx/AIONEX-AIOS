"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import { motion } from "framer-motion";
import {
  Building2,
  CheckCircle2,
  FileCheck2,
  Gavel,
  Landmark,
  LoaderCircle,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
} from "lucide-react";

import {
  createGovernanceBody,
  createGovernanceDecision,
  createGovernancePolicy,
  fetchGovernanceBodies,
  fetchGovernanceDecisions,
  fetchGovernancePolicies,
  retireGovernancePolicy,
  submitGovernanceDecision,
  submitGovernancePolicy,
  type GovernanceBody,
  type GovernanceDecision,
  type GovernancePolicy,
} from "@/lib/governance-api";
import {
  fetchGovernanceOverview,
  type GovernanceOverview,
} from "@/lib/owner-communications";

type Tab = "bodies" | "policies" | "decisions";

const inputClass =
  "glass-input rounded-xl px-3 py-2 text-sm text-white outline-none disabled:cursor-not-allowed disabled:opacity-50";
const buttonClass =
  "inline-flex items-center justify-center gap-2 rounded-xl border border-electric-500/20 bg-electric-500/10 px-3 py-2 text-xs font-semibold text-electric-200 transition hover:bg-electric-500/15 disabled:cursor-not-allowed disabled:opacity-50";

function dateValue(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function statusClass(status: string): string {
  if (["active", "approved"].includes(status)) {
    return "border-green-500/20 bg-green-500/10 text-green-300";
  }
  if (["rejected", "retired"].includes(status)) {
    return "border-red-500/20 bg-red-500/10 text-red-300";
  }
  return "border-amber-500/20 bg-amber-500/10 text-amber-200";
}

export default function OwnerGovernancePage() {
  const [overview, setOverview] = useState<GovernanceOverview | null>(null);
  const [bodies, setBodies] = useState<GovernanceBody[]>([]);
  const [policies, setPolicies] = useState<GovernancePolicy[]>([]);
  const [decisions, setDecisions] = useState<GovernanceDecision[]>([]);
  const [tab, setTab] = useState<Tab>("bodies");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Loading durable governance records…");

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const [nextOverview, nextBodies, nextPolicies, nextDecisions] =
        await Promise.all([
          fetchGovernanceOverview(signal),
          fetchGovernanceBodies(signal),
          fetchGovernancePolicies(signal),
          fetchGovernanceDecisions(signal),
        ]);
      setOverview(nextOverview);
      setBodies(nextBodies);
      setPolicies(nextPolicies);
      setDecisions(nextDecisions);
      setMessage("Councils, ministries, policies, and decisions synchronized.");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setMessage(
          error instanceof Error
            ? error.message
            : "Governance records could not be loaded.",
        );
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  async function perform(label: string, action: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    setMessage(`${label}…`);
    try {
      await action();
      await load();
      setMessage(`${label} completed and retained in the audit trail.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : `${label} failed.`);
    } finally {
      setBusy(false);
    }
  }

  function createBody(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const parentId = String(form.get("parent_id") || "");
    void perform("Creating governance body", async () => {
      await createGovernanceBody({
        name: String(form.get("name") || ""),
        kind: String(form.get("kind") || "council") as GovernanceBody["kind"],
        charter: String(form.get("charter") || "") || undefined,
        jurisdiction: String(form.get("jurisdiction") || "") || undefined,
        quorum: Number(form.get("quorum") || 1),
        parent_id: parentId || null,
      });
      formElement.reset();
    });
  }

  function createPolicy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const bodyId = String(form.get("body_id") || "");
    void perform("Creating governance policy", async () => {
      await createGovernancePolicy({
        code: String(form.get("code") || ""),
        title: String(form.get("title") || ""),
        description: String(form.get("description") || "") || undefined,
        body_id: bodyId || null,
        scope: String(form.get("scope") || "organization"),
        enforcement: String(form.get("enforcement") || "mandatory") as
          "mandatory" | "advisory" | "informational",
        policy: { source: "owner-dashboard" },
      });
      formElement.reset();
    });
  }

  function createDecision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const bodyId = String(form.get("body_id") || "");
    const policyId = String(form.get("policy_id") || "");
    void perform("Creating governance decision", async () => {
      await createGovernanceDecision({
        title: String(form.get("title") || ""),
        rationale: String(form.get("rationale") || "") || undefined,
        body_id: bodyId || null,
        policy_id: policyId || null,
        decision: { source: "owner-dashboard" },
      });
      formElement.reset();
    });
  }

  const pending = useMemo(
    () =>
      policies.filter((item) => ["draft", "pending"].includes(item.status))
        .length +
      decisions.filter((item) =>
        ["draft", "pending", "voting", "changes_requested"].includes(
          item.status,
        ),
      ).length,
    [decisions, policies],
  );

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between"
      >
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-amber-500/20 bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-300">
            <Gavel className="h-3.5 w-3.5" /> Owner Governance
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Councils, Ministries, Policies & Decisions
          </h1>
          <p className="mt-2 max-w-3xl text-sm text-white/45">
            Durable governance bodies, weighted quorum, policy lifecycle, change
            requests, rejection, and final Owner ratification.
          </p>
        </div>
        <button
          disabled={loading || busy}
          onClick={() => void load()}
          className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh evidence
        </button>
      </motion.div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {[
          ["Governance bodies", overview?.bodies || bodies.length, Landmark],
          ["Policies", overview?.policies || policies.length, FileCheck2],
          ["Decisions", overview?.decisions || decisions.length, Gavel],
          ["Pending approvals", overview?.pending_approvals || 0, ShieldCheck],
          ["Open governance work", pending, LoaderCircle],
        ].map(([label, value, Icon]) => {
          const CardIcon = Icon as React.ElementType;
          return (
            <div key={String(label)} className="glass-card p-5">
              <CardIcon className="h-5 w-5 text-amber-300" />
              <p className="mt-3 text-2xl font-bold text-white">
                {String(value)}
              </p>
              <p className="mt-1 text-xs text-white/35">{String(label)}</p>
            </div>
          );
        })}
      </div>

      <div className="glass-card p-4 text-xs text-electric-300">{message}</div>

      <div className="flex flex-wrap gap-2">
        {(["bodies", "policies", "decisions"] as Tab[]).map((value) => (
          <button
            key={value}
            onClick={() => setTab(value)}
            className={`rounded-xl border px-4 py-2 text-xs font-medium capitalize ${tab === value ? "border-amber-500/25 bg-amber-500/10 text-amber-200" : "border-white/[0.07] bg-white/[0.03] text-white/45"}`}
          >
            {value}
          </button>
        ))}
      </div>

      {tab === "bodies" && (
        <div className="grid gap-5 xl:grid-cols-[.8fr_1.2fr]">
          <form onSubmit={createBody} className="glass-card space-y-3 p-5">
            <h2 className="text-sm font-semibold text-white">
              Create council or ministry
            </h2>
            <input
              name="name"
              required
              minLength={2}
              placeholder="Governance body name"
              className={`${inputClass} w-full`}
            />
            <div className="grid gap-3 sm:grid-cols-2">
              <select name="kind" className={inputClass} defaultValue="council">
                <option value="council">Council</option>
                <option value="ministry">Ministry</option>
                <option value="committee">Committee</option>
                <option value="department">Department</option>
                <option value="board">Board</option>
              </select>
              <input
                name="quorum"
                type="number"
                min={1}
                defaultValue={1}
                className={inputClass}
              />
            </div>
            <select name="parent_id" className={`${inputClass} w-full`}>
              <option value="">No parent body</option>
              {bodies.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            <input
              name="jurisdiction"
              placeholder="Jurisdiction"
              className={`${inputClass} w-full`}
            />
            <textarea
              name="charter"
              rows={4}
              placeholder="Charter and responsibilities"
              className={`${inputClass} w-full`}
            />
            <button disabled={busy} type="submit" className={buttonClass}>
              <Plus className="h-4 w-4" /> Create governance body
            </button>
          </form>
          <div className="grid gap-3 sm:grid-cols-2">
            {bodies.map((item) => (
              <article key={item.id} className="glass-card p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="rounded-xl bg-amber-500/10 p-2.5">
                    {item.kind === "ministry" ? (
                      <Building2 className="h-5 w-5 text-amber-300" />
                    ) : (
                      <Landmark className="h-5 w-5 text-amber-300" />
                    )}
                  </div>
                  <span
                    className={`rounded-full border px-2 py-0.5 text-[10px] ${statusClass(item.status)}`}
                  >
                    {item.status}
                  </span>
                </div>
                <h3 className="mt-4 text-sm font-semibold text-white">
                  {item.name}
                </h3>
                <p className="mt-1 text-xs text-white/35">
                  {item.kind} · quorum {item.quorum}
                </p>
                <p className="mt-3 text-xs leading-5 text-white/45">
                  {item.charter || "No charter recorded."}
                </p>
              </article>
            ))}
          </div>
        </div>
      )}

      {tab === "policies" && (
        <div className="grid gap-5 xl:grid-cols-[.8fr_1.2fr]">
          <form onSubmit={createPolicy} className="glass-card space-y-3 p-5">
            <h2 className="text-sm font-semibold text-white">
              Create governed policy
            </h2>
            <div className="grid gap-3 sm:grid-cols-2">
              <input
                name="code"
                required
                minLength={2}
                placeholder="Policy code"
                className={inputClass}
              />
              <input
                name="title"
                required
                minLength={2}
                placeholder="Policy title"
                className={inputClass}
              />
            </div>
            <select name="body_id" className={`${inputClass} w-full`}>
              <option value="">Organization-wide Owner policy</option>
              {bodies.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            <div className="grid gap-3 sm:grid-cols-2">
              <input
                name="scope"
                defaultValue="organization"
                className={inputClass}
              />
              <select
                name="enforcement"
                className={inputClass}
                defaultValue="mandatory"
              >
                <option value="mandatory">Mandatory</option>
                <option value="advisory">Advisory</option>
                <option value="informational">Informational</option>
              </select>
            </div>
            <textarea
              name="description"
              rows={4}
              placeholder="Policy purpose and rules"
              className={`${inputClass} w-full`}
            />
            <button disabled={busy} type="submit" className={buttonClass}>
              <Plus className="h-4 w-4" /> Create policy
            </button>
          </form>
          <div className="space-y-3">
            {policies.map((item) => (
              <article key={item.id} className="glass-card p-5">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-semibold text-white">
                        {item.code} · {item.title}
                      </h3>
                      <span
                        className={`rounded-full border px-2 py-0.5 text-[10px] ${statusClass(item.status)}`}
                      >
                        {item.status}
                      </span>
                    </div>
                    <p className="mt-2 text-xs leading-5 text-white/45">
                      {item.description || "No policy description recorded."}
                    </p>
                    <p className="mt-2 text-[11px] text-white/30">
                      {item.scope} · {item.enforcement} · version {item.version}{" "}
                      · {dateValue(item.updated_at)}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      disabled={
                        busy ||
                        !["draft", "changes_requested", "rejected"].includes(
                          item.status,
                        )
                      }
                      onClick={() =>
                        void perform("Submitting governance policy", () =>
                          submitGovernancePolicy(item.id),
                        )
                      }
                      className={buttonClass}
                    >
                      <Send className="h-3.5 w-3.5" /> Submit for approval
                    </button>
                    <button
                      disabled={busy || item.status !== "active"}
                      onClick={() =>
                        void perform("Retiring governance policy", () =>
                          retireGovernancePolicy(item.id),
                        )
                      }
                      className="inline-flex items-center gap-2 rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-300 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      Retire
                    </button>
                  </div>
                </div>
              </article>
            ))}
          </div>
        </div>
      )}

      {tab === "decisions" && (
        <div className="grid gap-5 xl:grid-cols-[.8fr_1.2fr]">
          <form onSubmit={createDecision} className="glass-card space-y-3 p-5">
            <h2 className="text-sm font-semibold text-white">
              Create governance decision
            </h2>
            <input
              name="title"
              required
              minLength={2}
              placeholder="Decision title"
              className={`${inputClass} w-full`}
            />
            <select name="body_id" className={`${inputClass} w-full`}>
              <option value="">Direct Owner decision</option>
              {bodies.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            <select name="policy_id" className={`${inputClass} w-full`}>
              <option value="">No linked policy</option>
              {policies.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.code} · {item.title}
                </option>
              ))}
            </select>
            <textarea
              name="rationale"
              rows={5}
              placeholder="Decision rationale and retained evidence"
              className={`${inputClass} w-full`}
            />
            <button disabled={busy} type="submit" className={buttonClass}>
              <Plus className="h-4 w-4" /> Create decision
            </button>
          </form>
          <div className="space-y-3">
            {decisions.map((item) => (
              <article key={item.id} className="glass-card p-5">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-semibold text-white">
                        {item.title}
                      </h3>
                      <span
                        className={`rounded-full border px-2 py-0.5 text-[10px] ${statusClass(item.status)}`}
                      >
                        {item.status}
                      </span>
                    </div>
                    <p className="mt-2 text-xs leading-5 text-white/45">
                      {item.rationale || "No rationale recorded."}
                    </p>
                    <p className="mt-2 text-[11px] text-white/30">
                      {item.body_id
                        ? "Weighted body vote"
                        : "Direct Owner review"}{" "}
                      · {dateValue(item.updated_at)}
                    </p>
                  </div>
                  <button
                    disabled={
                      busy ||
                      !["draft", "changes_requested", "rejected"].includes(
                        item.status,
                      )
                    }
                    onClick={() =>
                      void perform("Submitting governance decision", () =>
                        submitGovernanceDecision(item.id),
                      )
                    }
                    className={buttonClass}
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" /> Open review cycle
                  </button>
                </div>
              </article>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
