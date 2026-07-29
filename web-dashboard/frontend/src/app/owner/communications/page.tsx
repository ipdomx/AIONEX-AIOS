"use client";

import { useMemo } from "react";
import { motion } from "framer-motion";
import {
  Bell,
  Mail,
  MessageCircle,
  Smartphone,
  Send,
  ShieldCheck,
} from "lucide-react";

import { useOwnerResource } from "@/hooks/use-owner-resource";

type Channel = {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  configured: boolean;
  protected: boolean;
  ownerOnly: boolean;
  status: string;
};

const channelIcons: Record<string, React.ElementType> = {
  in_app: Bell,
  email: Mail,
  push: Smartphone,
  whatsapp: MessageCircle,
};

export default function OwnerCommunicationsPage() {
  const {
    items: channels,
    loading,
    busy,
    message,
    execute,
  } = useOwnerResource<Channel>("communications");
  const activeCount = useMemo(
    () => channels.filter((channel) => channel.enabled).length,
    [channels],
  );

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className="inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300">
          <ShieldCheck className="h-3.5 w-3.5" /> Owner Communications
        </div>
        <h1 className="mt-3 text-3xl font-bold text-white">
          Notification & Delivery Control
        </h1>
        <p className="mt-2 text-sm text-white/45">
          Verify configured delivery channels and persist Owner enablement
          choices. Test delivery uses the connected backend provider.
        </p>
      </motion.div>

      <div className="grid gap-4 sm:grid-cols-3">
        <div className="glass-card p-5">
          <p className="text-xs uppercase tracking-wider text-white/35">
            Active channels
          </p>
          <p className="mt-2 text-3xl font-bold text-white">{activeCount}</p>
        </div>
        <div className="glass-card p-5">
          <p className="text-xs uppercase tracking-wider text-white/35">
            Owner-only channels
          </p>
          <p className="mt-2 text-3xl font-bold text-white">
            {channels.filter((item) => item.ownerOnly).length}
          </p>
        </div>
        <div className="glass-card p-5">
          <p className="text-xs uppercase tracking-wider text-white/35">
            Delivery policy
          </p>
          <p className="mt-2 text-sm font-semibold text-green-400">Governed</p>
        </div>
      </div>

      <div className="rounded-xl border border-electric-500/20 bg-electric-500/10 px-4 py-3 text-sm text-electric-300">
        {message}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {loading ? (
          <div className="glass-card p-8 text-center text-sm text-white/40 lg:col-span-2">
            Loading live communication channels…
          </div>
        ) : channels.length === 0 ? (
          <div className="glass-card p-8 text-center text-sm text-white/40 lg:col-span-2">
            No communication channels are configured.
          </div>
        ) : (
          channels.map((channel, index) => {
            const Icon = channelIcons[channel.id] ?? Bell;
            return (
              <motion.section
                key={channel.id}
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.04 }}
                className="glass-card p-5"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex gap-3">
                    <div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5">
                      <Icon className="h-5 w-5 text-electric-300" />
                    </div>
                    <div>
                      <h2 className="text-sm font-semibold text-white">
                        {channel.name}
                      </h2>
                      <p className="mt-1 text-xs leading-relaxed text-white/40">
                        {channel.description}
                      </p>
                      {channel.ownerOnly && (
                        <span className="mt-2 inline-flex rounded-full border border-purple-500/20 bg-purple-500/10 px-2 py-0.5 text-[10px] text-purple-300">
                          Owner only
                        </span>
                      )}
                    </div>
                  </div>
                  <button
                    disabled={busy || channel.protected || !channel.configured}
                    onClick={() => void execute(channel.id, "toggle")}
                    className={`rounded-full px-3 py-1 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50 ${channel.enabled ? "bg-green-500/15 text-green-300" : "bg-white/[0.06] text-white/40"}`}
                  >
                    {channel.enabled ? "Enabled" : "Disabled"}
                  </button>
                </div>
                <div className="mt-5 flex justify-end border-t border-white/[0.06] pt-4">
                  <button
                    disabled={
                      busy ||
                      !channel.enabled ||
                      !["in_app", "email"].includes(channel.id)
                    }
                    onClick={() => void execute(channel.id, "test")}
                    className="inline-flex items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-xs text-white/70 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <Send className="h-3.5 w-3.5" /> Send test
                  </button>
                </div>
                <p className="mt-2 text-right text-[10px] uppercase tracking-wider text-white/25">
                  {channel.status}
                </p>
              </motion.section>
            );
          })
        )}
      </div>
    </div>
  );
}
