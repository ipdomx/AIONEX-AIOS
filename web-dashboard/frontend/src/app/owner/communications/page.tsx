"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Bell,
  CheckCircle2,
  Clock3,
  Mail,
  MessageCircle,
  RefreshCw,
  RotateCcw,
  Send,
  ShieldCheck,
  Smartphone,
  TicketCheck,
} from "lucide-react";

import { useOwnerResource } from "@/hooks/use-owner-resource";
import {
  fetchCommunicationDeliveries,
  fetchCommunicationOverview,
  fetchOwnerSupportTickets,
  retryCommunicationDelivery,
  updateOwnerSupportTicket,
  type CommunicationDelivery,
  type CommunicationOverview,
  type SupportTicket,
} from "@/lib/owner-communications";

type Channel = {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  configured: boolean;
  protected: boolean;
  ownerOnly: boolean;
  status: string;
  reason?: string;
  deliveries?: number;
  capabilities?: string[];
};

const channelIcons: Record<string, React.ElementType> = {
  in_app: Bell,
  email: Mail,
  push: Smartphone,
  telegram: Send,
  whatsapp: MessageCircle,
};

function dateValue(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function statusClass(status: string): string {
  if (["delivered", "acknowledged", "resolved", "closed"].includes(status)) {
    return "border-green-500/20 bg-green-500/10 text-green-300";
  }
  if (["dead_letter", "failed", "urgent", "cancelled"].includes(status)) {
    return "border-red-500/20 bg-red-500/10 text-red-300";
  }
  if (
    ["retrying", "waiting_user", "in_progress", "suspended"].includes(status)
  ) {
    return "border-amber-500/20 bg-amber-500/10 text-amber-200";
  }
  return "border-white/10 bg-white/[0.04] text-white/55";
}

export default function OwnerCommunicationsPage() {
  const {
    items: channels,
    loading: channelsLoading,
    busy: channelBusy,
    message: channelMessage,
    execute,
  } = useOwnerResource<Channel>("communications");
  const [overview, setOverview] = useState<CommunicationOverview | null>(null);
  const [deliveries, setDeliveries] = useState<CommunicationDelivery[]>([]);
  const [tickets, setTickets] = useState<SupportTicket[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState(
    "Loading durable communication evidence…",
  );

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const [nextOverview, nextDeliveries, nextTickets] = await Promise.all([
        fetchCommunicationOverview(signal),
        fetchCommunicationDeliveries(signal),
        fetchOwnerSupportTickets(signal),
      ]);
      setOverview(nextOverview);
      setDeliveries(nextDeliveries);
      setTickets(nextTickets);
      setMessage(
        "Communication queues, receipts, and support records synchronized.",
      );
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setMessage(
          error instanceof Error
            ? error.message
            : "Communication evidence could not be loaded.",
        );
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const activeCount = useMemo(
    () => channels.filter((channel) => channel.enabled).length,
    [channels],
  );
  const pendingCount = useMemo(
    () =>
      deliveries.filter((item) => ["queued", "retrying"].includes(item.status))
        .length,
    [deliveries],
  );
  const deadLetterCount = useMemo(
    () => deliveries.filter((item) => item.status === "dead_letter").length,
    [deliveries],
  );
  const openTickets = useMemo(
    () =>
      tickets.filter(
        (item) =>
          !["resolved", "closed", "cancelled", "suspended"].includes(
            item.status,
          ),
      ),
    [tickets],
  );

  async function retry(delivery: CommunicationDelivery) {
    if (busyId) return;
    setBusyId(delivery.id);
    setMessage("Re-queueing the selected delivery…");
    try {
      await retryCommunicationDelivery(delivery.id);
      await load();
      setMessage("Delivery was safely returned to the durable queue.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Delivery retry failed.",
      );
    } finally {
      setBusyId(null);
    }
  }

  async function resolve(ticket: SupportTicket) {
    if (busyId) return;
    setBusyId(ticket.id);
    setMessage("Resolving the selected support request…");
    try {
      await updateOwnerSupportTicket(ticket.id, "resolved");
      await load();
      setMessage("Support request resolved and retained in the audit trail.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Support update failed.",
      );
    } finally {
      setBusyId(null);
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
          <div className="inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300">
            <ShieldCheck className="h-3.5 w-3.5" /> Owner Communications
          </div>
          <h1 className="mt-3 text-3xl font-bold text-white">
            Notification, Delivery & Support Control
          </h1>
          <p className="mt-2 max-w-3xl text-sm text-white/45">
            Durable in-app records, truthful provider readiness, delivery
            receipts, retries, dead-letter recovery, and private support intake.
          </p>
        </div>
        <button
          disabled={loading || busyId !== null}
          onClick={() => void load()}
          className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh evidence
        </button>
      </motion.div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {[
          ["Active channels", activeCount, CheckCircle2],
          ["Queued deliveries", pendingCount, Clock3],
          ["Dead-letter records", deadLetterCount, RotateCcw],
          ["Open support requests", openTickets.length, TicketCheck],
          ["Delivered receipts", overview?.by_status.delivered || 0, Send],
        ].map(([label, value, Icon]) => {
          const CardIcon = Icon as React.ElementType;
          return (
            <div key={String(label)} className="glass-card p-5">
              <CardIcon className="h-5 w-5 text-electric-300" />
              <p className="mt-3 text-2xl font-bold text-white">
                {String(value)}
              </p>
              <p className="mt-1 text-xs text-white/35">{String(label)}</p>
            </div>
          );
        })}
      </div>

      <div className="rounded-xl border border-electric-500/20 bg-electric-500/10 px-4 py-3 text-sm text-electric-300">
        {message || channelMessage}
      </div>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-white">
          Truthful channel readiness
        </h2>
        <div className="grid gap-4 lg:grid-cols-2">
          {channelsLoading ? (
            <div className="glass-card p-8 text-center text-sm text-white/40 lg:col-span-2">
              Loading live communication channels…
            </div>
          ) : (
            channels.map((channel, index) => {
              const Icon = channelIcons[channel.id] ?? Bell;
              return (
                <motion.article
                  key={channel.id}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.03 }}
                  className="glass-card p-5"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex gap-3">
                      <div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5">
                        <Icon className="h-5 w-5 text-electric-300" />
                      </div>
                      <div>
                        <h3 className="text-sm font-semibold text-white">
                          {channel.name}
                        </h3>
                        <p className="mt-1 text-xs leading-relaxed text-white/40">
                          {channel.description}
                        </p>
                        <p className="mt-2 text-[11px] text-white/30">
                          {channel.reason || channel.status} ·{" "}
                          {channel.deliveries || 0} deliveries
                        </p>
                      </div>
                    </div>
                    <button
                      disabled={
                        channelBusy || channel.protected || !channel.configured
                      }
                      onClick={() => void execute(channel.id, "toggle")}
                      className={`rounded-full px-3 py-1 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50 ${channel.enabled ? "bg-green-500/15 text-green-300" : "bg-white/[0.06] text-white/40"}`}
                    >
                      {channel.enabled ? "Enabled" : "Disabled"}
                    </button>
                  </div>
                </motion.article>
              );
            })
          )}
        </div>
      </section>

      <section className="glass-card overflow-hidden">
        <div className="border-b border-white/[0.06] p-5">
          <h2 className="text-sm font-semibold text-white">
            Delivery receipts & recovery
          </h2>
          <p className="mt-1 text-xs text-white/35">
            Every external attempt remains durable, including unconfigured and
            dead-letter states.
          </p>
        </div>
        <div className="divide-y divide-white/[0.05]">
          {deliveries.length === 0 ? (
            <p className="p-6 text-center text-sm text-white/40">
              No delivery records are available.
            </p>
          ) : (
            deliveries.slice(0, 20).map((delivery) => (
              <div
                key={delivery.id}
                className="flex flex-col gap-3 p-4 xl:flex-row xl:items-center xl:justify-between"
              >
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-white">
                      {delivery.channel}
                    </span>
                    <span
                      className={`rounded-full border px-2 py-0.5 text-[10px] ${statusClass(delivery.status)}`}
                    >
                      {delivery.status}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-white/35">
                    Attempts {delivery.attempt_count}/{delivery.max_attempts} ·{" "}
                    {dateValue(delivery.updated_at)}
                  </p>
                </div>
                <button
                  disabled={
                    busyId !== null ||
                    !["dead_letter", "failed", "unconfigured"].includes(
                      delivery.status,
                    )
                  }
                  onClick={() => void retry(delivery)}
                  className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-xs text-white/65 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <RotateCcw className="h-3.5 w-3.5" /> Retry delivery
                </button>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="glass-card overflow-hidden">
        <div className="border-b border-white/[0.06] p-5">
          <h2 className="text-sm font-semibold text-white">
            Private support intake
          </h2>
          <p className="mt-1 text-xs text-white/35">
            Requests remain tenant-owned while the Super Owner has complete
            platform visibility.
          </p>
        </div>
        <div className="divide-y divide-white/[0.05]">
          {tickets.length === 0 ? (
            <p className="p-6 text-center text-sm text-white/40">
              No support requests are recorded.
            </p>
          ) : (
            tickets.slice(0, 20).map((ticket) => (
              <div
                key={ticket.id}
                className="flex flex-col gap-3 p-4 xl:flex-row xl:items-center xl:justify-between"
              >
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-white">
                      {ticket.subject}
                    </span>
                    <span
                      className={`rounded-full border px-2 py-0.5 text-[10px] ${statusClass(ticket.status)}`}
                    >
                      {ticket.status}
                    </span>
                    <span className="text-[10px] uppercase tracking-wider text-white/25">
                      {ticket.priority}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-white/35">
                    {ticket.category} · {ticket.organization_id} ·{" "}
                    {dateValue(ticket.updated_at)}
                  </p>
                </div>
                <button
                  disabled={
                    busyId !== null ||
                    ["resolved", "closed", "cancelled", "suspended"].includes(
                      ticket.status,
                    )
                  }
                  onClick={() => void resolve(ticket)}
                  className="inline-flex items-center justify-center gap-2 rounded-xl border border-green-500/20 bg-green-500/10 px-3 py-2 text-xs text-green-300 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <TicketCheck className="h-3.5 w-3.5" /> Resolve request
                </button>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
