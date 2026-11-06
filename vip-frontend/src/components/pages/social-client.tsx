"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import {
  CheckCircle2,
  Facebook,
  HeartPulse,
  Instagram,
  Link2,
  LoaderCircle,
  Lock,
  RefreshCw,
  Share2,
  ShieldAlert,
  Unlink,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { StatusMessage } from "@/components/ui/status-message";
import { useAuth } from "@/hooks/use-auth";
import {
  ApiError,
  checkSocialAccountHealth,
  connectSocialAssets,
  disconnectSocialAccount,
  disconnectSocialConnection,
  listSocialAccounts,
  listSocialConnectionAssets,
  listSocialConnections,
  listSocialProviders,
  startSocialConnect,
} from "@/lib/api";
import type {
  SocialAccount,
  SocialAsset,
  SocialConnection,
  SocialProvider,
} from "@/types";

// Result codes the OAuth callback appends to /<locale>/social/. Anything not
// listed falls back to a generic message; nothing here invents a success.
const CALLBACK_MESSAGE_KEYS: Record<string, string> = {
  connected: "connected",
  "oauth-access-denied": "accessDenied",
  "oauth-state-expired": "stateExpired",
  "oauth-state-binding-mismatch": "stateMismatch",
  "oauth-state-invalid": "stateInvalid",
  "oauth-state-replayed": "stateInvalid",
  "oauth-state-missing": "stateInvalid",
  "oauth-token-invalid": "tokenInvalid",
  "oauth-user-inactive": "generic",
  "provider-not-configured": "notConfigured",
};

const HEALTH_KEYS = new Set([
  "healthy",
  "expiring",
  "degraded",
  "invalid",
  "expired",
  "error",
  "revoked",
  "unknown",
]);

const HEALTH_TONE: Record<string, string> = {
  healthy: "border-emerald-400/25 bg-emerald-500/10 text-emerald-100",
  expiring: "border-amber-400/25 bg-amber-500/10 text-amber-100",
  degraded: "border-amber-400/25 bg-amber-500/10 text-amber-100",
  invalid: "border-rose-400/25 bg-rose-500/10 text-rose-100",
  expired: "border-rose-400/25 bg-rose-500/10 text-rose-100",
  error: "border-rose-400/25 bg-rose-500/10 text-rose-100",
};

const META_DIALOG_HOST = "www.facebook.com";

type CallbackNotice = { tone: "success" | "error"; key: string } | null;

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const letters = parts.slice(0, 2).map((part) => Array.from(part)[0] || "");
  return letters.join("").toUpperCase() || "?";
}

function ProviderGlyph({ provider }: { provider: string }) {
  if (provider === "instagram") return <Instagram className="h-4 w-4" aria-hidden="true" />;
  if (provider === "facebook" || provider === "meta")
    return <Facebook className="h-4 w-4" aria-hidden="true" />;
  return <Share2 className="h-4 w-4" aria-hidden="true" />;
}

function Monogram({ name, provider }: { name: string; provider: string }) {
  return (
    <span
      className="relative inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-white/[0.1] bg-obsidian-700 text-sm font-semibold text-white"
      aria-hidden="true"
    >
      {initials(name)}
      <span className="absolute -bottom-1 -end-1 inline-flex h-5 w-5 items-center justify-center rounded-full border border-white/[0.12] bg-obsidian-900 text-crimson-200">
        <ProviderGlyph provider={provider} />
      </span>
    </span>
  );
}

