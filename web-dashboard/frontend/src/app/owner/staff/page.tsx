"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  Award,
  Bot,
  Brain,
  Briefcase,
  Building2,
  GraduationCap,
  PauseCircle,
  PlayCircle,
  RefreshCw,
  Search,
  ShieldCheck,
  UserCog,
  UserMinus,
  Users,
} from "lucide-react";

import { useOwnerResource } from "@/hooks/use-owner-resource";

type TrainingResult = {
  course_id: string;
  score: number;
  passed: boolean;
};

type StaffMember = {
  id: string;
  kind: "human" | "digital";
  name: string;
  role: string;
  department: string;
  ministry: string | null;
  organization: string;
  organizationId: string | null;
  status: string;
  performance: number | null;
  operationalHealth: number | null;
  trust: number | null;
  learning: number | null;
  successCount: number | null;
  failureCount: number | null;
  recommendation: string | null;
  restrictions: string[];
  warnings: string[];
  certifications: string[];
  training: TrainingResult | null;
  lastEvaluatedAt: string | null;
  providerNeutral?: boolean;
  grade?: number;
};

const score = (value: number | null) =>
  value === null || Number.isNaN(value) ? "—" : `${Math.round(value)}%`;

const statusClass = (status: string) => {
  if (status === "active") {
    return "border-green-500/20 bg-green-500/10 text-green-400";
  }
  if (status === "supervised") {
    return "border-sky-500/20 bg-sky-500/10 text-sky-300";
  }
  if (status === "retraining") {
    return "border-amber-500/20 bg-amber-500/10 text-amber-300";
  }
  return "border-orange-500/20 bg-orange-500/10 text-orange-400";
};

