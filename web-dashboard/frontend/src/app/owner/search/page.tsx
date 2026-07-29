"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { FileText, Search } from "lucide-react";
import Link from "next/link";

import {
  ownerNavigationItems,
  ownerNavigationSections,
} from "@/config/owner-navigation";
import { useOwnerResource } from "@/hooks/use-owner-resource";

type SearchableOwnerEntity = {
  id: string;
  name: string;
  type: "project" | "organization" | "service" | "worker";
  status: string;
  owner: string;
};

export default function OwnerGlobalSearchPage() {
  const [query, setQuery] = useState("");
  const [sectionId, setSectionId] = useState("all");
  const {
    items: liveItems,
    loading,
    message,
  } = useOwnerResource<SearchableOwnerEntity>("global-command");

  const results = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const selected =
      sectionId === "all"
        ? ownerNavigationItems
        : (ownerNavigationSections.find((section) => section.id === sectionId)
            ?.items ?? []);

    return selected.filter(
      (item) =>
        !needle ||
        item.label.toLowerCase().includes(needle) ||
        item.description.toLowerCase().includes(needle) ||
        item.href.toLowerCase().includes(needle),
    );
  }, [query, sectionId]);
  const liveResults = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return liveItems.slice(0, 20);
    return liveItems.filter((item) =>
      `${item.name} ${item.type} ${item.status} ${item.owner}`
        .toLowerCase()
        .includes(needle),
    );
  }, [liveItems, query]);

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300">
          <Search className="h-3.5 w-3.5" />
          Owner Navigation Search
        </div>
        <h1 className="text-3xl font-bold tracking-tight text-white">
          Find an Owner Module
        </h1>
        <p className="mt-2 text-sm text-white/45">
          Search registered Owner pages and live platform records from the
          protected control plane.
        </p>
      </motion.div>

      <div className="glass-card p-5">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
          <label className="relative flex-1">
            <span className="sr-only">Search Owner pages</span>
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search names, descriptions, or routes…"
              className="glass-input w-full rounded-xl py-3 pl-10 pr-4 text-sm text-white outline-none"
            />
          </label>
          <select
            value={sectionId}
            onChange={(event) => setSectionId(event.target.value)}
            className="glass-input rounded-xl px-4 py-3 text-sm text-white outline-none"
          >
            <option value="all" className="bg-space-800">
              All Owner groups
            </option>
            {ownerNavigationSections.map((section) => (
              <option
                key={section.id}
                value={section.id}
                className="bg-space-800"
              >
                {section.label}
              </option>
            ))}
          </select>
        </div>
        <p className="mt-3 text-xs text-electric-300">
          {results.length} reachable Owner page{results.length === 1 ? "" : "s"}
          {" · "}
          {loading
            ? "loading live records"
            : `${liveResults.length} live records`}
        </p>
        {!loading && (
          <p className="mt-1 text-[11px] text-white/35">{message}</p>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {results.map((item, index) => {
          const Icon = item.icon;
          return (
            <motion.div
              key={item.id}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.02 }}
            >
              <Link
                href={item.href}
                className="glass-card block h-full p-5 transition hover:bg-white/[0.05]"
              >
                <div className="flex items-start gap-3">
                  <span className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5">
                    <Icon className="h-5 w-5 text-electric-300" />
                  </span>
                  <span>
                    <span className="block text-sm font-semibold text-white">
                      {item.label}
                    </span>
                    <span className="mt-1 block text-xs leading-relaxed text-white/40">
                      {item.description}
                    </span>
                    <span className="mt-2 block text-[11px] text-white/30">
                      {item.href}
                    </span>
                  </span>
                </div>
              </Link>
            </motion.div>
          );
        })}
      </div>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-white">Live records</h2>
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {liveResults.map((item) => {
            const href =
              item.type === "project"
                ? "/owner/projects"
                : item.type === "organization"
                  ? "/owner/organizations"
                  : "/owner/services";
            return (
              <Link
                key={`${item.type}-${item.id}`}
                href={href}
                className="glass-card p-4 transition hover:bg-white/[0.05]"
              >
                <div className="text-sm font-semibold text-white">
                  {item.name}
                </div>
                <div className="mt-1 text-xs text-white/40">
                  {item.type} · {item.status} · {item.owner}
                </div>
              </Link>
            );
          })}
        </div>
      </section>

      {results.length === 0 && (
        <div className="glass-card p-8 text-center text-sm text-white/40">
          <FileText className="mx-auto mb-3 h-6 w-6" />
          No matching Owner page.
        </div>
      )}
    </div>
  );
}
