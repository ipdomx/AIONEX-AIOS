"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  CheckCircle2,
  FolderKanban,
  PauseCircle,
  PlayCircle,
  Search,
  ShieldCheck,
} from "lucide-react";

import { useOwnerResource } from "@/hooks/use-owner-resource";

type OwnerProject = {
  id: string;
  name: string;
  owner: string;
  organization: string;
  status: string;
  risk: string;
  progress: number;
  approvals: number;
  updatedAt: string;
};

export default function OwnerProjectsPage() {
  const { items, loading, busy, message, execute } =
    useOwnerResource<OwnerProject>("projects");
  const [query, setQuery] = useState("");

  const projects = useMemo(
    () =>
      items.filter((project) =>
        `${project.name} ${project.owner} ${project.organization} ${project.status}`
          .toLowerCase()
          .includes(query.toLowerCase()),
      ),
    [items, query],
  );

  function runProjectAction(
    projectId: string,
    action: "resume" | "pause" | "approve",
  ) {
    void execute(projectId, action);
  }

  const summaries = [
    ["Total projects", items.length],
    ["Needs approval", items.filter((item) => item.approvals > 0).length],
    [
      "High risk",
      items.filter((item) => ["high", "critical"].includes(item.risk)).length,
    ],
    [
      "Paused by owner",
      items.filter((item) => item.status === "paused").length,
    ],
  ] as const;

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between"
      >
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300">
            <FolderKanban className="h-3.5 w-3.5" /> Owner Project Command
          </div>
          <h1 className="text-3xl font-bold text-white">
            Global Project Oversight
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Owner visibility across every project, organization, approval, risk
            and execution state.
          </p>
        </div>
        <Link
          href={{
            pathname: "/owner/operations",
            query: { entity: "project", operation: "create" },
          }}
          className="btn-primary"
        >
          Create governed project
        </Link>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {summaries.map(([label, value]) => (
          <div key={label} className="glass-card p-5">
            <div className="text-2xl font-bold text-white">{value}</div>
            <div className="mt-1 text-xs text-white/35">{label}</div>
          </div>
        ))}
      </div>

      <section className="glass-card p-5">
        <div className="mb-2 flex items-center gap-3">
          <Search className="h-4 w-4 text-white/30" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="glass-input w-full rounded-xl px-4 py-2.5 text-sm text-white outline-none"
            placeholder="Search every project..."
          />
        </div>
        <div className="mb-4 text-xs text-electric-300">
          {loading ? "Loading governed projects..." : message}
        </div>
        <div className="space-y-3">
          {!loading && projects.length === 0 && (
            <div className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-5 text-sm text-white/45">
              No projects match the current search.
            </div>
          )}
          {projects.map((project) => (
            <div
              key={project.id}
              className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-4"
            >
              <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-sm font-semibold text-white">
                      {project.name}
                    </h2>
                    {["high", "critical"].includes(project.risk) ? (
                      <AlertTriangle className="h-4 w-4 text-red-400" />
                    ) : (
                      <ShieldCheck className="h-4 w-4 text-green-400" />
                    )}
                  </div>
                  <p className="mt-1 text-xs text-white/40">
                    {project.organization} · {project.owner}
                  </p>
                </div>
                <div className="grid flex-1 grid-cols-2 gap-3 sm:grid-cols-4 xl:max-w-2xl">
                  <div>
                    <div className="text-[10px] uppercase text-white/25">
                      Status
                    </div>
                    <div className="mt-1 text-xs text-white/65">
                      {project.status}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase text-white/25">
                      Progress
                    </div>
                    <div className="mt-1 text-xs text-white/65">
                      {project.progress}%
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase text-white/25">
                      Approvals
                    </div>
                    <div className="mt-1 text-xs text-white/65">
                      {project.approvals}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase text-white/25">
                      Risk
                    </div>
                    <div className="mt-1 text-xs text-white/65">
                      {project.risk}
                    </div>
                  </div>
                </div>
                <div className="flex gap-2">
                  {project.status === "paused" ? (
                    <button
                      onClick={() => runProjectAction(project.id, "resume")}
                      disabled={busy}
                      className="rounded-lg border border-white/[0.08] p-2 text-white/55 hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-50"
                      aria-label={`Resume ${project.name}`}
                    >
                      <PlayCircle className="h-4 w-4" />
                    </button>
                  ) : ["active", "in_progress", "planning", "running"].includes(
                      project.status,
                    ) ? (
                    <button
                      onClick={() => runProjectAction(project.id, "pause")}
                      disabled={busy}
                      className="rounded-lg border border-white/[0.08] p-2 text-white/55 hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-50"
                      aria-label={`Pause ${project.name}`}
                    >
                      <PauseCircle className="h-4 w-4" />
                    </button>
                  ) : null}
                  {project.status === "review" && (
                    <button
                      onClick={() => runProjectAction(project.id, "approve")}
                      disabled={busy}
                      className="rounded-lg border border-green-500/20 bg-green-500/10 p-2 text-green-400 disabled:cursor-not-allowed disabled:opacity-50"
                      aria-label={`Approve ${project.name}`}
                    >
                      <CheckCircle2 className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
