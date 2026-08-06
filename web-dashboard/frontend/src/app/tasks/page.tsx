"use client";

import {
  AlertCircle,
  CheckCircle2,
  CheckSquare,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Send,
  Undo2,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  phase29fApi,
  type ProjectRecord,
  type TaskComment,
  type TaskRecord,
} from "@/lib/phase29f-api";

const inputClass =
  "glass-input rounded-xl px-3 py-2.5 text-sm text-white outline-none disabled:cursor-not-allowed disabled:opacity-50";
const buttonClass =
  "inline-flex items-center justify-center gap-2 rounded-xl border border-electric-500/20 bg-electric-500/10 px-3 py-2 text-xs font-semibold text-electric-200 transition hover:bg-electric-500/15 disabled:cursor-not-allowed disabled:opacity-50";

function nextActions(task: TaskRecord): Array<[string, string]> {
  if (task.status === "todo") return [["start", "Start"]];
  if (task.status === "in_progress")
    return [
      ["request_review", "Request review"],
      ["block", "Block"],
    ];
  if (task.status === "review")
    return [
      ["approve", "Approve"],
      ["rework", "Return for rework"],
    ];
  if (["rework", "blocked"].includes(task.status))
    return [["start", "Resume work"]];
  if (["done", "cancelled"].includes(task.status))
    return [["reopen", "Reopen"]];
  return [];
}

