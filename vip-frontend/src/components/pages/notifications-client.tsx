"use client";

import {
  Bell,
  CheckCheck,
  CircleAlert,
  LoaderCircle,
  Mail,
  MessageCircle,
  RefreshCw,
  Save,
  Send,
  Smartphone,
  Trash2,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { StatusMessage } from "@/components/ui/status-message";
import { useAuth } from "@/hooks/use-auth";
import {
  deleteCommunicationEndpoint,
  getCommunicationChannels,
  getNotificationPreferences,
  listCommunicationEndpoints,
  listNotifications,
  markAllNotificationsRead,
  registerCommunicationEndpoint,
  updateNotification,
  updateNotificationPreference,
} from "@/lib/api";
import type {
  CommunicationChannelReadiness,
  CommunicationEndpoint,
  NotificationChannelId,
  NotificationPreference,
  PortalNotification,
} from "@/types";

const channelIcons = {
  in_app: Bell,
  email: Mail,
  push: Smartphone,
  telegram: Send,
  whatsapp: MessageCircle,
} as const;

const externalChannels: Array<CommunicationEndpoint["channel"]> = [
  "email",
  "push",
  "telegram",
  "whatsapp",
];

function formatDate(value: string, locale: string): string {
  try {
    return new Intl.DateTimeFormat(locale, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

export function NotificationsClient() {
  const t = useTranslations("notifications");
  const locale = useLocale();
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();
  const [notifications, setNotifications] = useState<PortalNotification[]>([]);
  const [channels, setChannels] = useState<CommunicationChannelReadiness[]>([]);
  const [endpoints, setEndpoints] = useState<CommunicationEndpoint[]>([]);
  const [preference, setPreference] = useState<NotificationPreference | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showUnread, setShowUnread] = useState(false);
  const [endpointChannel, setEndpointChannel] =
    useState<CommunicationEndpoint["channel"]>("email");
  const [endpointAddress, setEndpointAddress] = useState("");
  const [endpointLabel, setEndpointLabel] = useState("");

  useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace(`/${locale}/login`);
  }, [isAuthenticated, isLoading, locale, router]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [notificationRows, readiness, endpointRows, preferences] =
        await Promise.all([
          listNotifications({ unreadOnly: showUnread }),
          getCommunicationChannels(),
          listCommunicationEndpoints(),
          getNotificationPreferences(),
        ]);
      setNotifications(notificationRows);
      setChannels(readiness);
      setEndpoints(endpointRows);
      setPreference(
        preferences.find((item) => item.category === "*") ||
          preferences[0] ||
          null,
      );
    } catch {
      setError(t("loadError"));
    } finally {
      setLoading(false);
    }
  }, [showUnread, t]);

  useEffect(() => {
    if (isAuthenticated) void load();
  }, [isAuthenticated, load]);

  const unreadCount = useMemo(
    () => notifications.filter((item) => !item.read).length,
    [notifications],
  );

  async function markAllRead() {
    setSaving(true);
    setError("");
    try {
      const result = await markAllNotificationsRead();
      setNotifications((current) =>
        current.map((item) => ({ ...item, read: true })),
      );
      setNotice(t("markedAll", { count: result.updated }));
    } catch {
      setError(t("saveError"));
    } finally {
      setSaving(false);
    }
  }

  async function toggleRead(item: PortalNotification) {
    setSaving(true);
    setError("");
    try {
      const updated = await updateNotification(item.id, { read: !item.read });
      setNotifications((current) =>
        current.map((row) =>
          row.id === item.id ? { ...row, read: updated.read } : row,
        ),
      );
    } catch {
      setError(t("saveError"));
    } finally {
      setSaving(false);
    }
  }

  async function archive(item: PortalNotification) {
    setSaving(true);
    setError("");
    try {
      await updateNotification(item.id, { archived: true });
      setNotifications((current) =>
        current.filter((row) => row.id !== item.id),
      );
      setNotice(t("archived"));
    } catch {
      setError(t("saveError"));
    } finally {
      setSaving(false);
    }
  }

  function togglePreferenceChannel(channel: NotificationChannelId) {
    if (!preference) return;
    if (channel === "in_app") return;
    const selected = preference.channels.includes(channel);
    setPreference({
      ...preference,
      channels: selected
        ? preference.channels.filter((item) => item !== channel)
        : [...preference.channels, channel],
    });
  }

  async function savePreference() {
    if (!preference) return;
    setSaving(true);
    setError("");
    try {
      const updated = await updateNotificationPreference({
        category: preference.category,
        enabled: preference.enabled,
        channels: preference.channels.includes("in_app")
          ? preference.channels
          : ["in_app", ...preference.channels],
        minimum_severity: preference.minimum_severity,
        quiet_hours_start: preference.quiet_hours_start,
        quiet_hours_end: preference.quiet_hours_end,
        timezone: preference.timezone,
        digest_mode: preference.digest_mode,
      });
      setPreference(updated);
      setNotice(t("preferencesSaved"));
    } catch {
      setError(t("saveError"));
    } finally {
      setSaving(false);
    }
  }

  async function addEndpoint() {
    if (!endpointAddress.trim()) return;
    setSaving(true);
    setError("");
    try {
      const endpoint = await registerCommunicationEndpoint({
        channel: endpointChannel,
        address: endpointAddress.trim(),
        label: endpointLabel.trim() || t("primaryEndpoint"),
      });
      setEndpoints((current) => [
        endpoint,
        ...current.filter((item) => item.id !== endpoint.id),
      ]);
      setEndpointAddress("");
      setEndpointLabel("");
      setNotice(
        endpoint.verified ? t("endpointAdded") : t("endpointPending"),
      );
    } catch {
      setError(t("endpointError"));
    } finally {
      setSaving(false);
    }
  }

  async function removeEndpoint(endpoint: CommunicationEndpoint) {
    setSaving(true);
    setError("");
    try {
      await deleteCommunicationEndpoint(endpoint.id);
      setEndpoints((current) =>
        current.filter((item) => item.id !== endpoint.id),
      );
      setNotice(t("endpointRemoved"));
    } catch {
      setError(t("saveError"));
    } finally {
      setSaving(false);
    }
  }

  if (isLoading || (!isAuthenticated && !error)) {
    return (
      <section className="section-pad">
        <div className="page-shell flex min-h-[45vh] items-center justify-center">
          <LoaderCircle
            className="h-8 w-8 animate-spin text-electric-200"
            aria-label={t("loading")}
          />
        </div>
      </section>
    );
  }

  return (
    <section className="section-pad">
      <div className="page-shell">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <span className="eyebrow">{t("eyebrow")}</span>
            <h1 className="section-title mt-6">{t("title")}</h1>
            <p className="section-copy mt-4">{t("description")}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              onClick={() => void markAllRead()}
              disabled={saving || unreadCount === 0}
            >
              <CheckCheck className="h-4 w-4" aria-hidden="true" />
              {t("markAllRead")}
            </Button>
            <Button
              variant="secondary"
              onClick={() => void load()}
              disabled={loading}
            >
              <RefreshCw
                className={`h-4 w-4 ${loading ? "animate-spin" : ""}`}
                aria-hidden="true"
              />
              {t("refresh")}
            </Button>
          </div>
        </div>

        {error && (
          <StatusMessage tone="error" className="mt-6">
            {error}
          </StatusMessage>
        )}
        {notice && !error && (
          <StatusMessage tone="success" className="mt-6">
            {notice}
          </StatusMessage>
        )}

        <div className="mt-8 grid gap-6 xl:grid-cols-[1.35fr_.65fr]">
          <Card>
            <CardContent>
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <h2 className="text-xl font-semibold">{t("inbox")}</h2>
                  <p className="mt-2 text-sm text-white/40">
                    {t("unreadCount", { count: unreadCount })}
                  </p>
                </div>
                <label className="inline-flex items-center gap-2 text-sm text-white/60">
                  <input
                    type="checkbox"
                    checked={showUnread}
                    onChange={(event) => setShowUnread(event.target.checked)}
                    className="h-4 w-4 rounded border-white/20 bg-black/30"
                  />
                  {t("unreadOnly")}
                </label>
              </div>

              <div className="mt-6 space-y-3">
                {loading ? (
                  <div className="flex min-h-32 items-center justify-center text-white/45">
                    <LoaderCircle className="me-2 h-5 w-5 animate-spin" />
                    {t("loading")}
                  </div>
                ) : notifications.length ? (
                  notifications.map((item) => (
                    <article
                      key={item.id}
                      className={`rounded-2xl border p-5 ${
                        item.read
                          ? "border-white/[0.07] bg-black/10"
                          : "border-electric-300/20 bg-electric-500/[0.06]"
                      }`}
                    >
                      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="rounded-full border border-white/10 px-2.5 py-1 text-[11px] uppercase tracking-wider text-white/50">
                              {item.category}
                            </span>
                            <span className="text-xs text-white/35">
                              {formatDate(item.created_at, locale)}
                            </span>
                          </div>
                          <h3 className="mt-3 font-semibold text-white">
                            {item.title}
                          </h3>
                          <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-white/55">
                            {item.message}
                          </p>
                          <div className="mt-4 flex flex-wrap gap-2">
                            {item.deliveries.map((delivery) => (
                              <span
                                key={delivery.id}
                                className="rounded-lg border border-white/[0.07] bg-black/20 px-2.5 py-1 text-[11px] text-white/45"
                              >
                                {delivery.channel}: {delivery.status}
                              </span>
                            ))}
                          </div>
                        </div>
                        <div className="flex shrink-0 gap-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => void toggleRead(item)}
                            disabled={saving}
                          >
                            {item.read ? t("markUnread") : t("markRead")}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => void archive(item)}
                            disabled={saving}
                            aria-label={t("archive")}
                          >
                            <Trash2 className="h-4 w-4" aria-hidden="true" />
                          </Button>
                        </div>
                      </div>
                    </article>
                  ))
                ) : (
                  <div className="rounded-2xl border border-dashed border-white/10 px-6 py-12 text-center">
                    <Bell className="mx-auto h-8 w-8 text-white/25" />
                    <h3 className="mt-4 font-semibold">{t("empty")}</h3>
                    <p className="mt-2 text-sm text-white/40">{t("emptyCopy")}</p>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          <div className="space-y-6">
            <Card>
              <CardContent>
                <h2 className="text-xl font-semibold">{t("channelReadiness")}</h2>
                <div className="mt-5 space-y-3">
                  {channels.map((channel) => {
                    const Icon = channelIcons[channel.id];
                    return (
                      <div
                        key={channel.id}
                        className="flex items-start justify-between gap-4 rounded-xl border border-white/[0.07] bg-black/15 p-4"
                      >
                        <div className="flex min-w-0 gap-3">
                          <Icon className="mt-0.5 h-5 w-5 shrink-0 text-electric-200" />
                          <div className="min-w-0">
                            <p className="font-medium text-white">{channel.name}</p>
                            <p className="mt-1 text-xs leading-5 text-white/35">
                              {channel.reason}
                            </p>
                          </div>
                        </div>
                        <span
                          className={`rounded-full px-2.5 py-1 text-[11px] ${
                            channel.ready
                              ? "bg-emerald-400/10 text-emerald-200"
                              : "bg-amber-400/10 text-amber-200"
                          }`}
                        >
                          {channel.ready ? t("ready") : t("notConfigured")}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>

            {preference && (
              <Card>
                <CardContent>
                  <h2 className="text-xl font-semibold">{t("preferences")}</h2>
                  <div className="mt-5 space-y-3">
                    {channels.map((channel) => (
                      <label
                        key={channel.id}
                        className="flex items-center justify-between gap-4 rounded-xl border border-white/[0.07] px-4 py-3 text-sm"
                      >
                        <span>{channel.name}</span>
                        <input
                          type="checkbox"
                          checked={preference.channels.includes(channel.id)}
                          disabled={channel.id === "in_app"}
                          onChange={() => togglePreferenceChannel(channel.id)}
                          className="h-4 w-4 rounded border-white/20 bg-black/30"
                        />
                      </label>
                    ))}
                    <label className="block text-sm text-white/60">
                      {t("minimumSeverity")}
                      <select
                        value={preference.minimum_severity}
                        onChange={(event) =>
                          setPreference({
                            ...preference,
                            minimum_severity: event.target
                              .value as NotificationPreference["minimum_severity"],
                          })
                        }
                        className="mt-2 h-11 w-full rounded-xl border border-white/10 bg-ink-950 px-3 text-white"
                      >
                        <option value="info">{t("severity.info")}</option>
                        <option value="warning">{t("severity.warning")}</option>
                        <option value="critical">{t("severity.critical")}</option>
                      </select>
                    </label>
                    <Button
                      className="w-full"
                      onClick={() => void savePreference()}
                      disabled={saving}
                    >
                      <Save className="h-4 w-4" aria-hidden="true" />
                      {t("savePreferences")}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        </div>

        <Card className="mt-6">
          <CardContent>
            <div className="grid gap-6 lg:grid-cols-[.7fr_1.3fr]">
              <div>
                <h2 className="text-xl font-semibold">{t("endpoints")}</h2>
                <p className="mt-2 text-sm leading-6 text-white/40">
                  {t("endpointsCopy")}
                </p>
                <div className="mt-5 grid gap-3">
                  <select
                    value={endpointChannel}
                    onChange={(event) =>
                      setEndpointChannel(
                        event.target.value as CommunicationEndpoint["channel"],
                      )
                    }
                    className="h-11 rounded-xl border border-white/10 bg-ink-950 px-3 text-white"
                  >
                    {externalChannels.map((channel) => (
                      <option key={channel} value={channel}>
                        {t(`channel.${channel}`)}
                      </option>
                    ))}
                  </select>
                  <input
                    value={endpointAddress}
                    onChange={(event) => setEndpointAddress(event.target.value)}
                    placeholder={t("endpointAddress")}
                    className="h-11 rounded-xl border border-white/10 bg-black/20 px-3 text-white placeholder:text-white/25"
                  />
                  <input
                    value={endpointLabel}
                    onChange={(event) => setEndpointLabel(event.target.value)}
                    placeholder={t("endpointLabel")}
                    className="h-11 rounded-xl border border-white/10 bg-black/20 px-3 text-white placeholder:text-white/25"
                  />
                  <Button
                    onClick={() => void addEndpoint()}
                    disabled={saving || !endpointAddress.trim()}
                  >
                    <Send className="h-4 w-4" aria-hidden="true" />
                    {t("addEndpoint")}
                  </Button>
                </div>
              </div>
              <div className="space-y-3">
                {endpoints.length ? (
                  endpoints.map((endpoint) => (
                    <div
                      key={endpoint.id}
                      className="flex items-center justify-between gap-4 rounded-xl border border-white/[0.07] bg-black/15 p-4"
                    >
                      <div>
                        <p className="font-medium text-white">{endpoint.label}</p>
                        <p className="mt-1 text-xs text-white/40">
                          {t(`channel.${endpoint.channel}`)} · {endpoint.masked_address}
                        </p>
                        <p className="mt-1 text-[11px] text-white/30">
                          {endpoint.verified
                            ? t("verified")
                            : t("verificationPending")}
                        </p>
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => void removeEndpoint(endpoint)}
                        disabled={saving}
                        aria-label={t("removeEndpoint")}
                      >
                        <Trash2 className="h-4 w-4" aria-hidden="true" />
                      </Button>
                    </div>
                  ))
                ) : (
                  <div className="flex min-h-40 items-center justify-center rounded-2xl border border-dashed border-white/10 px-6 text-center text-sm text-white/40">
                    <CircleAlert className="me-2 h-5 w-5" />
                    {t("noEndpoints")}
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
