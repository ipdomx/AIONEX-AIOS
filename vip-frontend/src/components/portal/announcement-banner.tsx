"use client";

import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { usePortalExperience } from "@/components/portal/portal-experience-provider";

export function AnnouncementBanner() {
  const { configuration, publicationVersion, text, href } = usePortalExperience();
  const announcement = configuration?.announcement;
  const [dismissed, setDismissed] = useState(false);
  const key = `aionex.portal.announcement.${publicationVersion || "fallback"}`;
  useEffect(() => {
    setDismissed(window.sessionStorage.getItem(key) === "dismissed");
  }, [key]);
  if (!announcement?.enabled || dismissed) return null;
  const severityClass = {
    info: "border-white/10 bg-obsidian-700 text-zinc-200",
    success: "border-emerald-300/20 bg-emerald-400/10 text-emerald-100",
    warning: "border-amber-300/20 bg-amber-400/10 text-amber-100",
    critical: "border-rose-300/20 bg-rose-500/10 text-rose-100",
  }[announcement.severity];
  return (
    <div className={`border-b px-4 py-2.5 text-center text-xs ${severityClass}`}>
      <span>{text(announcement.message)}</span>
      {announcement.link_url && text(announcement.link_label) && (
        <a href={href(announcement.link_url)} className="ms-2 font-bold underline underline-offset-4">{text(announcement.link_label)}</a>
      )}
      {announcement.dismissible && (
        <button
          type="button"
          className="ms-3 inline-flex align-middle"
          aria-label="Dismiss"
          onClick={() => {
            window.sessionStorage.setItem(key, "dismissed");
            setDismissed(true);
          }}
        ><X className="h-3.5 w-3.5" /></button>
      )}
    </div>
  );
}