export default function TasksPage() {
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [selected, setSelected] = useState<TaskRecord | null>(null);
  const [comments, setComments] = useState<TaskComment[]>([]);
  const [comment, setComment] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setMessage("");
    try {
      const [taskRows, projectRows] = await Promise.all([
        phase29fApi.listTasks({ limit: 100 }),
        phase29fApi.listProjects({ limit: 100 }),
      ]);
      setTasks(taskRows);
      setProjects(projectRows);
      if (selected) {
        const refreshed =
          taskRows.find((item) => item.id === selected.id) || null;
        setSelected(refreshed);
      }
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Failed to load tasks.",
      );
    } finally {
      setLoading(false);
    }
  }, [selected]);

  useEffect(() => {
    void load();
    // The selected record is refreshed explicitly after mutations.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const visible = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return tasks.filter(
      (task) =>
        (statusFilter === "all" || task.status === statusFilter) &&
        (!normalized ||
          `${task.title} ${task.project || ""} ${task.assignee || ""}`
            .toLowerCase()
            .includes(normalized)),
    );
  }, [query, statusFilter, tasks]);

  async function createTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    const projectId = String(values.get("project_id") || "");
    setBusy("create");
    setMessage("");
    try {
      await phase29fApi.createTask({
        title: String(values.get("title") || "").trim(),
        description: String(values.get("description") || "").trim() || null,
        priority: String(values.get("priority") || "medium"),
        project_id: projectId || null,
        workspace_id:
          projects.find((project) => project.id === projectId)?.workspace_id ||
          null,
        tags: String(values.get("tags") || "")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      });
      form.reset();
      setMessage("Task created and retained in the project history.");
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Task creation failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function transition(task: TaskRecord, action: string) {
    setBusy(task.id);
    setMessage("");
    try {
      const updated = await phase29fApi.transitionTask(task.id, action, action);
      setTasks((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      if (selected?.id === updated.id) setSelected(updated);
      setMessage(`Task ${action.replaceAll("_", " ")} completed and audited.`);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Task transition failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function openTask(task: TaskRecord) {
    setSelected(task);
    setBusy(task.id);
    try {
      setComments(await phase29fApi.listTaskComments(task.id));
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Comments could not be loaded.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function addComment() {
    if (!selected || !comment.trim()) return;
    setBusy(selected.id);
    try {
      const created = await phase29fApi.addTaskComment(
        selected.id,
        comment.trim(),
      );
      setComments((current) => [...current, created]);
      setComment("");
      setMessage("Comment added to the durable task record.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Comment could not be added.",
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300">
            <CheckSquare className="h-3.5 w-3.5" /> Governed Work Management
          </div>
          <h1 className="mt-3 text-3xl font-bold text-white">
            Tasks & Review Cycles
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Create, assign, review, return, approve, reopen, and discuss
            retained project work.
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
        onSubmit={createTask}
        className="glass-card grid gap-3 p-5 lg:grid-cols-6"
      >
        <input
          name="title"
          minLength={2}
          required
          placeholder="Task title"
          className={`${inputClass} lg:col-span-2`}
        />
        <select name="project_id" className={inputClass} defaultValue="">
          <option value="">No project</option>
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
        <select name="priority" className={inputClass} defaultValue="medium">
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
          <option value="critical">Critical</option>
        </select>
        <input
          name="tags"
          placeholder="tags,comma,separated"
          className={inputClass}
        />
        <button className={buttonClass} disabled={busy === "create"}>
          {busy === "create" ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Plus className="h-4 w-4" />
          )}{" "}
          Create task
        </button>
        <textarea
          name="description"
          placeholder="Description and acceptance context"
          className={`${inputClass} min-h-20 lg:col-span-6`}
        />
      </form>

      <div className="flex flex-col gap-3 sm:flex-row">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search tasks"
            className={`${inputClass} w-full pl-10`}
          />
        </div>
        <select
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value)}
          className={inputClass}
        >
          <option value="all">All statuses</option>
          {[
            "todo",
            "in_progress",
            "review",
            "rework",
            "blocked",
            "done",
            "cancelled",
          ].map((value) => (
            <option key={value} value={value}>
              {value.replaceAll("_", " ")}
            </option>
          ))}
        </select>
      </div>

      {loading ? (
        <div className="glass-card flex min-h-44 items-center justify-center text-white/45">
          <Loader2 className="me-2 h-5 w-5 animate-spin" />
          Loading tasks…
        </div>
      ) : visible.length === 0 ? (
        <div className="glass-card p-10 text-center text-sm text-white/40">
          No tasks match the current filters.
        </div>
      ) : (
        <div className="space-y-3">
          {visible.map((task) => (
            <section key={task.id} className="glass-card p-5">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                <button
                  type="button"
                  onClick={() => void openTask(task)}
                  className="min-w-0 text-start"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="font-semibold text-white">{task.title}</h2>
                    <span className="rounded-full border border-white/[0.08] px-2 py-0.5 text-[10px] text-white/45">
                      {task.status}
                    </span>
                    <span className="rounded-full border border-purple-500/20 bg-purple-500/10 px-2 py-0.5 text-[10px] text-purple-300">
                      {task.review_status}
                    </span>
                  </div>
                  <p className="mt-2 text-xs text-white/35">
                    {task.project || "No project"} ·{" "}
                    {task.assignee || "Unassigned"} · rework {task.rework_count}
                  </p>
                </button>
                <div className="flex flex-wrap gap-2">
                  {nextActions(task).map(([action, label]) => (
                    <button
                      key={action}
                      className={buttonClass}
                      disabled={busy === task.id}
                      onClick={() => void transition(task, action)}
                    >
                      {action === "approve" ? (
                        <CheckCircle2 className="h-3.5 w-3.5" />
                      ) : action === "rework" || action === "reopen" ? (
                        <Undo2 className="h-3.5 w-3.5" />
                      ) : (
                        <CheckSquare className="h-3.5 w-3.5" />
                      )}
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            </section>
          ))}
        </div>
      )}

      {selected && (
        <section className="glass-card p-6">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-white">
                {selected.title}
              </h2>
              <p className="mt-1 text-xs text-white/35">
                Durable comments and review evidence
              </p>
            </div>
            <button
              type="button"
              onClick={() => setSelected(null)}
              className="text-xs text-white/45 hover:text-white"
            >
              Close
            </button>
          </div>
          <div className="mt-5 space-y-3">
            {comments.length ? (
              comments.map((entry) => (
                <div
                  key={entry.id}
                  className="rounded-xl border border-white/[0.06] bg-black/15 p-4"
                >
                  <p className="whitespace-pre-wrap text-sm text-white/70">
                    {entry.body}
                  </p>
                  <p className="mt-2 text-[10px] text-white/30">
                    {entry.created_at}
                  </p>
                </div>
              ))
            ) : (
              <div className="text-sm text-white/35">No comments recorded.</div>
            )}
          </div>
          <div className="mt-5 flex flex-col gap-3 sm:flex-row">
            <textarea
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              placeholder="Add review evidence or a project comment"
              className={`${inputClass} min-h-24 flex-1`}
            />
            <button
              className={`${buttonClass} self-end`}
              disabled={!comment.trim() || busy === selected.id}
              onClick={() => void addComment()}
            >
              <Send className="h-4 w-4" /> Add comment
            </button>
          </div>
        </section>
      )}

      {!loading && tasks.some((task) => task.status === "blocked") && (
        <div className="flex items-start gap-3 rounded-xl border border-amber-500/20 bg-amber-500/10 p-4 text-sm text-amber-200">
          <AlertCircle className="mt-0.5 h-4 w-4" /> Blocked tasks remain
          visible until explicitly resumed, cancelled, or reassigned.
        </div>
      )}
    </div>
  );
}
