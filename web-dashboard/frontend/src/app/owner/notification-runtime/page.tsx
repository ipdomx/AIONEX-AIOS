"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import {
  Bell,
  Mail,
  MessageCircle,
  RefreshCw,
  Send,
  Smartphone,
  ToggleLeft,
  ToggleRight,
} from "lucide-react";
import {
  fetchNotificationRules,
  updateNotificationRule,
  type OwnerNotificationRule,
} from "@/lib/owner-notification-runtime";

const severityClass: Record<OwnerNotificationRule["severity"], string> = {
  info: "border-blue-500/20 bg-blue-500/10 text-blue-300",
  warning: "border-orange-500/20 bg-orange-500/10 text-orange-300",
  critical: "border-red-500/20 bg-red-500/10 text-red-300",
};

const channelIcon: Record<
  OwnerNotificationRule["channels"][number],
  LucideIcon
> = {
  in_app: Bell,
  email: Mail,
  push: Smartphone,
  telegram: Send,
  whatsapp: MessageCircle,
};

type SummaryCard = readonly [label: string, value: number, icon: LucideIcon];

export default function OwnerNotificationRuntimePage() {
  const [items, setItems] = useState<OwnerNotificationRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("Loading notification rules...");

  async function load(signal?: AbortSignal) {
    setLoading(true);
    try {
      const data = await fetchNotificationRules(signal);
      setItems(data);
      setMessage("Notification rules synchronized.");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setItems([]);
        setMessage("Notification rules backend contract is not available.");
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
      enabled: items.filter((item) => item.enabled).length,
      critical: items.filter((item) => item.severity === "critical").length,
      whatsapp: items.filter((item) => item.channels.includes("whatsapp"))
        .length,
    }),
    [items],
  );

  const cards: SummaryCard[] = [
    ["Enabled rules", summary.enabled, ToggleRight],
    ["Critical rules", summary.critical, Bell],
    ["WhatsApp rules", summary.whatsapp, MessageCircle],
  ];

  async function toggle(id: string) {
    const current = items.find((item) => item.id === id);
    if (!current) return;
    const next = !current.enabled;
    setMessage("Updating notification rule...");
    try {
      const updated = await updateNotificationRule(id, { enabled: next });
      setItems((value) =>
        value.map((item) => (item.id === id ? updated : item)),
      );
      setMessage("Notification rule updated.");
    } catch {
      setMessage("Notification update failed and was not persisted.");
    }
  }

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between"
      >
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300">
            <Bell className="h-3.5 w-3.5" /> Owner Notification Registry
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Notification Routing Rules
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Persist routing declarations for project, incident and clarification
            events. A channel delivers only when its provider and event consumer
            are connected.
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
        {cards.map(([label, value, Icon]) => (
          <div key={label} className="glass-card p-5">
            <Icon className="h-5 w-5 text-electric-300" />
            <div className="mt-4 text-3xl font-bold text-white">{value}</div>
            <div className="mt-1 text-xs text-white/40">{label}</div>
          </div>
        ))}
      </div>

      <div className="glass-card p-4 text-xs text-electric-300">{message}</div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {items.map((item, index) => (
          <motion.div
            key={item.id}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.03 }}
            className="glass-card p-5"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-sm font-semibold text-white">
                  {item.name}
                </h2>
                <p className="mt-1 text-xs text-white/40">
                  {item.event} · {item.audience} · {item.updatedAt}
                </p>
              </div>
              <span
                className={`rounded-full border px-2.5 py-1 text-xs ${severityClass[item.severity]}`}
              >
                {item.severity}
              </span>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {item.channels.map((channel) => {
                const Icon = channelIcon[channel] ?? Bell;
                return (
                  <span
                    key={channel}
                    className="rounded-lg border border-white/[0.06] bg-white/[0.03] px-2.5 py-1.5 text-xs text-white/55"
                  >
                    <Icon className="mr-1 inline h-3.5 w-3.5" />
                    {channel}
                  </span>
                );
              })}
            </div>
            <button
              onClick={() => void toggle(item.id)}
              className="mt-4 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-xs text-white/70"
            >
              {item.enabled ? (
                <ToggleRight className="mr-1 inline h-3.5 w-3.5" />
              ) : (
                <ToggleLeft className="mr-1 inline h-3.5 w-3.5" />
              )}
              {item.enabled ? "Disable" : "Enable"}
            </button>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
