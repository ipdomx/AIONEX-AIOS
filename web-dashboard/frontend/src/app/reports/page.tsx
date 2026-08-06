"use client";

import {
  Archive,
  BarChart3,
  Download,
  FileText,
  Loader2,
  Plus,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  phase29fApi,
  type ProjectRecord,
  type ReportRecord,
} from "@/lib/phase29f-api";

const inputClass =
  "glass-input rounded-xl px-3 py-2.5 text-sm text-white outline-none disabled:cursor-not-allowed disabled:opacity-50";
const buttonClass =
  "inline-flex items-center justify-center gap-2 rounded-xl border border-electric-500/20 bg-electric-500/10 px-3 py-2 text-xs font-semibold text-electric-200 transition hover:bg-electric-500/15 disabled:cursor-not-allowed disabled:opacity-50";

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function ReportsPage() {
  const [reports, setReports] = useState<ReportRecord[]>([]);
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setMessage("");
    try {
      const [reportRows, projectRows] = await Promise.all([
        phase29fApi.listReports({ limit: 100 }),
        phase29fApi.listProjects({ limit: 100 }),
      ]);
      setReports(reportRows);
      setProjects(projectRows);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Reports could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function createReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    const projectId = String(values.get("project_id") || "");
    const project = projects.find((item) => item.id === projectId);
    setBusy("create");
    try {
      await phase29fApi.createReport({
        name: String(values.get("name") || "").trim(),
        type: String(values.get("type") || "operations"),
        summary: String(values.get("summary") || "").trim() || null,
        project_id: projectId || null,
        workspace_id: project?.workspace_id || null,
        metrics: {},
        format: "json",
      });
      form.reset();
      setMessage("Report created, generated, and checksum-protected.");
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Report creation failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function generate(report: ReportRecord) {
    setBusy(report.id);
    try {
      const updated = await phase29fApi.generateReport(report.id);
      setReports((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setMessage("Report regenerated from retained project records.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Report generation failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function download(report: ReportRecord) {
    setBusy(report.id);
    try {
      const blob = await phase29fApi.downloadReport(report.id);
      saveBlob(blob, `aionex-report-${report.id.slice(0, 8)}.json`);
      setMessage("Checksum-verified report downloaded.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Report download failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function archive(report: ReportRecord) {
    setBusy(report.id);
    try {
      const updated = await phase29fApi.archiveReport(report.id);
      setReports((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setMessage("Report archived without losing its retained content.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Report archive failed.",
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
            <ShieldCheck className="h-3.5 w-3.5" /> Retained Evidence
          </div>
          <h1 className="mt-3 text-3xl font-bold text-white">
            Reports & Downloads
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Generate project reports from durable records, validate their
            checksum, download, and archive them.
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
        onSubmit={createReport}
        className="glass-card grid gap-3 p-5 lg:grid-cols-5"
      >
        <input
          name="name"
          minLength={2}
          required
          placeholder="Report name"
          className={`${inputClass} lg:col-span-2`}
        />
        <select name="project_id" defaultValue="" className={inputClass}>
          <option value="">Organization report</option>
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
        <select name="type" defaultValue="operations" className={inputClass}>
          <option value="operations">Operations</option>
          <option value="delivery">Delivery</option>
          <option value="quality">Quality</option>
          <option value="governance">Governance</option>
        </select>
        <button className={buttonClass} disabled={busy === "create"}>
          {busy === "create" ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Plus className="h-4 w-4" />
          )}{" "}
          Create report
        </button>
        <textarea
          name="summary"
          placeholder="Report purpose or executive summary"
          className={`${inputClass} min-h-20 lg:col-span-5`}
        />
      </form>

      {loading ? (
        <div className="glass-card flex min-h-48 items-center justify-center text-white/45">
          <Loader2 className="me-2 h-5 w-5 animate-spin" />
          Loading reports…
        </div>
      ) : reports.length === 0 ? (
        <div className="glass-card p-10 text-center text-sm text-white/40">
          No reports are currently recorded.
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {reports.map((report) => (
            <section key={report.id} className="glass-card p-5">
              <div className="flex items-start gap-3">
                <div className="rounded-xl border border-purple-500/20 bg-purple-500/10 p-2.5">
                  <FileText className="h-5 w-5 text-purple-300" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h2 className="font-semibold text-white">{report.name}</h2>
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] ${report.status === "archived" ? "bg-white/[0.06] text-white/35" : "bg-green-500/10 text-green-300"}`}
                    >
                      {report.status}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-white/35">
                    {report.type} · version {report.version} ·{" "}
                    {report.size_bytes || 0} bytes
                  </p>
                  <p className="mt-3 text-sm leading-6 text-white/50">
                    {report.summary || "Generated from retained AIOS records."}
                  </p>
                  <div className="mt-4 grid grid-cols-3 gap-2">
                    {Object.entries(report.metrics || {})
                      .slice(0, 3)
                      .map(([key, value]) => (
                        <div
                          key={key}
                          className="rounded-xl border border-white/[0.05] bg-black/15 p-3 text-center"
                        >
                          <BarChart3 className="mx-auto h-4 w-4 text-electric-300" />
                          <div className="mt-1 text-sm font-semibold text-white">
                            {String(value)}
                          </div>
                          <div className="text-[10px] text-white/30">
                            {key.replaceAll("_", " ")}
                          </div>
                        </div>
                      ))}
                  </div>
                  {report.checksum && (
                    <p className="mt-3 break-all font-mono text-[10px] text-white/25">
                      SHA-256 {report.checksum}
                    </p>
                  )}
                  <div className="mt-4 flex flex-wrap gap-2">
                    <button
                      className={buttonClass}
                      disabled={
                        busy === report.id || report.status === "archived"
                      }
                      onClick={() => void generate(report)}
                    >
                      <RefreshCw className="h-3.5 w-3.5" /> Regenerate
                    </button>
                    <button
                      className={buttonClass}
                      disabled={busy === report.id}
                      onClick={() => void download(report)}
                    >
                      <Download className="h-3.5 w-3.5" /> Download
                    </button>
                    <button
                      className={buttonClass}
                      disabled={
                        busy === report.id || report.status === "archived"
                      }
                      onClick={() => void archive(report)}
                    >
                      <Archive className="h-3.5 w-3.5" /> Archive
                    </button>
                  </div>
                </div>
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
