"use client";

import {
  AlertCircle,
  CheckCircle2,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Workflow,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  phase29fApi,
  type ProjectRecord,
  type WorkflowRecord,
  type WorkflowRun,
} from "@/lib/phase29f-api";

const inputClass =
  "glass-input rounded-xl px-3 py-2.5 text-sm text-white outline-none disabled:cursor-not-allowed disabled:opacity-50";
const buttonClass =
  "inline-flex items-center justify-center gap-2 rounded-xl border border-electric-500/20 bg-electric-500/10 px-3 py-2 text-xs font-semibold text-electric-200 transition hover:bg-electric-500/15 disabled:cursor-not-allowed disabled:opacity-50";

export default function WorkflowsPage() {
  const [workflows, setWorkflows] = useState<WorkflowRecord[]>([]);
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [runs, setRuns] = useState<Record<string, WorkflowRun[]>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setMessage("");
    try {
      const [workflowRows, projectRows] = await Promise.all([
        phase29fApi.listWorkflows({ limit: 100 }),
        phase29fApi.listProjects({ limit: 100 }),
      ]);
      setWorkflows(workflowRows);
      setProjects(projectRows);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Failed to load workflows.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function createWorkflow(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    const projectId = String(values.get("project_id") || "");
    const project = projects.find((item) => item.id === projectId);
    const requestedSteps = String(
      values.get("steps") || "validation,set,evidence",
    )
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    const steps = requestedSteps.map((type, index) => {
      if (type === "set")
        return { type, id: `step-${index + 1}`, key: "ready", value: true };
      if (type === "evidence")
        return { type, id: `step-${index + 1}`, label: "workflow-evidence" };
      return { type: "validation", id: `step-${index + 1}` };
    });
    setBusy("create");
    try {
      await phase29fApi.createWorkflow({
        name: String(values.get("name") || "").trim(),
        description: String(values.get("description") || "").trim() || null,
        trigger: "manual",
        project_id: projectId || null,
        workspace_id: project?.workspace_id || null,
        steps,
      });
      form.reset();
      setMessage("Workflow created with a durable run contract.");
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Workflow creation failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function runWorkflow(workflow: WorkflowRecord) {
    setBusy(workflow.id);
    setMessage("");
    try {
      const result = await phase29fApi.runWorkflow(workflow.id, {
        requested_from: "dashboard",
        workflow_version: workflow.version,
      });
      setWorkflows((current) =>
        current.map((item) =>
          item.id === workflow.id ? result.workflow : item,
        ),
      );
      setRuns((current) => ({
        ...current,
        [workflow.id]: [result.run, ...(current[workflow.id] || [])],
      }));
      setMessage(
        result.run_status === "completed"
          ? "Workflow completed and evidence was retained."
          : `Workflow finished with status ${result.run_status}.`,
      );
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Workflow run failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function loadRuns(workflowId: string) {
    setBusy(workflowId);
    try {
      const rows = await phase29fApi.listWorkflowRuns(workflowId);
      setRuns((current) => ({ ...current, [workflowId]: rows }));
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Run history could not be loaded.",
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-purple-500/20 bg-purple-500/10 px-3 py-1 text-xs text-purple-300">
            <Workflow className="h-3.5 w-3.5" /> Provider-neutral Orchestration
          </div>
          <h1 className="mt-3 text-3xl font-bold text-white">
            Durable Workflows
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Run deterministic validation, state-setting, and evidence steps
            without an external model.
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

      <form
        onSubmit={createWorkflow}
        className="glass-card grid gap-3 p-5 lg:grid-cols-5"
      >
        <input
          name="name"
          minLength={2}
          required
          placeholder="Workflow name"
          className={`${inputClass} lg:col-span-2`}
        />
        <select name="project_id" defaultValue="" className={inputClass}>
          <option value="">Workspace-neutral workflow</option>
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
        <input
          name="steps"
          defaultValue="validation,set,evidence"
          placeholder="validation,set,evidence"
          className={inputClass}
        />
        <button className={buttonClass} disabled={busy === "create"}>
          {busy === "create" ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Plus className="h-4 w-4" />
          )}{" "}
          Create workflow
        </button>
        <textarea
          name="description"
          placeholder="Purpose and execution boundary"
          className={`${inputClass} min-h-20 lg:col-span-5`}
        />
      </form>

      {loading ? (
        <div className="glass-card flex min-h-48 items-center justify-center text-white/45">
          <Loader2 className="me-2 h-5 w-5 animate-spin" />
          Loading workflows…
        </div>
      ) : workflows.length === 0 ? (
        <div className="glass-card p-10 text-center text-sm text-white/40">
          No workflows are currently recorded.
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {workflows.map((workflow) => (
            <section key={workflow.id} className="glass-card p-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="font-semibold text-white">
                      {workflow.name}
                    </h2>
                    <span className="rounded-full border border-white/[0.08] px-2 py-0.5 text-[10px] text-white/45">
                      {workflow.status}
                    </span>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-white/40">
                    {workflow.description || "No description"}
                  </p>
                  <p className="mt-3 text-xs text-white/30">
                    {workflow.steps.length} steps · {workflow.run_count} runs ·
                    version {workflow.version}
                  </p>
                </div>
                <button
                  className={buttonClass}
                  disabled={busy === workflow.id}
                  onClick={() => void runWorkflow(workflow)}
                >
                  {busy === workflow.id ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Play className="h-4 w-4" />
                  )}{" "}
                  Run
                </button>
              </div>

              <div className="mt-5 border-t border-white/[0.06] pt-4">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-white/40">
                    Run evidence
                  </h3>
                  <button
                    className="inline-flex items-center gap-1 text-xs text-electric-300"
                    onClick={() => void loadRuns(workflow.id)}
                  >
                    <RotateCcw className="h-3.5 w-3.5" /> Load history
                  </button>
                </div>
                <div className="mt-3 space-y-2">
                  {(runs[workflow.id] || []).slice(0, 5).map((run) => (
                    <div
                      key={run.id}
                      className="rounded-xl border border-white/[0.06] bg-black/15 p-3 text-xs text-white/45"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span>{run.id.slice(0, 8)}</span>
                        <span
                          className={
                            run.status === "completed"
                              ? "text-green-300"
                              : run.status === "failed"
                                ? "text-red-300"
                                : "text-amber-200"
                          }
                        >
                          {run.status === "completed" ? (
                            <CheckCircle2 className="me-1 inline h-3.5 w-3.5" />
                          ) : (
                            <AlertCircle className="me-1 inline h-3.5 w-3.5" />
                          )}
                          {run.status}
                        </span>
                      </div>
                      <p className="mt-2">
                        step {run.current_step} · attempts {run.attempt_count} ·
                        evidence {run.evidence.length}
                      </p>
                      {Object.keys(run.output || {}).length > 0 && (
                        <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap rounded-lg bg-black/20 p-2 text-[10px] text-white/55">
                          {JSON.stringify(run.output, null, 2)}
                        </pre>
                      )}
                    </div>
                  ))}
                  {runs[workflow.id]?.length === 0 && (
                    <p className="text-xs text-white/30">No runs recorded.</p>
                  )}
                </div>
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
