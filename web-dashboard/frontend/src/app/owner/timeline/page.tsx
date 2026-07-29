"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  Clock3,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import {
  fetchOwnerTimeline,
  type OwnerTimelineEvent,
} from "@/lib/owner-timeline";

export default function OwnerTimelinePage() {
  const [events, setEvents] = useState<OwnerTimelineEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState<
    "all" | OwnerTimelineEvent["category"]
  >("all");
  const [message, setMessage] = useState("Loading owner timeline...");

  async function load(signal?: AbortSignal) {
    setLoading(true);
    try {
      const data = await fetchOwnerTimeline(signal);
      setEvents(data);
      setMessage(
        `Timeline synchronized with ${data.length} event${data.length === 1 ? "" : "s"}.`,
      );
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setEvents([]);
        setMessage("Owner timeline backend contract is not available.");
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

  const visible = useMemo(
    () =>
      events.filter(
        (event) => category === "all" || event.category === category,
      ),
    [events, category],
  );

  const criticalCount = events.filter(
    (event) => event.severity === "critical",
  ).length;
  const warningCount = events.filter(
    (event) => event.severity === "warning",
  ).length;

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between"
      >
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300">
            <Clock3 className="h-3.5 w-3.5" /> Owner Global Timeline
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Unified Activity Timeline
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Single owner-visible record of project, user, approval, service,
            incident and security activity.
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
        <div className="glass-card p-5">
          <Activity className="h-5 w-5 text-electric-300" />
          <div className="mt-4 text-3xl font-bold text-white">
            {events.length}
          </div>
          <div className="mt-1 text-xs text-white/40">Total events</div>
        </div>
        <div className="glass-card p-5">
          <AlertTriangle className="h-5 w-5 text-orange-300" />
          <div className="mt-4 text-3xl font-bold text-white">
            {warningCount}
          </div>
          <div className="mt-1 text-xs text-white/40">Warnings</div>
        </div>
        <div className="glass-card p-5">
          <ShieldAlert className="h-5 w-5 text-red-300" />
          <div className="mt-4 text-3xl font-bold text-white">
            {criticalCount}
          </div>
          <div className="mt-1 text-xs text-white/40">Critical events</div>
        </div>
      </div>

      <div className="glass-card p-4">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="text-xs text-electric-300">{message}</div>
          <select
            value={category}
            onChange={(event) =>
              setCategory(event.target.value as typeof category)
            }
            className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"
          >
            <option value="all" className="bg-space-800">
              All categories
            </option>
            <option value="project" className="bg-space-800">
              Projects
            </option>
            <option value="user" className="bg-space-800">
              Users
            </option>
            <option value="security" className="bg-space-800">
              Security
            </option>
            <option value="approval" className="bg-space-800">
              Approvals
            </option>
            <option value="service" className="bg-space-800">
              Services
            </option>
            <option value="incident" className="bg-space-800">
              Incidents
            </option>
          </select>
        </div>
      </div>

      <div className="space-y-3">
        {visible.map((event, index) => (
          <motion.div
            key={event.id}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.025 }}
            className="glass-card p-5"
          >
            <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
              <div>
                <div className="text-sm font-semibold text-white">
                  {event.action}
                </div>
                <div className="mt-1 text-xs text-white/40">
                  {event.actor} · {event.target}
                </div>
                <p className="mt-3 text-sm text-white/55">{event.details}</p>
              </div>
              <div className="text-left xl:text-right">
                <div className="text-xs text-white/35">
                  {new Date(event.occurredAt).toLocaleString()}
                </div>
                <div
                  className={`mt-2 inline-flex rounded-full border px-2.5 py-1 text-xs ${event.severity === "critical" ? "border-red-500/20 bg-red-500/10 text-red-300" : event.severity === "warning" ? "border-orange-500/20 bg-orange-500/10 text-orange-300" : "border-electric-500/20 bg-electric-500/10 text-electric-300"}`}
                >
                  {event.category} · {event.severity}
                </div>
              </div>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
