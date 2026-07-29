"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  ExternalLink,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";

import { ownerNavigationSections } from "@/config/owner-navigation";
import {
  fetchOwnerFinalizationSnapshot,
  type OwnerFinalizationSnapshot,
} from "@/lib/owner-finalization";

const emptySnapshot: OwnerFinalizationSnapshot = {
  generatedAt: "",
  completion: 0,
  checks: [],
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
      setMessage(`Live readiness is ${result.completion}%.`);
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

  return (
    <div className="space-y-6">
      <header className="glass-card p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <ShieldCheck className="h-7 w-7 text-electric-300" />
            <div>
              <h1 className="text-2xl font-bold text-white">
                Owner Dashboard Completion
              </h1>
              <p className="mt-1 text-sm text-white/45">
                Live dependency health and evidence-backed release gates, plus
                the complete Owner route inventory.
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
            Run live checks
          </button>
        </div>
      </header>
      <section className="glass-card p-5">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold text-white">
              Production readiness
            </h2>
            <p className="mt-1 text-xs text-white/45">{message}</p>
          </div>
          <div className="text-3xl font-bold text-white">
            {snapshot.completion}%
          </div>
        </div>
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
      <section className="glass-card p-5">
        <div className="flex items-start gap-3">
          <ClipboardCheck className="mt-0.5 h-5 w-5 text-electric-300" />
          <div>
            <h2 className="text-sm font-semibold text-white">
              Final deployment gate
            </h2>
            <p className="mt-2 text-xs leading-relaxed text-white/45">
              Deploy only when the live checks above reach 100% and CodeQL and
              Final Validation succeed. A completed backup, current performance
              evidence, security clearance, and explicit Owner approval are all
              required.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
