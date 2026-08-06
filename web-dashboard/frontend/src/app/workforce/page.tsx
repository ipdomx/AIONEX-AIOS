"use client";

import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  Loader2,
  PauseCircle,
  PlayCircle,
  Plus,
  RefreshCw,
  ShieldCheck,
  UserCog,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  phase29fApi,
  type ProjectRecord,
  type WorkforceAssignment,
  type WorkforceIncident,
  type WorkforceMember,
} from "@/lib/phase29f-api";

const inputClass =
  "glass-input rounded-xl px-3 py-2.5 text-sm text-white outline-none disabled:cursor-not-allowed disabled:opacity-50";
const buttonClass =
  "inline-flex items-center justify-center gap-2 rounded-xl border border-electric-500/20 bg-electric-500/10 px-3 py-2 text-xs font-semibold text-electric-200 transition hover:bg-electric-500/15 disabled:cursor-not-allowed disabled:opacity-50";

export default function WorkforcePage() {
  const [members, setMembers] = useState<WorkforceMember[]>([]);
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [assignments, setAssignments] = useState<WorkforceAssignment[]>([]);
  const [incidents, setIncidents] = useState<WorkforceIncident[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setMessage("");
    try {
      const [memberRows, projectRows, assignmentRows, incidentRows] =
        await Promise.all([
          phase29fApi.listWorkforceMembers({ limit: 200 }),
          phase29fApi.listProjects({ limit: 100 }),
          phase29fApi.listAssignments({ limit: 200 }),
          phase29fApi.listWorkforceIncidents({ limit: 100 }),
        ]);
      setMembers(memberRows);
      setProjects(projectRows);
      setAssignments(assignmentRows);
      setIncidents(incidentRows);
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Workforce records could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function createMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    setBusy("member-create");
    try {
      await phase29fApi.createDigitalMember({
        name: String(values.get("name") || "").trim(),
        role: String(values.get("role") || "Digital Worker").trim(),
        department: String(values.get("department") || "Delivery").trim(),
        ministry: String(values.get("ministry") || "").trim() || null,
        skills: String(values.get("skills") || "")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        grade: Number(values.get("grade") || 1),
      });
      form.reset();
      setMessage("Provider-neutral digital workforce member created.");
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Workforce member creation failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function createAssignment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    setBusy("assignment-create");
    try {
      await phase29fApi.createAssignment({
        title: String(values.get("title") || "").trim(),
        project_id: String(values.get("project_id") || ""),
        worker_id: String(values.get("worker_id") || ""),
        required_skills: String(values.get("skills") || "")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        acceptance_criteria: String(values.get("criteria") || "")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        priority: 70,
        risk: String(values.get("risk") || "normal"),
      });
      form.reset();
      setMessage("Assignment created with retained acceptance criteria.");
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Assignment creation failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function transitionMember(member: WorkforceMember, action: string) {
    setBusy(member.id);
    try {
      const updated = await phase29fApi.transitionMember(member.id, {
        action,
        reason: `Dashboard ${action}`,
        grade:
          action === "promote" ? Math.min(100, member.grade + 1) : undefined,
      });
      setMembers((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setMessage(`Workforce lifecycle action ${action} completed and audited.`);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Lifecycle action failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function transitionAssignment(
    assignment: WorkforceAssignment,
    action: string,
  ) {
    setBusy(assignment.id);
    try {
      const evidence =
        action === "submit_review"
          ? { passed_criteria: assignment.acceptance_criteria }
          : {};
      const updated = await phase29fApi.transitionAssignment(assignment.id, {
        action,
        reason: `Dashboard ${action}`,
        evidence,
        defects: action === "rework" ? ["Owner review requested rework"] : [],
      });
      setAssignments((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setMessage(`Assignment ${action.replaceAll("_", " ")} retained.`);
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Assignment transition failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function evaluate(member: WorkforceMember) {
    setBusy(member.id);
    try {
      await phase29fApi.evaluateMember(member.id);
      setMessage("Workforce health evidence regenerated.");
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Evaluation failed.");
    } finally {
      setBusy(null);
    }
  }

  async function resolveIncident(incident: WorkforceIncident) {
    setBusy(incident.id);
    try {
      const updated = await phase29fApi.resolveWorkforceIncident(
        incident.id,
        "Resolved from workforce dashboard",
      );
      setIncidents((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setMessage("Workforce incident resolved and preserved in history.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Incident resolution failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  const digital = members.filter((item) => item.kind === "digital");

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-purple-500/20 bg-purple-500/10 px-3 py-1 text-xs text-purple-300">
            <Bot className="h-3.5 w-3.5" /> Governed Digital Workforce
          </div>
          <h1 className="mt-3 text-3xl font-bold text-white">
            Workforce Operations
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Assign work, enforce acceptance criteria, evaluate health, retrain,
            promote, suspend, and retire provider-neutral workers.
          </p>
        </div>
        <button
          className={buttonClass}
          onClick={() => void load()}
          disabled={loading}
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />{" "}
          Refresh
        </button>
      </div>

      {message && (
        <div className="rounded-xl border border-electric-500/20 bg-electric-500/10 px-4 py-3 text-sm text-electric-200">
          {message}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-4">
        <Summary label="All workforce" value={members.length} icon={UserCog} />
        <Summary label="Digital workers" value={digital.length} icon={Bot} />
        <Summary
          label="Active assignments"
          value={
            assignments.filter(
              (item) => !["completed", "cancelled"].includes(item.status),
            ).length
          }
          icon={Activity}
        />
        <Summary
          label="Open incidents"
          value={incidents.filter((item) => item.status !== "resolved").length}
          icon={AlertTriangle}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <form
          onSubmit={createMember}
          className="glass-card grid gap-3 p-5 sm:grid-cols-2"
        >
          <h2 className="font-semibold text-white sm:col-span-2">
            Create digital worker
          </h2>
          <input
            name="name"
            minLength={2}
            required
            placeholder="Worker name"
            className={inputClass}
          />
          <input
            name="role"
            defaultValue="Digital Worker"
            placeholder="Role"
            className={inputClass}
          />
          <input
            name="department"
            defaultValue="Delivery"
            placeholder="Department"
            className={inputClass}
          />
          <input
            name="ministry"
            placeholder="Ministry or council"
            className={inputClass}
          />
          <input
            name="skills"
            placeholder="skills,comma,separated"
            className={inputClass}
          />
          <input
            name="grade"
            type="number"
            min="1"
            max="100"
            defaultValue="1"
            className={inputClass}
          />
          <button
            className={`${buttonClass} sm:col-span-2`}
            disabled={busy === "member-create"}
          >
            <Plus className="h-4 w-4" /> Create provider-neutral worker
          </button>
        </form>

        <form
          onSubmit={createAssignment}
          className="glass-card grid gap-3 p-5 sm:grid-cols-2"
        >
          <h2 className="font-semibold text-white sm:col-span-2">
            Create governed assignment
          </h2>
          <input
            name="title"
            minLength={2}
            required
            placeholder="Assignment title"
            className={`${inputClass} sm:col-span-2`}
          />
          <select
            name="project_id"
            required
            defaultValue=""
            className={inputClass}
          >
            <option value="" disabled>
              Select project
            </option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
          <select
            name="worker_id"
            required
            defaultValue=""
            className={inputClass}
          >
            <option value="" disabled>
              Select worker
            </option>
            {digital
              .filter(
                (member) => !["suspended", "retired"].includes(member.status),
              )
              .map((member) => (
                <option key={member.id} value={member.id}>
                  {member.name}
                </option>
              ))}
          </select>
          <input
            name="skills"
            placeholder="required skills"
            className={inputClass}
          />
          <input
            name="criteria"
            required
            placeholder="criteria,comma,separated"
            className={inputClass}
          />
          <select name="risk" defaultValue="normal" className={inputClass}>
            <option value="low">Low risk</option>
            <option value="normal">Normal risk</option>
            <option value="high">High risk</option>
            <option value="critical">Critical risk</option>
          </select>
          <button
            className={buttonClass}
            disabled={busy === "assignment-create"}
          >
            <Plus className="h-4 w-4" /> Create assignment
          </button>
        </form>
      </div>

      {loading ? (
        <div className="glass-card flex min-h-48 items-center justify-center text-white/45">
          <Loader2 className="me-2 h-5 w-5 animate-spin" />
          Loading workforce…
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {digital.map((member) => (
            <section key={member.id} className="glass-card p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="font-semibold text-white">{member.name}</h2>
                    <span className="rounded-full border border-white/[0.08] px-2 py-0.5 text-[10px] text-white/45">
                      {member.status}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-white/35">
                    {member.role} · {member.department} · grade {member.grade}
                  </p>
                </div>
                <ShieldCheck className="h-5 w-5 text-purple-300" />
              </div>
              <div className="mt-4 grid grid-cols-4 gap-2 text-center text-xs">
                {[
                  ["Performance", member.performance],
                  ["Health", member.operational_health],
                  ["Trust", member.trust],
                  ["Learning", member.learning],
                ].map(([label, value]) => (
                  <div
                    key={String(label)}
                    className="rounded-xl border border-white/[0.05] bg-black/15 p-3"
                  >
                    <div className="text-sm font-semibold text-white">
                      {typeof value === "number"
                        ? `${Math.round(value)}%`
                        : "—"}
                    </div>
                    <div className="mt-1 text-[10px] text-white/30">
                      {String(label)}
                    </div>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-xs text-white/40">
                {member.recommendation || "Evaluation pending"} ·{" "}
                {member.success_count} successful · {member.failure_count}{" "}
                returned
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  className={buttonClass}
                  disabled={busy === member.id}
                  onClick={() => void evaluate(member)}
                >
                  <Activity className="h-3.5 w-3.5" /> Evaluate
                </button>
                <button
                  className={buttonClass}
                  disabled={busy === member.id || member.status === "retired"}
                  onClick={() => void transitionMember(member, "promote")}
                >
                  <CheckCircle2 className="h-3.5 w-3.5" /> Promote
                </button>
                <button
                  className={buttonClass}
                  disabled={busy === member.id || member.status === "retired"}
                  onClick={() => void transitionMember(member, "retrain")}
                >
                  <RefreshCw className="h-3.5 w-3.5" /> Retrain
                </button>
                {member.status === "suspended" ? (
                  <button
                    className={buttonClass}
                    disabled={busy === member.id}
                    onClick={() => void transitionMember(member, "restore")}
                  >
                    <PlayCircle className="h-3.5 w-3.5" /> Restore
                  </button>
                ) : (
                  <button
                    className={buttonClass}
                    disabled={busy === member.id || member.status === "retired"}
                    onClick={() => void transitionMember(member, "suspend")}
                  >
                    <PauseCircle className="h-3.5 w-3.5" /> Suspend
                  </button>
                )}
              </div>
            </section>
          ))}
        </div>
      )}

      <section className="glass-card p-5">
        <h2 className="font-semibold text-white">Assignments</h2>
        <div className="mt-4 space-y-3">
          {assignments.length === 0 ? (
            <p className="text-sm text-white/35">
              No assignments are recorded.
            </p>
          ) : (
            assignments.map((assignment) => (
              <div
                key={assignment.id}
                className="rounded-xl border border-white/[0.06] bg-black/15 p-4"
              >
                <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-semibold text-white">
                        {assignment.title}
                      </h3>
                      <span className="rounded-full border border-white/[0.08] px-2 py-0.5 text-[10px] text-white/45">
                        {assignment.status}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-white/35">
                      completeness {Math.round(assignment.completeness * 100)}%
                      · attempts {assignment.attempts} · risk {assignment.risk}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {assignment.status === "assigned" && (
                      <button
                        className={buttonClass}
                        disabled={busy === assignment.id}
                        onClick={() =>
                          void transitionAssignment(assignment, "start")
                        }
                      >
                        Start
                      </button>
                    )}
                    {assignment.status === "in_progress" && (
                      <button
                        className={buttonClass}
                        disabled={busy === assignment.id}
                        onClick={() =>
                          void transitionAssignment(assignment, "submit_review")
                        }
                      >
                        Submit review
                      </button>
                    )}
                    {assignment.status === "review" && (
                      <>
                        <button
                          className={buttonClass}
                          disabled={busy === assignment.id}
                          onClick={() =>
                            void transitionAssignment(assignment, "approve")
                          }
                        >
                          Approve
                        </button>
                        <button
                          className={buttonClass}
                          disabled={busy === assignment.id}
                          onClick={() =>
                            void transitionAssignment(assignment, "rework")
                          }
                        >
                          Rework
                        </button>
                      </>
                    )}
                    {assignment.status === "rework" && (
                      <button
                        className={buttonClass}
                        disabled={busy === assignment.id}
                        onClick={() =>
                          void transitionAssignment(assignment, "start")
                        }
                      >
                        Resume
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="glass-card p-5">
        <h2 className="font-semibold text-white">Workforce incidents</h2>
        <div className="mt-4 space-y-3">
          {incidents.length === 0 ? (
            <p className="text-sm text-white/35">
              No workforce incidents are recorded.
            </p>
          ) : (
            incidents.map((incident) => (
              <div
                key={incident.id}
                className="flex flex-col gap-3 rounded-xl border border-white/[0.06] bg-black/15 p-4 lg:flex-row lg:items-center lg:justify-between"
              >
                <div>
                  <p className="text-sm font-semibold text-white">
                    {incident.category} · {incident.severity}
                  </p>
                  <p className="mt-1 text-xs text-white/40">
                    {incident.description}
                  </p>
                </div>
                {incident.status !== "resolved" && (
                  <button
                    className={buttonClass}
                    disabled={busy === incident.id}
                    onClick={() => void resolveIncident(incident)}
                  >
                    Resolve
                  </button>
                )}
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}

function Summary({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: number;
  icon: React.ElementType;
}) {
  return (
    <div className="glass-card p-5">
      <Icon className="h-5 w-5 text-electric-300" />
      <div className="mt-3 text-2xl font-bold text-white">{value}</div>
      <div className="mt-1 text-xs text-white/35">{label}</div>
    </div>
  );
}
