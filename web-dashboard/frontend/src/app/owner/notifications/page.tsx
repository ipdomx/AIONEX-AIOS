"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  Bell,
  CheckCircle2,
  Info,
  ShieldAlert,
} from "lucide-react";

import { useOwnerResource } from "@/hooks/use-owner-resource";

type Notification = {
  id: string;
  title: string;
  message: string;
  type: string;
  severity: string;
  read: boolean;
  createdAt: string;
};

function notificationCategory(type: string): string {
  return type.toLowerCase().split(/[.:/]/, 1)[0] ?? type.toLowerCase();
}

export default function OwnerNotificationsPage() {
  const {
    items: notifications,
    loading,
    busy,
    message,
    execute,
  } = useOwnerResource<Notification>("notifications");
  const [filter, setFilter] = useState("all");

  const visible = useMemo(
    () =>
      notifications.filter(
        (item) =>
          filter === "all" || notificationCategory(item.type) === filter,
      ),
    [filter, notifications],
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300">
            <Bell className="h-3.5 w-3.5" /> Owner notifications
          </div>
          <h1 className="text-2xl font-bold text-white">Notification Center</h1>
          <p className="mt-1 text-sm text-white/40">
            Owner-wide visibility into projects, approvals, incidents, staff,
            users and infrastructure.
          </p>
        </div>
        <button
          onClick={() => void execute("all", "mark-all-read")}
          disabled={busy || notifications.every((item) => item.read)}
          className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          Mark all read
        </button>
      </div>

      <div className="rounded-xl border border-electric-500/20 bg-electric-500/10 px-4 py-3 text-xs text-electric-300">
        {message}
      </div>

      <div className="flex flex-wrap gap-2">
        {["all", "project", "approval", "incident", "staff", "system"].map(
          (value) => (
            <button
              key={value}
              onClick={() => setFilter(value)}
              className={`rounded-xl border px-3 py-2 text-xs font-medium capitalize transition ${filter === value ? "border-electric-500/30 bg-electric-500/10 text-electric-300" : "border-white/[0.06] bg-white/[0.03] text-white/45 hover:bg-white/[0.06]"}`}
            >
              {value}
            </button>
          ),
        )}
      </div>

      <div className="space-y-3">
        {loading ? (
          <div className="glass-card p-8 text-center text-sm text-white/40">
            Loading live notifications…
          </div>
        ) : visible.length === 0 ? (
          <div className="glass-card p-8 text-center text-sm text-white/40">
            No notifications match this filter.
          </div>
        ) : (
          visible.map((item, index) => {
            const Icon =
              item.severity === "critical"
                ? ShieldAlert
                : item.severity === "warning"
                  ? AlertTriangle
                  : item.severity === "success"
                    ? CheckCircle2
                    : Info;
            const iconClass =
              item.severity === "critical"
                ? "text-red-400"
                : item.severity === "warning"
                  ? "text-orange-400"
                  : item.severity === "success"
                    ? "text-green-400"
                    : "text-electric-300";
            return (
              <motion.button
                disabled={busy || item.read}
                key={item.id}
                onClick={() => void execute(item.id, "mark-read")}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.03 }}
                className={`glass-card flex w-full items-start gap-4 p-5 text-left transition hover:bg-white/[0.05] disabled:cursor-default ${item.read ? "opacity-70" : "border border-electric-500/10"}`}
              >
                <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-2.5">
                  <Icon className={`h-5 w-5 ${iconClass}`} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-sm font-semibold text-white">
                      {item.title}
                    </h2>
                    {!item.read && (
                      <span className="h-2 w-2 rounded-full bg-electric-400" />
                    )}
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-white/45">
                    {item.message}
                  </p>
                  <div className="mt-3 flex items-center gap-3 text-[10px] uppercase tracking-wider text-white/25">
                    <span>{item.type}</span>
                    <span>{item.createdAt}</span>
                  </div>
                </div>
              </motion.button>
            );
          })
        )}
      </div>
    </div>
  );
}
