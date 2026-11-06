"use client";

import { useState, type MouseEvent } from "react";

import { ApiError } from "@/lib/api";

type Translate = (key: string, values?: Record<string, string | number>) => string;

// Meta "offset 1" currencies: budgets are already whole units.
const ZERO_DECIMAL = new Set(["CLP", "COP", "CRC", "HUF", "ISK", "IDR", "JPY", "KRW", "PYG", "TWD", "VND"]);

export function currencyOffset(currency: string): number {
  return ZERO_DECIMAL.has(currency.toUpperCase()) ? 1 : 100;
}

export function toMinor(value: string, currency: string): number {
  const parsed = Number(value.trim());
  if (!Number.isFinite(parsed) || parsed <= 0) return 0;
  return Math.round(parsed * currencyOffset(currency));
}

export function money(amount: number | null | undefined, currency: string): string {
  if (amount == null || !Number.isFinite(amount)) return "—";
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(amount);
  } catch {
    return `${currency} ${amount.toFixed(2)}`;
  }
}

export function moneyMinor(amount: number | null | undefined, currency: string): string {
  if (amount == null) return "—";
  return money(amount / currencyOffset(currency), currency);
}

export function compact(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(value);
}

const ERROR_KEYS: Record<string, string> = {
  ADS_PLAN_REQUIRED: "planRequired",
  ADS_DISABLED: "planRequired",
  "ads-daily-cap-exceeded": "dailyCap",
  "ads-lifetime-cap-exceeded": "lifetimeCap",
  "ads-daily-cap-reached": "capReached",
  "ads-lifetime-cap-reached": "capReached",
  "ads-spend-cap-not-configured": "capReached",
  "activation-confirmation-mismatch": "confirmation",
  "ads-activation-disabled-by-owner": "activationDisabled",
  "ads-active-campaign-limit": "activeLimit",
  "ads-management-permission-not-granted": "managePermission",
  "ads-permission-not-granted": "readPermission",
  "ad-account-limit-reached": "accountLimit",
  "ads-insights-throttled": "throttled",
  "ads-no-metrics-yet": "noMetrics",
  "ads-recommendation-daily-limit": "aiLimit",
  "ai-assistant-unavailable": "aiUnavailable",
  DAILY_MESSAGE_LIMIT: "quota",
  "provider-not-configured": "notConfigured",
  "objective-needs-conversion-setup": "objectiveSetup",
};

export function adsErrorText(t: Translate, cause: unknown): string {
  const code = cause instanceof ApiError ? cause.code : null;
  const key = code ? ERROR_KEYS[code] : undefined;
  if (key) return t(`errors.${key}`);
  if (code && code.startsWith("meta-ads-") && code.includes("throttled")) return t("errors.throttled");
  return t("errors.generic");
}

export function DeltaBadge({ change }: { change: number | null }) {
  if (change == null) return <span className="text-[11px] text-white/30">—</span>;
  const up = change >= 0;
  return (
    <span className={`text-[11px] font-medium ${up ? "text-emerald-300/80" : "text-rose-300/80"}`}>
      {up ? "▲" : "▼"} {compact(Math.abs(change), 1)}%
    </span>
  );
}

export interface SeriesPoint {
  label: string;
  value: number | null;
}

/** One-series SVG line chart with a crosshair tooltip; no dependency. */
export function LineChart({
  points,
  title,
  format,
}: {
  points: SeriesPoint[];
  title: string;
  format: (value: number | null) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 600;
  const height = 180;
  const pad = { top: 12, right: 12, bottom: 24, left: 12 };
  const values = points.map((point) => point.value ?? 0);
  const max = Math.max(1e-9, ...values);
  const step = points.length > 1 ? (width - pad.left - pad.right) / (points.length - 1) : 0;
  const x = (index: number) => pad.left + index * step;
  const y = (value: number) => pad.top + (height - pad.top - pad.bottom) * (1 - value / max);
  const path = points
    .map((point, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(1)},${y(point.value ?? 0).toFixed(1)}`)
    .join(" ");

  function onMove(event: MouseEvent<SVGSVGElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    if (!box.width || points.length === 0) return;
    const relative = ((event.clientX - box.left) / box.width) * width;
    const index = step ? Math.round((relative - pad.left) / step) : 0;
    setHover(Math.max(0, Math.min(points.length - 1, index)));
  }

  const active = hover != null ? points[hover] : null;
  return (
    <figure className="relative">
      <figcaption className="mb-2 text-xs font-semibold text-white/70">{title}</figcaption>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-44 w-full"
        role="img"
        aria-label={title}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        {[0.25, 0.5, 0.75, 1].map((fraction) => (
          <line
            key={fraction}
            x1={pad.left}
            x2={width - pad.right}
            y1={y(max * fraction)}
            y2={y(max * fraction)}
            stroke="rgba(255,255,255,0.06)"
            strokeWidth={1}
          />
        ))}
        <line x1={pad.left} x2={width - pad.right} y1={y(0)} y2={y(0)} stroke="rgba(255,255,255,0.18)" strokeWidth={1} />
        {points.length > 0 && <path d={path} fill="none" stroke="#FF2D3F" strokeWidth={2} strokeLinejoin="round" />}
        {active && hover != null && (
          <>
            <line x1={x(hover)} x2={x(hover)} y1={pad.top} y2={y(0)} stroke="rgba(255,255,255,0.25)" strokeWidth={1} />
            <circle cx={x(hover)} cy={y(active.value ?? 0)} r={5} fill="#FF2D3F" stroke="#0B0B0D" strokeWidth={2} />
          </>
        )}
        {points.length > 0 && (
          <>
            <text x={pad.left} y={height - 6} fill="rgba(255,255,255,0.4)" fontSize={11}>
              {points[0].label}
            </text>
            <text x={width - pad.right} y={height - 6} fill="rgba(255,255,255,0.4)" fontSize={11} textAnchor="end">
              {points[points.length - 1].label}
            </text>
          </>
        )}
      </svg>
      {active && (
        <div className="pointer-events-none absolute right-2 top-6 rounded-lg border border-white/10 bg-obsidian-800 px-3 py-2 text-xs text-white shadow-lg">
          <div className="text-white/50">{active.label}</div>
          <div className="font-semibold">{format(active.value)}</div>
        </div>
      )}
    </figure>
  );
}

/** Horizontal bars for one breakdown; every bar is labelled, so identity is never colour-only. */
export function BarList({
  items,
  format,
}: {
  items: { label: string; value: number }[];
  format: (value: number) => string;
}) {
  const max = Math.max(1e-9, ...items.map((item) => item.value));
  return (
    <ul className="space-y-2">
      {items.map((item) => (
        <li key={item.label} title={`${item.label}: ${format(item.value)}`}>
          <div className="flex items-center justify-between gap-3 text-xs">
            <span className="truncate text-white/70">{item.label}</span>
            <span className="shrink-0 font-medium text-white">{format(item.value)}</span>
          </div>
          <div className="mt-1 h-2 rounded-full bg-white/[0.05]">
            <div className="h-2 rounded-full bg-crimson-400" style={{ width: `${Math.max(2, (item.value / max) * 100)}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}
