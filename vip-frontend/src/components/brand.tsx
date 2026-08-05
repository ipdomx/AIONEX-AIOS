/* eslint-disable @next/next/no-img-element */
"use client";

import Link from "next/link";
import { usePortalExperience } from "@/components/portal/portal-experience-provider";

export function Brand({ locale, compact = false }: { locale: string; compact?: boolean }) {
  const { configuration, text } = usePortalExperience();
  const branding = configuration?.branding;
  const size = compact
    ? Math.max(28, (configuration?.theme.logo_size_px || 42) - 6)
    : configuration?.theme.logo_size_px || 42;
  const siteName = branding?.site_name || "AIONEX AIOS";
  return (
    <Link href={`/${locale}`} className="brand-lockup" aria-label={siteName}>
      {/* Dynamic owner assets may be served by the API, so next/image is intentionally not used. */}
      <img
        src={branding?.logo_url || "/brand/aionex-mark.svg"}
        alt={text(branding?.logo_alt, siteName)}
        width={size}
        height={size}
        className="shrink-0 object-contain"
      />
      <span className="brand-words">
        <strong>{branding?.short_name || "AIONEX"}</strong>
        <span>{branding?.wordmark_suffix || "AIOS"}</span>
      </span>
    </Link>
  );
}
