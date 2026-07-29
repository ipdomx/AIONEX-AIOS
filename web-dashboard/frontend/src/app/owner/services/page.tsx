"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Bot,
  CheckCircle2,
  Cloud,
  Database,
  Globe2,
  Lock,
  Server,
  Shield,
  ToggleLeft,
  ToggleRight,
  Workflow,
} from "lucide-react";

import { useOwnerResource } from "@/hooks/use-owner-resource";

type Service = {
  id: string;
  name: string;
  category: string;
  description: string;
  enabled: boolean;
  protected: boolean;
  scope: string;
};

function iconFor(service: Service): React.ElementType {
  if (service.id === "vault") return Lock;
  if (service.category === "AI Providers") return Bot;
  if (service.category === "Engineering") return Workflow;
  if (service.category === "Cloud") return Cloud;
  if (service.category === "Data") return Database;
  if (service.category === "Security") return Shield;
  if (service.category === "Infrastructure") return Server;
  return Globe2;
}

export default function OwnerServicesPage() {
  const {
    items: services,
    loading,
    busy,
    message,
    execute,
  } = useOwnerResource<Service>("services");
  const [category, setCategory] = useState("All");
  const categories = useMemo(
    () => [
      "All",
      ...Array.from(new Set(services.map((service) => service.category))),
    ],
    [services],
  );
  const visible =
    category === "All"
      ? services
      : services.filter((service) => service.category === category);
  const enabledCount = services.filter((service) => service.enabled).length;

  function toggleService(service: Service) {
    if (
      service.enabled &&
      !window.confirm(
        `Block ${service.name}? Dependent optional platform features may stop working.`,
      )
    ) {
      return;
    }
    void execute(service.id, "toggle");
  }

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between"
      >
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            Owner Service Control
          </h1>
          <p className="mt-1 text-sm text-white/40">
            Persist owner allow/block policies for optional platform services.
            Runtime credentials remain deployment-managed.
          </p>
        </div>
        <div className="flex items-center gap-3 rounded-xl border border-white/[0.06] bg-white/[0.03] px-4 py-3">
          <CheckCircle2 className="h-5 w-5 text-green-400" />
          <div>
            <div className="text-sm font-semibold text-white">
              {enabledCount} enabled
            </div>
            <div className="text-[10px] text-white/35">
              of {services.length} services
            </div>
          </div>
        </div>
      </motion.div>

      <div className="flex flex-wrap gap-2">
        {categories.map((item) => (
          <button
            key={item}
            onClick={() => setCategory(item)}
            className={`rounded-xl px-4 py-2 text-xs font-medium transition ${category === item ? "bg-electric-500/15 text-electric-300 border border-electric-500/20" : "glass text-white/45 hover:text-white/75"}`}
          >
            {item}
          </button>
        ))}
      </div>

      <div className="rounded-xl border border-electric-500/20 bg-electric-500/10 px-4 py-3 text-xs text-electric-300">
        {message}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {loading ? (
          <div className="glass-card p-8 text-center text-sm text-white/40 lg:col-span-2 xl:col-span-3">
            Loading live owner services…
          </div>
        ) : visible.length === 0 ? (
          <div className="glass-card p-8 text-center text-sm text-white/40 lg:col-span-2 xl:col-span-3">
            No services match this category.
          </div>
        ) : (
          visible.map((service, index) => {
            const Icon = iconFor(service);
            const coreService =
              service.protected ||
              ["postgres", "redis", "vault"].includes(service.id);
            return (
              <motion.div
                key={service.id}
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.03 }}
                className="glass-card p-5"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-start gap-3">
                    <div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5">
                      <Icon className="h-5 w-5 text-electric-300" />
                    </div>
                    <div>
                      <h2 className="text-sm font-semibold text-white">
                        {service.name}
                      </h2>
                      <p className="text-[10px] uppercase tracking-wider text-white/30">
                        {service.category}
                      </p>
                    </div>
                  </div>
                  <button
                    disabled={busy || coreService}
                    onClick={() => toggleService(service)}
                    aria-label={`Toggle ${service.name}`}
                    className="rounded-lg p-1.5 hover:bg-white/[0.05] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {service.enabled ? (
                      <ToggleRight className="h-7 w-7 text-green-400" />
                    ) : (
                      <ToggleLeft className="h-7 w-7 text-white/25" />
                    )}
                  </button>
                </div>
                <p className="mt-4 text-xs leading-relaxed text-white/40">
                  {service.description}
                </p>
                <div className="mt-4 flex items-center justify-between border-t border-white/[0.05] pt-3 text-[10px]">
                  <span className="text-white/30">{service.scope}</span>
                  <span
                    className={
                      service.enabled ? "text-green-400" : "text-orange-400"
                    }
                  >
                    {coreService
                      ? "Core service"
                      : service.enabled
                        ? "Allowed by owner"
                        : "Blocked by owner"}
                  </span>
                </div>
              </motion.div>
            );
          })
        )}
      </div>
    </div>
  );
}