export function SocialClient() {
  const t = useTranslations("social");
  const format = useFormatter();
  const locale = useLocale();
  const { isAuthenticated, isLoading } = useAuth();

  const [providers, setProviders] = useState<SocialProvider[] | null>(null);
  const [accounts, setAccounts] = useState<SocialAccount[]>([]);
  const [connections, setConnections] = useState<SocialConnection[]>([]);
  const [loadError, setLoadError] = useState("");
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState<CallbackNotice>(null);
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);

  const [pickerConnection, setPickerConnection] = useState<SocialConnection | null>(null);
  const [assets, setAssets] = useState<SocialAsset[] | null>(null);
  const [assetsError, setAssetsError] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [skippedCount, setSkippedCount] = useState(0);

  const describeError = useCallback(
    (cause: unknown): string => {
      if (cause instanceof ApiError) {
        if (cause.status === 429) return t("errors.rateLimited");
        if (cause.code === "provider-not-configured") return t("errors.notConfigured");
        if (cause.code === "provider-coming-soon") return t("errors.comingSoon");
        if (cause.code && cause.code.startsWith("meta-")) return t("errors.provider");
        if (cause.code === "token-not-available" || cause.code === "connection-revoked")
          return t("errors.reconnect");
      }
      return t("errors.generic");
    },
    [t],
  );

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [providerList, accountList, connectionList] = await Promise.all([
        listSocialProviders(),
        listSocialAccounts(),
        listSocialConnections(),
      ]);
      setProviders(providerList.items);
      setAccounts(accountList.items);
      setConnections(connectionList.items);
      setLoadError("");
    } catch (cause) {
      setLoadError(describeError(cause));
    } finally {
      setLoading(false);
    }
  }, [describeError]);

  const openPicker = useCallback(
    async (connectionId: string) => {
      setAssets(null);
      setAssetsError("");
      setSkippedCount(0);
      try {
        const result = await listSocialConnectionAssets(connectionId);
        setPickerConnection(result.connection);
        setAssets(result.items);
        setSelected(
          new Set(result.items.filter((item) => item.connectable && !item.connected).map((item) => item.asset_id)),
        );
      } catch (cause) {
        setPickerConnection(null);
        setAssetsError(describeError(cause));
      }
    },
    [describeError],
  );

  // Read the callback result once, then drop it from the address bar so a
  // reload never replays a stale message.
  useEffect(() => {
    if (!isAuthenticated) return;
    const params = new URLSearchParams(window.location.search);
    const result = params.get("result");
    if (!result) return;
    const code = params.get("code") || "";
    const connectionId = params.get("connection");
    const key = CALLBACK_MESSAGE_KEYS[code] || (code.startsWith("meta-") ? "providerError" : "generic");
    setNotice({ tone: result === "success" ? "success" : "error", key });
    window.history.replaceState(window.history.state, "", window.location.pathname);
    if (result === "success" && connectionId && /^[A-Za-z0-9-]{1,64}$/.test(connectionId)) {
      void openPicker(connectionId);
    }
  }, [isAuthenticated, openPicker]);

  useEffect(() => {
    if (isAuthenticated) void loadAll();
  }, [isAuthenticated, loadAll]);

  const pendingConnections = useMemo(
    () => connections.filter((item) => item.status === "pending_selection"),
    [connections],
  );

  async function connect(provider: SocialProvider) {
    setActionError("");
    setBusy(`start:${provider.key}`);
    try {
      const { authorize_url: authorizeUrl } = await startSocialConnect(provider.key, locale);
      const target = new URL(authorizeUrl);
      if (target.protocol !== "https:" || target.hostname !== META_DIALOG_HOST) {
        throw new Error("unexpected-authorize-host");
      }
      window.location.assign(target.toString());
    } catch (cause) {
      setActionError(describeError(cause));
      setBusy(null);
    }
  }

  async function saveSelection() {
    if (!pickerConnection || selected.size === 0) return;
    setActionError("");
    setBusy("connect");
    try {
      const result = await connectSocialAssets(pickerConnection.id, Array.from(selected));
      setSkippedCount(result.skipped.length);
      setNotice(
        result.items.length > 0 ? { tone: "success", key: "assetsConnected" } : { tone: "error", key: "nothingConnected" },
      );
      if (result.skipped.length === 0) {
        setPickerConnection(null);
        setAssets(null);
      }
      await loadAll();
    } catch (cause) {
      setActionError(describeError(cause));
    } finally {
      setBusy(null);
    }
  }

  async function cancelConnection(connection: SocialConnection) {
    setActionError("");
    setBusy(`cancel:${connection.id}`);
    try {
      await disconnectSocialConnection(connection.id);
      setPickerConnection(null);
      setAssets(null);
      await loadAll();
    } catch (cause) {
      setActionError(describeError(cause));
    } finally {
      setBusy(null);
    }
  }

  async function checkHealth(account: SocialAccount) {
    setActionError("");
    setBusy(`health:${account.id}`);
    try {
      const updated = await checkSocialAccountHealth(account.id);
      setAccounts((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    } catch (cause) {
      setActionError(describeError(cause));
    } finally {
      setBusy(null);
    }
  }

  async function disconnect(account: SocialAccount) {
    if (confirming !== account.id) {
      setConfirming(account.id);
      return;
    }
    setConfirming(null);
    setActionError("");
    setBusy(`disconnect:${account.id}`);
    try {
      await disconnectSocialAccount(account.id);
      setNotice({ tone: "success", key: "disconnected" });
      await loadAll();
    } catch (cause) {
      setActionError(describeError(cause));
    } finally {
      setBusy(null);
    }
  }

  function toggle(assetId: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(assetId)) next.delete(assetId);
      else next.add(assetId);
      return next;
    });
  }

  function formatDate(value: string | null): string {
    if (!value) return t("accounts.never");
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return t("accounts.never");
    return format.dateTime(date, { dateStyle: "medium", timeStyle: "short" });
  }

  const header = (
    <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
      <div className="max-w-3xl">
        <span className="eyebrow">
          <Share2 className="h-3.5 w-3.5" aria-hidden="true" /> {t("eyebrow")}
        </span>
        <h1 className="section-title mt-6">{t("title")}</h1>
        <p className="section-copy mt-4">{t("description")}</p>
      </div>
      {isAuthenticated && (
        <Button variant="secondary" disabled={loading} onClick={() => void loadAll()}>
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
          {t("refresh")}
        </Button>
      )}
    </div>
  );

  if (isLoading) {
    return (
      <section className="page-shell py-16 text-white">
        <div className="glass-panel flex min-h-52 items-center justify-center rounded-3xl" role="status" aria-label={t("loading")}>
          <LoaderCircle className="h-7 w-7 animate-spin text-crimson-200" aria-hidden="true" />
        </div>
      </section>
    );
  }

  if (!isAuthenticated) {
    return (
      <section className="page-shell py-10 text-white sm:py-14">
        {header}
        <div className="glass-panel mt-8 rounded-3xl p-6 sm:p-8">
          <div className="flex items-start gap-3">
            <Lock className="mt-0.5 h-5 w-5 shrink-0 text-crimson-200" aria-hidden="true" />
            <div>
              <h2 className="text-lg font-semibold">{t("signedOut.title")}</h2>
              <p className="mt-2 text-sm leading-6 text-white/55">{t("signedOut.body")}</p>
              <div className="mt-5 flex flex-wrap gap-2">
                <Link
                  href={`/${locale}/login`}
                  className="portal-primary-button inline-flex h-11 items-center px-5 text-sm font-semibold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
                >
                  {t("signedOut.login")}
                </Link>
                <Link
                  href={`/${locale}/register`}
                  className="portal-secondary-button inline-flex h-11 items-center px-5 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
                >
                  {t("signedOut.register")}
                </Link>
              </div>
            </div>
          </div>
        </div>
      </section>
    );
  }

  const facebookAssets = (assets || []).filter((item) => item.provider === "facebook");
  const instagramAssets = (assets || []).filter((item) => item.provider === "instagram");

  const assetGroup = (title: string, items: SocialAsset[]) => (
    <fieldset className="mt-5">
      <legend className="text-xs font-semibold uppercase tracking-wide text-white/45">{title}</legend>
      {items.length === 0 ? (
        <p className="mt-2 text-sm text-white/45">{t("picker.noneInGroup")}</p>
      ) : (
        <ul className="mt-2 grid gap-2 sm:grid-cols-2">
          {items.map((asset) => {
            const id = `social-asset-${asset.asset_id.replace(/[^A-Za-z0-9_-]/g, "-")}`;
            const disabled = asset.connected || !asset.connectable;
            return (
              <li key={asset.asset_id}>
                <label
                  htmlFor={id}
                  className="flex cursor-pointer items-center gap-3 rounded-2xl border border-white/[0.08] bg-black/20 p-3 transition hover:border-white/20 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60"
                >
                  <input
                    id={id}
                    type="checkbox"
                    className="h-4 w-4 accent-crimson-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
                    checked={asset.connected || selected.has(asset.asset_id)}
                    disabled={disabled}
                    onChange={() => toggle(asset.asset_id)}
                  />
                  <Monogram name={asset.display_name} provider={asset.provider} />
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-semibold">{asset.display_name}</span>
                    <span className="block truncate text-xs text-white/45">
                      {asset.connected
                        ? t("picker.alreadyConnected")
                        : !asset.connectable
                          ? t("picker.notGranted")
                          : asset.handle
                            ? `@${asset.handle}`
                            : t(`kinds.${asset.provider === "instagram" ? "instagram" : "page"}`)}
                    </span>
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
    </fieldset>
  );

  return (
    <section className="page-shell py-10 text-white sm:py-14">
      {header}

      {notice && (
        <StatusMessage tone={notice.tone} className="mt-6">
          {t(`callback.${notice.key}`)}
        </StatusMessage>
      )}
      {actionError && (
        <StatusMessage tone="error" className="mt-4">
          {actionError}
        </StatusMessage>
      )}
      {loadError && (
        <StatusMessage tone="error" className="mt-4">
          {loadError}
        </StatusMessage>
      )}

      <StatusMessage className="mt-6">{t("honesty")}</StatusMessage>

      {/* Providers */}
      <h2 className="mt-10 text-lg font-semibold">{t("providers.title")}</h2>
      {providers === null ? (
        <div className="glass-panel mt-4 flex min-h-32 items-center justify-center rounded-3xl" role="status" aria-label={t("loading")}>
          <LoaderCircle className="h-6 w-6 animate-spin text-crimson-200" aria-hidden="true" />
        </div>
      ) : (
        <ul className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {providers.map((provider) => {
            const live = provider.status === "configured";
            const comingSoon = provider.status === "coming_soon";
            return (
              <li
                key={provider.key}
                className={`glass-panel flex flex-col rounded-3xl p-5 ${comingSoon ? "opacity-60" : ""}`}
                aria-disabled={!live || undefined}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="inline-flex items-center gap-2 text-sm font-semibold">
                    <ProviderGlyph provider={provider.key} />
                    {provider.display_name}
                  </span>
                  <span
                    className={`rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${
                      live
                        ? "border-emerald-400/25 bg-emerald-500/10 text-emerald-100"
                        : "border-white/[0.12] bg-white/[0.04] text-white/55"
                    }`}
                  >
                    {t(`providers.status.${comingSoon ? "comingSoon" : live ? "available" : "notConfigured"}`)}
                  </span>
                </div>
                <p className="mt-3 flex-1 text-xs leading-5 text-white/50">
                  {provider.key === "meta"
                    ? live
                      ? t("providers.metaBody")
                      : t("providers.metaNotConfigured")
                    : t("providers.comingSoonBody")}
                </p>
                {provider.key === "meta" ? (
                  <Button
                    className="mt-4 w-full"
                    disabled={!live || busy !== null}
                    onClick={() => void connect(provider)}
                  >
                    {busy === `start:${provider.key}` ? (
                      <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
                    ) : (
                      <Facebook className="h-4 w-4" aria-hidden="true" />
                    )}
                    {t("providers.connectFacebook")}
                  </Button>
                ) : (
                  <Button className="mt-4 w-full" variant="secondary" disabled>
                    {t("providers.comingSoonButton")}
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {/* Pending grants that still need an asset choice */}
      {pendingConnections.length > 0 && !pickerConnection && (
        <div className="glass-panel mt-8 rounded-3xl p-5 sm:p-6">
          <h2 className="text-base font-semibold">{t("pending.title")}</h2>
          <ul className="mt-3 grid gap-2">
            {pendingConnections.map((connection) => (
              <li key={connection.id} className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-white/[0.08] bg-black/20 p-3">
                <span className="inline-flex items-center gap-3 text-sm">
                  <Monogram name={connection.display_name} provider={connection.provider} />
                  {connection.display_name}
                </span>
                <span className="flex flex-wrap gap-2">
                  <Button size="sm" onClick={() => void openPicker(connection.id)} disabled={busy !== null}>
                    <Link2 className="h-4 w-4" aria-hidden="true" />
                    {t("pending.choose")}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => void cancelConnection(connection)} disabled={busy !== null}>
                    {t("pending.cancel")}
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Asset picker after the callback */}
      {assetsError && (
        <StatusMessage tone="error" className="mt-6">
          {assetsError}
        </StatusMessage>
      )}
      {pickerConnection && (
        <div className="glass-panel mt-8 rounded-3xl p-5 sm:p-6" aria-labelledby="social-picker-title">
          <h2 id="social-picker-title" className="text-base font-semibold">
            {t("picker.title", { name: pickerConnection.display_name })}
          </h2>
          <p className="mt-1 text-xs leading-5 text-white/50">{t("picker.body")}</p>
          {assets === null ? (
            <p className="mt-4 text-sm text-white/45" role="status">
              <LoaderCircle className="me-2 inline h-4 w-4 animate-spin" aria-hidden="true" />
              {t("loading")}
            </p>
          ) : assets.length === 0 ? (
            <StatusMessage className="mt-4">{t("picker.empty")}</StatusMessage>
          ) : (
            <>
              {assetGroup(t("picker.pages"), facebookAssets)}
              {assetGroup(t("picker.instagram"), instagramAssets)}
            </>
          )}
          {skippedCount > 0 && (
            <StatusMessage tone="error" className="mt-4">
              {t("picker.skipped", { count: skippedCount })}
            </StatusMessage>
          )}
          <div className="mt-5 flex flex-wrap gap-2">
            <Button disabled={busy !== null || selected.size === 0} onClick={() => void saveSelection()}>
              {busy === "connect" ? (
                <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
              )}
              {t("picker.connect", { count: selected.size })}
            </Button>
            <Button
              variant="ghost"
              disabled={busy !== null}
              onClick={() => {
                setPickerConnection(null);
                setAssets(null);
              }}
            >
              {t("picker.later")}
            </Button>
          </div>
        </div>
      )}

      {/* Connected accounts */}
      <h2 className="mt-10 text-lg font-semibold">{t("accounts.title")}</h2>
      {accounts.length === 0 ? (
        <div className="glass-panel mt-4 rounded-3xl p-6 text-sm text-white/50">{t("accounts.empty")}</div>
      ) : (
        <ul className="mt-4 grid gap-3">
          {accounts.map((account) => {
            const health = HEALTH_KEYS.has(account.health_state) ? account.health_state : "unknown";
            return (
              <li key={account.id} className="glass-panel flex flex-col gap-4 rounded-3xl p-5 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex min-w-0 items-center gap-3">
                  <Monogram name={account.display_name} provider={account.provider} />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold">{account.display_name}</p>
                    <p className="truncate text-xs text-white/45">
                      {account.handle ? `@${account.handle} · ` : ""}
                      {t(`kinds.${account.provider === "instagram" ? "instagram" : "page"}`)}
                    </p>
                  </div>
                </div>
                <div className="flex flex-col gap-3 sm:items-end">
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span
                      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 font-semibold ${
                        HEALTH_TONE[health] || "border-white/[0.12] bg-white/[0.04] text-white/60"
                      }`}
                    >
                      <HeartPulse className="h-3.5 w-3.5" aria-hidden="true" />
                      {t(`health.${health}`)}
                    </span>
                    <span className="text-white/40">
                      {t("accounts.lastChecked", { date: formatDate(account.last_health_at) })}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" variant="secondary" disabled={busy !== null} onClick={() => void checkHealth(account)}>
                      {busy === `health:${account.id}` ? (
                        <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
                      ) : (
                        <HeartPulse className="h-4 w-4" aria-hidden="true" />
                      )}
                      {t("accounts.checkHealth")}
                    </Button>
                    <Button size="sm" variant="danger" disabled={busy !== null} onClick={() => void disconnect(account)}>
                      {busy === `disconnect:${account.id}` ? (
                        <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
                      ) : confirming === account.id ? (
                        <ShieldAlert className="h-4 w-4" aria-hidden="true" />
                      ) : (
                        <Unlink className="h-4 w-4" aria-hidden="true" />
                      )}
                      {confirming === account.id ? t("accounts.confirmDisconnect") : t("accounts.disconnect")}
                    </Button>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