export default function OwnerStaffPage() {
  const { items, loading, busy, message, execute } =
    useOwnerResource<StaffMember>("staff");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [kind, setKind] = useState("all");

  const visible = useMemo(
    () =>
      items.filter(
        (item) =>
          (status === "all" || item.status === status) &&
          (kind === "all" || item.kind === kind) &&
          `${item.name} ${item.role} ${item.department} ${item.ministry ?? ""} ${item.organization}`
            .toLowerCase()
            .includes(query.toLowerCase()),
      ),
    [items, kind, query, status],
  );
  const statusOptions = useMemo(
    () => ["all", ...Array.from(new Set(items.map((item) => item.status)))],
    [items],
  );

  const humanStaff = items.filter((item) => item.kind === "human").length;
  const digitalWorkers = items.filter((item) => item.kind === "digital").length;
  const supervised = items.filter(
    (item) => item.kind === "digital" && item.status === "supervised",
  ).length;
  const retraining = items.filter(
    (item) => item.kind === "digital" && item.status === "retraining",
  ).length;

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between"
      >
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-purple-500/20 bg-purple-500/10 px-3 py-1 text-xs font-medium text-purple-300">
            <UserCog className="h-3.5 w-3.5" />
            Owner Workforce Oversight
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Human &amp; Digital Workforce
          </h1>
          <p className="mt-2 max-w-3xl text-sm text-white/45">
            Live identity status plus evidence-based performance, health,
            training, supervision and certification for AIOS digital workers.
          </p>
        </div>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          { label: "Human Staff", value: humanStaff, icon: Users },
          { label: "Digital Workers", value: digitalWorkers, icon: Bot },
          { label: "Under Supervision", value: supervised, icon: ShieldCheck },
          { label: "In Retraining", value: retraining, icon: GraduationCap },
        ].map((item) => (
          <div key={item.label} className="glass-card p-5">
            <item.icon className="h-5 w-5 text-purple-300" />
            <div className="mt-4 text-2xl font-bold text-white">
              {item.value}
            </div>
            <div className="mt-1 text-xs uppercase tracking-wider text-white/35">
              {item.label}
            </div>
          </div>
        ))}
      </div>

      <div className="space-y-3">
        <div className="flex flex-col gap-3 lg:flex-row">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search worker, role, department, ministry or organization..."
              className="glass-input w-full rounded-xl py-2.5 pl-10 pr-4 text-sm text-white outline-none"
            />
          </div>
          <select
            value={kind}
            onChange={(event) => setKind(event.target.value)}
            className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"
          >
            <option value="all" className="bg-space-800">
              All Workforce
            </option>
            <option value="human" className="bg-space-800">
              Human Staff
            </option>
            <option value="digital" className="bg-space-800">
              Digital Workers
            </option>
          </select>
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"
          >
            {statusOptions.map((option) => (
              <option key={option} value={option} className="bg-space-800">
                {option === "all" ? "All Status" : option}
              </option>
            ))}
          </select>
        </div>
        <div className="text-xs text-electric-300">
          {loading ? "Loading workforce records..." : message}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {!loading && visible.length === 0 && (
          <div className="glass-card p-6 text-sm text-white/45 xl:col-span-2">
            No workforce records match the current filters.
          </div>
        )}
        {visible.map((member, index) => {
          const MemberIcon = member.kind === "digital" ? Bot : UserCog;
          return (
            <motion.section
              key={member.id}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: Math.min(index, 8) * 0.04 }}
              className="glass-card p-5"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-3">
                    <div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5">
                      <MemberIcon className="h-5 w-5 text-purple-300" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="break-words text-sm font-semibold text-white">
                          {member.name}
                        </h2>
                        <span className="rounded-full border border-white/[0.07] px-2 py-0.5 text-[10px] uppercase tracking-wide text-white/35">
                          {member.kind}
                        </span>
                      </div>
                      <p className="mt-1 text-xs text-white/40">
                        {member.role} · {member.department}
                        {member.ministry ? ` · ${member.ministry}` : ""}
                      </p>
                      <p className="mt-1 flex items-center gap-1 text-xs text-white/30">
                        <Building2 className="h-3 w-3" />
                        {member.organization}
                      </p>
                    </div>
                  </div>
                </div>
                <span
                  className={`shrink-0 rounded-full border px-2.5 py-1 text-xs ${statusClass(member.status)}`}
                >
                  {member.status}
                </span>
              </div>

              {member.kind === "digital" ? (
                <>
                  <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
                    {[
                      {
                        label: "Performance",
                        value: score(member.performance),
                        icon: Activity,
                      },
                      {
                        label: "Health",
                        value: score(member.operationalHealth),
                        icon: ShieldCheck,
                      },
                      {
                        label: "Trust",
                        value: score(member.trust),
                        icon: Briefcase,
                      },
                      {
                        label: "Learning",
                        value: score(member.learning),
                        icon: Brain,
                      },
                    ].map((metric) => (
                      <div
                        key={metric.label}
                        className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-3"
                      >
                        <metric.icon className="h-3.5 w-3.5 text-electric-300" />
                        <div className="mt-2 text-sm font-semibold text-white">
                          {metric.value}
                        </div>
                        <div className="mt-0.5 text-[10px] uppercase tracking-wide text-white/30">
                          {metric.label}
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="mt-4 grid gap-3 sm:grid-cols-2">
                    <div className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-3 text-xs text-white/45">
                      <div className="font-medium text-white/75">
                        Performance record
                      </div>
                      <div className="mt-2">
                        Successful assignments: {member.successCount ?? 0}
                      </div>
                      <div>Failed or returned: {member.failureCount ?? 0}</div>
                    </div>
                    <div className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-3 text-xs text-white/45">
                      <div className="font-medium text-white/75">
                        Latest training assessment
                      </div>
                      {member.training ? (
                        <div className="mt-2 space-y-1">
                          <div>{member.training.course_id}</div>
                          <div>
                            Score: {Math.round(member.training.score)}% ·{" "}
                            {member.training.passed ? "Passed" : "Not passed"}
                          </div>
                        </div>
                      ) : (
                        <div className="mt-2">No assessment recorded.</div>
                      )}
                    </div>
                  </div>

                  <div className="mt-4 rounded-xl border border-white/[0.05] bg-white/[0.02] p-3 text-xs text-white/45">
                    <div className="font-medium text-white/75">
                      Institute recommendation
                    </div>
                    <div className="mt-2">
                      {member.recommendation ?? "Standard monitoring"}
                    </div>
                    {member.restrictions.length > 0 && (
                      <ul className="mt-2 list-disc space-y-1 pl-4 text-amber-200/70">
                        {member.restrictions.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    )}
                    {member.certifications.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-1.5">
                        {member.certifications.map((item) => (
                          <span
                            key={item}
                            className="rounded-full border border-green-500/15 bg-green-500/5 px-2 py-1 text-[10px] text-green-300"
                          >
                            {item}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2 border-t border-white/[0.05] pt-4">
                    <button
                      type="button"
                      disabled={busy || member.status === "retired"}
                      onClick={() =>
                        void execute(member.id, "promotion", {
                          grade: Math.min(100, (member.grade ?? 1) + 1),
                          reason: "Owner verified performance promotion",
                        })
                      }
                      className="inline-flex items-center gap-2 rounded-xl border border-green-500/20 bg-green-500/10 px-3 py-2 text-xs text-green-300 disabled:opacity-40"
                    >
                      <Award className="h-3.5 w-3.5" /> Promote
                    </button>
                    <button
                      type="button"
                      disabled={busy || member.status === "retired"}
                      onClick={() =>
                        void execute(member.id, "training", {
                          reason: "Owner assigned governed retraining",
                        })
                      }
                      className="inline-flex items-center gap-2 rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-200 disabled:opacity-40"
                    >
                      <RefreshCw className="h-3.5 w-3.5" /> Retrain
                    </button>
                    {member.status === "suspended" ? (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          void execute(member.id, "restore", {
                            reason: "Owner restored workforce member",
                          })
                        }
                        className="inline-flex items-center gap-2 rounded-xl border border-electric-500/20 bg-electric-500/10 px-3 py-2 text-xs text-electric-200 disabled:opacity-40"
                      >
                        <PlayCircle className="h-3.5 w-3.5" /> Restore
                      </button>
                    ) : (
                      <button
                        type="button"
                        disabled={busy || member.status === "retired"}
                        onClick={() =>
                          void execute(member.id, "suspension", {
                            reason: "Owner suspended workforce member",
                          })
                        }
                        className="inline-flex items-center gap-2 rounded-xl border border-orange-500/20 bg-orange-500/10 px-3 py-2 text-xs text-orange-300 disabled:opacity-40"
                      >
                        <PauseCircle className="h-3.5 w-3.5" /> Suspend
                      </button>
                    )}
                    <button
                      type="button"
                      disabled={busy || member.status === "retired"}
                      onClick={() =>
                        void execute(member.id, "retirement", {
                          reason: "Owner retired workforce member",
                        })
                      }
                      className="inline-flex items-center gap-2 rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-300 disabled:opacity-40"
                    >
                      <UserMinus className="h-3.5 w-3.5" /> Retire
                    </button>
                  </div>
                </>
              ) : (
                <div className="mt-4 border-t border-white/[0.05] pt-4 text-xs text-white/45">
                  Human account status is read directly from the identity
                  database. Digital-worker performance scores do not apply to
                  human identities.
                </div>
              )}
            </motion.section>
          );
        })}
      </div>
    </div>
  );
}
