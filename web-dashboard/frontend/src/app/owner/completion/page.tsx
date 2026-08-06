"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  ExternalLink,
  Layers3,
  PauseCircle,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";

import { ownerNavigationSections } from "@/config/owner-navigation";
import {
  EMPTY_OWNER_COMPLETION_PROGRAM,
  fetchOwnerFinalizationSnapshot,
  type OwnerCompletionBatch,
  type OwnerFinalizationSnapshot,
} from "@/lib/owner-finalization";

const emptySnapshot: OwnerFinalizationSnapshot = {
  generatedAt: "",
  completion: 0,
  checks: [],
  program: EMPTY_OWNER_COMPLETION_PROGRAM,
};

const batchClass: Record<OwnerCompletionBatch["status"], string> = {
  complete: "border-green-500/20 bg-green-500/10 text-green-300",
  pending: "border-orange-500/20 bg-orange-500/10 text-orange-300",
  deferred: "border-blue-500/20 bg-blue-500/10 text-blue-300",
};

export default function OwnerCompletionPage() {
  const [snapshot, setSnapshot] = useState(emptySnapshot);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("Checking production readiness...");

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const result = await fetchOwnerFinalizationSnapshot(signal);
      setSnapshot(result);
      setMessage(
        `Runtime readiness ${result.completion}% · completion program ${result.program.completion}%.`,
      );
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setSnapshot(emptySnapshot);
        setMessage(
          error instanceof Error ? error.message : "Readiness check failed",
        );
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const counts = useMemo(
    () => ({
      complete: snapshot.program.batches.filter(
        (batch) => batch.status === "complete",
      ).length,
      pending: snapshot.program.batches.filter(
        (batch) => batch.status === "pending",
      ).length,
      deferred: snapshot.program.batches.filter(
        (batch) => batch.status === "deferred",
      ).length,
    }),
    [snapshot.program.batches],
  );

  return (
    <div className="space-y-6">
      <header className="glass-card p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex items-start gap-3">
            <ShieldCheck className="mt-1 h-7 w-7 flex-shrink-0 text-electric-300" />
            <div>
              <h1 className="text-2xl font-bold text-white">
                Platform Completion Program
              </h1>
              <p className="mt-1 max-w-4xl text-sm leading-relaxed text-white/45">
                Evidence-backed inventory of every AIOS module, Owner page,
                public portal page, backend endpoint, and completion batch. AI
                models and providers are deliberately reserved for the final
                batch.
              </p>
            </div>
          </div>
          <button
            type="button"
            disabled={loading}
            onClick={() => void load()}
            className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refresh evidence
          </button>
        </div>
      </header>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <div className="glass-card p-5">
          <ShieldCheck className="h-5 w-5 text-electric-300" />
          <div className="mt-4 text-3xl font-bold text-white">
            {snapshot.completion}%
          </div>
          <div className="mt-1 text-xs text-white/40">Runtime readiness</div>
        </div>
        <div className="glass-card p-5">
          <Layers3 className="h-5 w-5 text-electric-300" />
          <div className="mt-4 text-3xl font-bold text-white">
            {snapshot.program.completion}%
          </div>
          <div className="mt-1 text-xs text-white/40">
            Full platform completion
          </div>
        </div>
        <div className="glass-card p-5">
          <CheckCircle2 className="h-5 w-5 text-green-300" />
          <div className="mt-4 text-3xl font-bold text-white">
            {counts.complete}/{snapshot.program.batches.length || 10}
          </div>
          <div className="mt-1 text-xs text-white/40">Batches closed</div>
        </div>
        <div className="glass-card p-5">
          <Clock3 className="h-5 w-5 text-orange-300" />
          <div className="mt-4 text-3xl font-bold text-white">
            {snapshot.program.current_batch || "—"}
          </div>
          <div className="mt-1 text-xs text-white/40">Current batch</div>
        </div>
      </section>

      <section className="glass-card p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-sm font-semibold text-white">
              No-omission completion contract
            </h2>
            <p className="mt-1 text-xs leading-relaxed text-white/45">
              {snapshot.program.verified_features} verified of{" "}
              {snapshot.program.actionable_features} non-provider features.{" "}
              {snapshot.program.deferred_features} provider/model feature is
              held for {snapshot.program.models_providers_batch}, the final
              batch.
            </p>
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
            <span className="rounded-full border border-green-500/20 bg-green-500/10 px-3 py-1 text-green-300">
              {counts.complete} complete
            </span>
            <span className="rounded-full border border-orange-500/20 bg-orange-500/10 px-3 py-1 text-orange-300">
              {counts.pending} pending
            </span>
            <span className="rounded-full border border-blue-500/20 bg-blue-500/10 px-3 py-1 text-blue-300">
              {counts.deferred} deferred
            </span>
          </div>
        </div>
        <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/[0.05]">
          <div
            className="h-full rounded-full bg-electric-400"
            style={{ width: `${snapshot.program.completion}%` }}
          />
        </div>
        <p className="mt-3 text-xs text-electric-300">{message}</p>
      </section>

      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <Layers3 className="h-4 w-4 text-electric-300" />
          <h2 className="text-sm font-semibold text-white">
            Completion batches
          </h2>
        </div>
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {snapshot.program.batches.map((batch) => (
            <article key={batch.batch_id} className="glass-card p-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs font-semibold text-electric-300">
                    Batch {batch.batch_id}
                  </p>
                  <h3 className="mt-1 text-sm font-semibold text-white">
                    {batch.title}
                  </h3>
                </div>
                <span
                  className={`rounded-full border px-2.5 py-1 text-xs ${batchClass[batch.status]}`}
                >
                  {batch.status}
                </span>
              </div>
              <p className="mt-3 text-xs leading-relaxed text-white/45">
                {batch.objective}
              </p>
              <div className="mt-4 flex items-center justify-between text-[11px] text-white/35">
                <span>
                  {batch.verified_features}/{batch.total_features} features
                  verified
                </span>
                {batch.status === "deferred" ? (
                  <PauseCircle className="h-4 w-4 text-blue-300" />
                ) : batch.status === "complete" ? (
                  <CheckCircle2 className="h-4 w-4 text-green-300" />
                ) : (
                  <AlertTriangle className="h-4 w-4 text-orange-300" />
                )}
              </div>
              <div className="mt-4 space-y-2 border-t border-white/[0.05] pt-4">
                {batch.features.map((feature) => (
                  <div
                    key={feature.feature_id}
                    className="flex items-start justify-between gap-3 text-xs"
                  >
                    <span className="text-white/55">{feature.title}</span>
                    <span className="flex-shrink-0 text-white/30">
                      {feature.status}
                    </span>
                  </div>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="glass-card p-5">
        <h2 className="text-sm font-semibold text-white">
          Live release and dependency checks
        </h2>
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {snapshot.checks.map((check) => (
            <div
              key={check.id}
              className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4"
            >
              <div className="flex items-center gap-2">
                {check.status === "passed" ? (
                  <CheckCircle2 className="h-4 w-4 text-green-400" />
                ) : (
                  <AlertTriangle className="h-4 w-4 text-orange-300" />
                )}
                <span className="text-sm font-medium text-white">
                  {check.label}
                </span>
              </div>
              <p className="mt-2 text-xs text-white/40">{check.details}</p>
            </div>
          ))}
        </div>
      </section>

      {ownerNavigationSections.map((section) => (
        <section key={section.id} className="space-y-3">
          <h2 className="text-sm font-semibold text-white">{section.label}</h2>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {section.items.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="glass-card flex items-center gap-3 p-4 transition hover:bg-white/[0.05]"
              >
                <ExternalLink className="h-5 w-5 text-electric-300" />
                <span className="flex-1 text-sm font-medium text-white/75">
                  {item.label}
                </span>
                <span className="text-[10px] text-white/30">Open</span>
              </Link>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
