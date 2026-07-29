"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  RefreshCw,
  RadioTower,
  Server,
  ShieldCheck,
} from "lucide-react";
import {
  fetchOwnerRealtimeSnapshot,
  type OwnerRealtimeSnapshot,
} from "@/lib/owner-realtime";

const emptySnapshot: OwnerRealtimeSnapshot = {
  generatedAt: "",
  metrics: [],
  events: [],
};

const statusClass: Record<"healthy" | "warning" | "critical", string> = {
  healthy: "border-green-500/20 bg-green-500/10 text-green-300",
  warning: "border-orange-500/20 bg-orange-500/10 text-orange-300",
  critical: "border-red-500/20 bg-red-500/10 text-red-300",
};

export default function OwnerRealtimePage() {
  const [snapshot, setSnapshot] = useState(emptySnapshot);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState(
    "Connecting to owner realtime data...",
  );

  async function load(signal?: AbortSignal) {
    setLoading(true);
    try {
      const data = await fetchOwnerRealtimeSnapshot(signal);
      setSnapshot(data);
      setMessage(
        `Realtime synchronized at ${new Date(data.generatedAt).toLocaleTimeString()}.`,
      );
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setSnapshot(emptySnapshot);
        setMessage("Realtime Owner backend contract is not available.");
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, []);

  const summary = useMemo(
    () => ({
      healthy: snapshot.metrics.filter((metric) => metric.status === "healthy")
        .length,
      warning: snapshot.metrics.filter((metric) => metric.status === "warning")
        .length,
      critical: snapshot.metrics.filter(
        (metric) => metric.status === "critical",
      ).length,
    }),
    [snapshot],
  );

  const cards: Array<{
    label: string;
    value: number;
    Icon: typeof ShieldCheck;
  }> = [
    { label: "Healthy", value: summary.healthy, Icon: ShieldCheck },
    { label: "Warnings", value: summary.warning, Icon: AlertTriangle },
    { label: "Critical", value: summary.critical, Icon: Server },
  ];

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between"
      >
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300">
            <RadioTower className="h-3.5 w-3.5" /> Owner Realtime Control
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Live Runtime Monitoring
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Continuous owner visibility into workers, queues, latency, errors
            and critical runtime events.
          </p>
        </div>
        <button
          disabled={loading}
          onClick={() => void load()}
          className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {cards.map(({ label, value, Icon }) => (
          <div key={label} className="glass-card p-5">
            <Icon className="h-5 w-5 text-electric-300" />
            <div className="mt-4 text-3xl font-bold text-white">{value}</div>
            <div className="mt-1 text-xs text-white/40">{label}</div>
          </div>
        ))}
      </div>

      <div className="glass-card p-4 text-xs text-electric-300">
        <Activity className="mr-2 inline h-3.5 w-3.5" />
        {message}
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {snapshot.metrics.map((metric, index) => (
          <motion.div
            key={metric.id}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.03 }}
            className="glass-card p-5"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-xs uppercase tracking-wider text-white/30">
                  {metric.label}
                </div>
                <div className="mt-2 text-3xl font-bold text-white">
                  {metric.value}
                  <span className="ml-1 text-sm font-medium text-white/35">
                    {metric.unit}
                  </span>
                </div>
                <div className="mt-2 text-xs text-white/30">
                  Updated {metric.updatedAt}
                </div>
              </div>
              <span
                className={`rounded-full border px-2.5 py-1 text-xs ${statusClass[metric.status]}`}
              >
                {metric.status}
              </span>
            </div>
          </motion.div>
        ))}
      </div>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-white">Live events</h2>
        {snapshot.events.map((event) => (
          <div
            key={event.id}
            className="glass-card flex flex-col gap-2 p-4 md:flex-row md:items-center md:justify-between"
          >
            <div>
              <div className="text-sm font-medium text-white">
                {event.message}
              </div>
              <div className="mt-1 text-xs text-white/35">{event.source}</div>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-xs text-white/30">{event.createdAt}</span>
              <span
                className={`rounded-full border px-2.5 py-1 text-xs ${event.severity === "critical" ? statusClass.critical : event.severity === "warning" ? statusClass.warning : statusClass.healthy}`}
              >
                {event.severity}
              </span>
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}
