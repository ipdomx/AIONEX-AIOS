"use client";

import { Facebook, Instagram, Share2 } from "lucide-react";

import { ApiError } from "@/lib/api";
import type { SocialPostStatus, SocialTargetStatus } from "@/types";

// Validation and result codes with a translation under socialPublishing.issues.
// Anything else is shown with a generic sentence plus the raw code.
export const ISSUE_CODES = new Set([
  "instagram-caption-too-long",
  "instagram-too-many-hashtags",
  "instagram-too-many-mentions",
  "instagram-requires-media",
  "instagram-image-must-be-jpeg",
  "instagram-image-too-large",
  "instagram-aspect-ratio-out-of-range",
  "instagram-image-upscaled",
  "instagram-image-downscaled",
  "instagram-carousel-needs-2-to-10-items",
  "instagram-video-must-be-mp4-or-mov",
  "instagram-video-too-large",
  "instagram-video-too-short",
  "instagram-video-too-long",
  "instagram-reel-not-9-16",
  "instagram-links-not-clickable",
  "image-dimensions-unknown",
  "video-duration-unknown",
  "image-post-needs-one-image",
  "video-post-needs-one-video",
  "text-post-needs-text",
  "text-post-has-media",
  "link-invalid",
  "link-post-has-media",
  "facebook-text-too-long",
  "facebook-multi-photo-needs-2-to-10-images",
  "facebook-multi-photo-images-only",
  "facebook-image-type-unsupported",
  "facebook-image-too-large",
  "facebook-video-type-unsupported",
  "facebook-video-too-large",
  "facebook-video-too-long",
  "facebook-reel-posted-as-video",
  "account-reconnect-required",
  "account-disconnected",
  "publish-outcome-unknown",
  "worker-lease-expired",
  "media-not-found",
]);

export function issueKey(code: string | null | undefined): string | null {
  if (!code) return null;
  const base = code.startsWith("validation-failed:") ? code.slice("validation-failed:".length) : code;
  return ISSUE_CODES.has(base) ? base : null;
}

export const POST_STATUS_TONE: Record<SocialPostStatus, string> = {
  draft: "border-white/[0.12] bg-white/[0.04] text-white/70",
  scheduled: "border-sky-400/25 bg-sky-500/10 text-sky-100",
  publishing: "border-amber-400/25 bg-amber-500/10 text-amber-100",
  published: "border-emerald-400/25 bg-emerald-500/10 text-emerald-100",
  partially_failed: "border-amber-400/30 bg-amber-500/15 text-amber-100",
  failed: "border-rose-400/25 bg-rose-500/10 text-rose-100",
  canceled: "border-white/[0.12] bg-white/[0.03] text-white/45",
};

export const TARGET_STATUS_TONE: Record<SocialTargetStatus, string> = {
  pending: "border-sky-400/25 bg-sky-500/10 text-sky-100",
  publishing: "border-amber-400/25 bg-amber-500/10 text-amber-100",
  retry_wait: "border-amber-400/25 bg-amber-500/10 text-amber-100",
  published: "border-emerald-400/25 bg-emerald-500/10 text-emerald-100",
  failed: "border-rose-400/25 bg-rose-500/10 text-rose-100",
  canceled: "border-white/[0.12] bg-white/[0.03] text-white/45",
};

const LIVE_POST_HOSTS = ["facebook.com", "fb.com", "fb.watch", "instagram.com"];

/** Only an https link on a Meta host is ever rendered as a live-post link. */
export function safePermalink(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:") return null;
    const host = url.hostname.toLowerCase();
    return LIVE_POST_HOSTS.some((item) => host === item || host.endsWith(`.${item}`))
      ? url.toString()
      : null;
  } catch {
    return null;
  }
}

export function PlatformGlyph({ provider, className = "h-4 w-4" }: { provider: string; className?: string }) {
  if (provider === "instagram") return <Instagram className={className} aria-hidden="true" />;
  if (provider === "facebook") return <Facebook className={className} aria-hidden="true" />;
  return <Share2 className={className} aria-hidden="true" />;
}

export function formatBytes(value: number): string {
  if (value >= 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  if (value >= 1024) return `${Math.round(value / 1024)} KB`;
  return `${value} B`;
}

export function apiErrorKey(cause: unknown): string {
  if (cause instanceof ApiError) {
    if (cause.code === "DAILY_MESSAGE_LIMIT" || cause.code === "MESSAGE_CREDITS_EXHAUSTED")
      return "aiQuota";
    if (cause.status === 429) return "rateLimited";
    if (cause.status === 413 || cause.code === "media-too-large") return "mediaTooLarge";
    if (cause.status === 415 || cause.code === "media-type-unsupported") return "mediaType";
    if (cause.code === "post-validation-failed") return "validation";
    if (cause.code === "scheduled-at-in-past") return "scheduleInPast";
    if (cause.code === "scheduled-at-too-far") return "scheduleTooFar";
    if (cause.code === "target-account-not-found") return "accountUnavailable";
    if (cause.code === "ai-assistant-unavailable") return "aiUnavailable";
    if (cause.code && cause.code.startsWith("ai-")) return "aiFailed";
    if (cause.status === 409) return "conflict";
  }
  return "generic";
}
