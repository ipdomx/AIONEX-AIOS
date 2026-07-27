"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, Bell, CheckCircle2, Info, ShieldAlert } from "lucide-react";

type Notification = {
  id: string;
  title: string;
  message: string;
  category: "project" | "approval" | "incident" | "staff" | "system";
  severity: "info" | "success" | "warning" | "critical";
  read: boolean;
  time: string;
};

const initialNotifications: Notification[] = [
  { id: "n1", title: "Project needs clarification", message: "AIOS Runtime Consolidation requires owner clarification before the next release gate.", category: "project", severity: "warning", read: false, time: "2m ago" },
  { id: "n2", title: "Approval required", message: "A new AI provider enablement request is awaiting your decision.", category: "approval", severity: "warning", read: false, time: "10m ago" },
  { id: "n3", title: "Security incident contained", message: "Automated defenses isolated a suspicious authentication pattern.", category: "incident", severity: "critical", read: false, time: "25m ago" },
  { id: "n4", title: "Project completed", message: "Phase 8 infrastructure validation completed successfully.", category: "project", severity: "success", read: true, time: "1h ago" },
  { id: "n5", title: "Staff performance report ready", message: "The weekly chief engineer and internal staff performance report is available.", category: "staff", severity: "info", read: true, time: "3h ago" },
  { id: "n6", title: "Backup verified", message: "The latest disaster-recovery backup passed integrity validation.", category: "system", severity: "success", read: true, time: "5h ago" },
];

export default function OwnerNotificationsPage() {
  const [notifications, setNotifications] = useState(initialNotifications);
  const [filter, setFilter] = useState("all");

  const visible = useMemo(
    () => notifications.filter((item) => filter === "all" || item.category === filter),
    [filter, notifications],
  );

  function markAllRead() {
    setNotifications((current) => current.map((item) => ({ ...item, read: true })));
  }

  function markRead(id: string) {
    setNotifications((current) => current.map((item) => (item.id === id ? { ...item, read: true } : item)));
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300"><Bell className="h-3.5 w-3.5" /> Owner notifications</div>
          <h1 className="text-2xl font-bold text-white">Notification Center</h1>
          <p className="mt-1 text-sm text-white/40">Owner-wide visibility into projects, approvals, incidents, staff, users and infrastructure.</p>
        </div>
        <button onClick={markAllRead} className="btn-primary">Mark all read</button>
      </div>

      <div className="flex flex-wrap gap-2">
        {["all", "project", "approval", "incident", "staff", "system"].map((value) => (
          <button key={value} onClick={() => setFilter(value)} className={`rounded-xl border px-3 py-2 text-xs font-medium capitalize transition ${filter === value ? "border-electric-500/30 bg-electric-500/10 text-electric-300" : "border-white/[0.06] bg-white/[0.03] text-white/45 hover:bg-white/[0.06]"}`}>{value}</button>
        ))}
      </div>

      <div className="space-y-3">
        {visible.map((item, index) => {
          const Icon = item.severity === "critical" ? ShieldAlert : item.severity === "warning" ? AlertTriangle : item.severity === "success" ? CheckCircle2 : Info;
          const iconClass = item.severity === "critical" ? "text-red-400" : item.severity === "warning" ? "text-orange-400" : item.severity === "success" ? "text-green-400" : "text-electric-300";
          return (
            <motion.button key={item.id} onClick={() => markRead(item.id)} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.03 }} className={`glass-card flex w-full items-start gap-4 p-5 text-left transition hover:bg-white/[0.05] ${item.read ? "opacity-70" : "border border-electric-500/10"}`}>
              <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-2.5"><Icon className={`h-5 w-5 ${iconClass}`} /></div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2"><h2 className="text-sm font-semibold text-white">{item.title}</h2>{!item.read && <span className="h-2 w-2 rounded-full bg-electric-400" />}</div>
                <p className="mt-1 text-xs leading-relaxed text-white/45">{item.message}</p>
                <div className="mt-3 flex items-center gap-3 text-[10px] uppercase tracking-wider text-white/25"><span>{item.category}</span><span>{item.time}</span></div>
              </div>
            </motion.button>
          );
        })}
      </div>
    </div>
  );
}
