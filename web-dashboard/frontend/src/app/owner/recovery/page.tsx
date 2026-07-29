"use client";

import { motion } from "framer-motion";
import { useEffect } from "react";
import {
  ArchiveRestore,
  CheckCircle2,
  DatabaseBackup,
  HardDriveDownload,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
} from "lucide-react";

import { useOwnerResource } from "@/hooks/use-owner-resource";

type RecoveryRecord = {
  id: string;
  name: string;
  kind: string;
  requestedAt: string;
  completedAt?: string | null;
  status: string;
  checksum?: string | null;
  artifactReady: boolean;
};

function formatTimestamp(value: string) {
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? value : timestamp.toLocaleString();
}

export default function OwnerRecoveryPage() {
  const { items, loading, busy, message, reload, refresh, execute } =
    useOwnerResource<RecoveryRecord>("recovery");
  const processing = items.some((record) =>
    ["pending", "running"].includes(record.status),
  );
  const completedBackupAvailable = items.some((record) => record.artifactReady);

  useEffect(() => {
    if (!processing) return;
    const controller = new AbortController();
    const timer = window.setInterval(() => {
      void refresh(controller.signal);
    }, 3000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [processing, refresh]);

  function createBackup() {
    void execute("platform", "create-backup", {
      kind: "on-demand",
      scope: "platform",
    });
  }

  function validateRestore() {
    void execute("latest", "validate-restore", {
      scope: "platform",
    });
  }

  function runDisasterRecoveryDrill() {
    void execute("platform", "dr-drill", {
      scope: "platform",
    });
  }

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className="inline-flex items-center gap-2 rounded-full border border-blue-500/20 bg-blue-500/10 px-3 py-1 text-xs text-blue-300">
          <ArchiveRestore className="h-3.5 w-3.5" /> Owner Recovery Center
        </div>
        <h1 className="mt-3 text-3xl font-bold text-white">
          Backup, Restore &amp; Disaster Recovery
        </h1>
        <p className="mt-2 text-sm text-white/45">
          Owner-level continuity controls for protected backups, restore
          validation, failover readiness and recovery evidence.
        </p>
      </motion.div>

      <div className="rounded-xl border border-electric-500/20 bg-electric-500/10 px-4 py-3 text-sm text-electric-300">
        {loading ? "Loading recovery records..." : message}
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <button
          onClick={createBackup}
          disabled={loading || busy || processing}
          className="glass-card p-5 text-left transition hover:bg-white/[0.05] disabled:cursor-not-allowed disabled:opacity-50"
        >
          <DatabaseBackup className="h-6 w-6 text-electric-300" />
          <h2 className="mt-4 text-sm font-semibold text-white">
            Queue backup
          </h2>
          <p className="mt-2 text-xs text-white/40">
            Queue a durable on-demand PostgreSQL backup job.
          </p>
        </button>
        <button
          onClick={validateRestore}
          disabled={loading || busy || processing || !completedBackupAvailable}
          className="glass-card p-5 text-left transition hover:bg-white/[0.05] disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RotateCcw className="h-6 w-6 text-purple-300" />
          <h2 className="mt-4 text-sm font-semibold text-white">
            Queue restore validation
          </h2>
          <p className="mt-2 text-xs text-white/40">
            Restore the latest protected archive into an isolated scratch
            database.
          </p>
        </button>
        <button
          onClick={runDisasterRecoveryDrill}
          disabled={loading || busy || processing || !completedBackupAvailable}
          className="glass-card p-5 text-left transition hover:bg-white/[0.05] disabled:cursor-not-allowed disabled:opacity-50"
        >
          <ShieldAlert className="h-6 w-6 text-orange-300" />
          <h2 className="mt-4 text-sm font-semibold text-white">
            Run DR drill
          </h2>
          <p className="mt-2 text-xs text-white/40">
            Queue a real restore drill and persist its release evidence.
          </p>
        </button>
      </div>

      <section className="glass-card overflow-hidden">
        <div className="flex items-center justify-between border-b border-white/[0.06] p-5">
          <h2 className="text-sm font-semibold text-white">Protected assets</h2>
          <button
            type="button"
            onClick={() => void reload()}
            disabled={loading || busy}
            className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-white/60 transition hover:bg-white/[0.05] disabled:opacity-50"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${processing ? "animate-spin" : ""}`}
            />
            Refresh
          </button>
        </div>
        <div className="divide-y divide-white/[0.05]">
          {!loading && items.length === 0 && (
            <div className="p-5 text-sm text-white/45">
              No backup or recovery requests exist yet.
            </div>
          )}
          {items.map((record) => (
            <div
              key={record.id}
              className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="flex items-center gap-3">
                <HardDriveDownload className="h-5 w-5 text-electric-300" />
                <div>
                  <p className="text-sm font-medium text-white">
                    {record.name}
                  </p>
                  <p className="mt-1 text-xs text-white/35">
                    {record.kind} · Requested:{" "}
                    {formatTimestamp(record.requestedAt)}
                    {record.completedAt
                      ? ` · Completed: ${formatTimestamp(record.completedAt)}`
                      : ""}
                  </p>
                </div>
              </div>
              <span
                className={`inline-flex items-center gap-1 text-xs ${
                  ["completed", "healthy", "protected"].includes(record.status)
                    ? "text-green-400"
                    : "text-orange-300"
                }`}
              >
                <CheckCircle2 className="h-4 w-4" />
                {record.status}
              </span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
