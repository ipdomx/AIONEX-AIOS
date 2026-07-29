"use client";

import Link from "next/link";
import {
  CheckCircle2,
  ClipboardCheck,
  ExternalLink,
  ShieldCheck,
} from "lucide-react";

import {
  ownerNavigationGroups,
  ownerNavigationItems,
  ownerRootNavigationItem,
} from "@/config/owner-navigation";

export default function OwnerCompletionPage() {
  const OwnerIcon = ownerRootNavigationItem.icon;

  return (
    <div className="space-y-6">
      <header className="glass-card p-6">
        <div className="flex items-center gap-3">
          <ShieldCheck className="h-7 w-7 text-green-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">
              Owner Dashboard Inventory
            </h1>
            <p className="mt-1 text-sm text-white/45">
              {ownerNavigationItems.length} owner pages registered across{" "}
              {ownerNavigationGroups.length} navigation groups.
            </p>
          </div>
        </div>
      </header>

      <section className="space-y-3">
        <div className="flex items-center gap-2 px-1">
          <OwnerIcon className="h-5 w-5 text-electric-300" />
          <h2 className="text-sm font-semibold text-white">Owner Center</h2>
          <span className="text-xs text-white/30">1 page</span>
        </div>
        <Link
          href={ownerRootNavigationItem.href}
          className="glass-card flex items-center gap-3 p-4 transition hover:bg-white/[0.05]"
        >
          <CheckCircle2 className="h-5 w-5 flex-shrink-0 text-green-400" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-white/75">
              {ownerRootNavigationItem.label}
            </div>
            <div className="mt-1 truncate text-[11px] text-white/30">
              {ownerRootNavigationItem.href}
            </div>
          </div>
          <ExternalLink className="h-4 w-4 flex-shrink-0 text-white/25" />
        </Link>
      </section>

      {ownerNavigationGroups.map((group) => {
        const GroupIcon = group.icon;
        return (
          <section key={group.id} className="space-y-3">
            <div className="flex items-center gap-2 px-1">
              <GroupIcon className="h-5 w-5 text-electric-300" />
              <h2 className="text-sm font-semibold text-white">
                {group.label}
              </h2>
              <span className="text-xs text-white/30">
                {group.items.length} pages
              </span>
            </div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {group.items.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="glass-card flex items-center gap-3 p-4 transition hover:bg-white/[0.05]"
                >
                  <CheckCircle2 className="h-5 w-5 flex-shrink-0 text-green-400" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-white/75">
                      {item.label}
                    </div>
                    <div className="mt-1 truncate text-[11px] text-white/30">
                      {item.href}
                    </div>
                  </div>
                  <ExternalLink className="h-4 w-4 flex-shrink-0 text-white/25" />
                </Link>
              ))}
            </div>
          </section>
        );
      })}

      <section className="glass-card p-5">
        <div className="flex items-start gap-3">
          <ClipboardCheck className="mt-0.5 h-5 w-5 text-electric-300" />
          <div>
            <h2 className="text-sm font-semibold text-white">
              Navigation contract
            </h2>
            <p className="mt-2 text-xs leading-relaxed text-white/45">
              This inventory and the Sidebar use the same route registry, so a
              built Owner page cannot silently drift out of navigation coverage.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
