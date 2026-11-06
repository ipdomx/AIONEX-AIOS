"use client";

import { CheckCircle2, KeyRound, Link2, LoaderCircle, RefreshCw, Unlink } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { StatusMessage } from "@/components/ui/status-message";
import {
  linkAdAccounts,
  listAdsConnections,
  listAvailableAdAccounts,
  requestAdAccountSync,
  startAdsConnect,
  unlinkAdAccount,
  updateAdAccountLink,
} from "@/lib/api";
import type { AdAccountLink, AdsAccess, AdsAvailableAccount, AdsConnection } from "@/types";

import { adsErrorText, currencyOffset, toMinor } from "./ads-shared";

const META_DIALOG_HOST = "www.facebook.com";
const SYNC_STATES = ["pending", "syncing", "ok", "throttled", "report_pending", "reconnect", "error"];

type Picker = { source: "oauth" | "owner_token"; connectionId: string | null; items: AdsAvailableAccount[] };

export function AdsAccountsPanel({
  access,
  links,
  onChanged,
  notice,
}: {
  access: AdsAccess;
  links: AdAccountLink[];
  onChanged: () => Promise<void>;
  notice: { tone: "success" | "error"; text: string } | null;
}) {
  const t = useTranslations("ads");
  const locale = useLocale();
  const [connections, setConnections] = useState<AdsConnection[]>([]);
  const [picker, setPicker] = useState<Picker | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [targets, setTargets] = useState<Record<string, string>>({});

  const loadConnections = useCallback(async () => {
    try {
      setConnections((await listAdsConnections()).items);
    } catch (cause) {
      setError(adsErrorText(t, cause));
    }
  }, [t]);

  useEffect(() => {
    void loadConnections();
  }, [loadConnections]);

  async function connect() {
    setError("");
    setBusy("connect");
    try {
      const { authorize_url: authorizeUrl } = await startAdsConnect(locale);
      const target = new URL(authorizeUrl);
      if (target.protocol !== "https:" || target.hostname !== META_DIALOG_HOST) throw new Error("unexpected-authorize-host");
      window.location.assign(target.toString());
    } catch (cause) {
      setError(adsErrorText(t, cause));
      setBusy(null);
    }
  }

  async function openPicker(source: "oauth" | "owner_token", connectionId: string | null) {
    setError("");
    setBusy(`picker:${connectionId ?? source}`);
    try {
      const result = await listAvailableAdAccounts({ source, connectionId });
      setPicker({ source, connectionId, items: result.items });
      setSelected(new Set());
    } catch (cause) {
      setError(adsErrorText(t, cause));
    } finally {
      setBusy(null);
    }
  }

  async function saveSelection() {
    if (!picker || selected.size === 0) return;
    setError("");
    setBusy("link");
    try {
      await linkAdAccounts({
        source: picker.source,
        connection_id: picker.connectionId,
        ad_account_ids: Array.from(selected),
      });
      setPicker(null);
      setMessage(t("accounts.linkedNotice"));
      await onChanged();
    } catch (cause) {
      setError(adsErrorText(t, cause));
    } finally {
      setBusy(null);
    }
  }

  async function act(key: string, work: () => Promise<unknown>, success?: string) {
    setError("");
    setMessage("");
    setBusy(key);
    try {
      await work();
      if (success) setMessage(success);
      await onChanged();
    } catch (cause) {
      setError(adsErrorText(t, cause));
    } finally {
      setBusy(null);
    }
  }

  function toggle(accountId: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(accountId)) next.delete(accountId);
      else next.add(accountId);
      return next;
    });
  }

  return (
    <div className="space-y-6">
      {notice && <StatusMessage tone={notice.tone}>{notice.text}</StatusMessage>}
      {message && <StatusMessage tone="success">{message}</StatusMessage>}
      {error && <StatusMessage tone="error">{error}</StatusMessage>}

      <section className="glass-card p-6">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="max-w-2xl">
            <h2 className="text-xl font-semibold text-white">{t("accounts.title")}</h2>
            <p className="mt-1 text-sm text-white/45">{t("accounts.description")}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void connect()} disabled={busy === "connect"}>
              {busy === "connect" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Link2 className="h-4 w-4" />}
              {t("accounts.connect")}
            </Button>
            {access.owner_token_fallback && (
              <Button variant="secondary" onClick={() => void openPicker("owner_token", null)} disabled={busy !== null}>
                <KeyRound className="h-4 w-4" /> {t("accounts.ownerToken")}
              </Button>
            )}
          </div>
        </div>
        {access.owner_token_fallback && <p className="mt-3 text-[11px] text-white/35">{t("accounts.ownerTokenNote")}</p>}

        <h3 className="mt-6 text-sm font-semibold text-white/80">{t("accounts.connections")}</h3>
        {connections.length === 0 ? (
          <p className="mt-2 text-sm text-white/40">{t("accounts.noConnections")}</p>
        ) : (
          <ul className="mt-3 grid gap-3 md:grid-cols-2">
            {connections.map((item) => (
              <li key={item.id} className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4">
                <div className="text-sm font-semibold text-white">{item.display_name}</div>
                <div className={`mt-1 text-xs ${item.can_manage ? "text-emerald-300/80" : "text-white/45"}`}>
                  {item.can_manage ? t("accounts.canManage") : t("accounts.readOnly")}
                </div>
                {item.ads_scopes_missing.length > 0 && (
                  <div className="mt-1 text-[11px] text-amber-200/70">
                    {t("accounts.missing", { scopes: item.ads_scopes_missing.join(", ") })}
                  </div>
                )}
                <Button
                  size="sm"
                  variant="secondary"
                  className="mt-3"
                  disabled={!item.can_read || busy !== null}
                  onClick={() => void openPicker("oauth", item.id)}
                >
                  {busy === `picker:${item.id}` && <LoaderCircle className="h-3.5 w-3.5 animate-spin" />}
                  {t("accounts.showAccounts")}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {picker && (
        <section className="glass-card p-6">
          <h3 className="text-lg font-semibold text-white">{t("accounts.availableTitle")}</h3>
          <ul className="mt-4 space-y-2">
            {picker.items.map((item) => (
              <li key={item.ad_account_id}>
                <label className="flex items-center gap-3 rounded-xl border border-white/[0.07] p-3 text-sm text-white/80">
                  <input
                    type="checkbox"
                    disabled={item.linked || !item.active}
                    checked={selected.has(item.ad_account_id)}
                    onChange={() => toggle(item.ad_account_id)}
                  />
                  <span className="flex-1">
                    <span className="font-medium text-white">{item.name}</span>
                    <span className="ms-2 text-xs text-white/40">
                      {item.currency} · {item.timezone_name}
                      {item.business_name ? ` · ${item.business_name}` : ""}
                    </span>
                  </span>
                  {item.linked && <span className="text-[11px] text-emerald-300/80">{t("accounts.alreadyLinked")}</span>}
                  {!item.active && <span className="text-[11px] text-amber-200/70">{t("accounts.inactive")}</span>}
                </label>
              </li>
            ))}
          </ul>
          <Button className="mt-4" onClick={() => void saveSelection()} disabled={selected.size === 0 || busy === "link"}>
            {busy === "link" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
            {t("accounts.linkSelected")}
          </Button>
        </section>
      )}

      <section className="space-y-3">
        <h3 className="text-lg font-semibold text-white">{t("accounts.linkedTitle")}</h3>
        {links.length === 0 ? (
          <div className="glass-card p-6 text-center text-sm text-white/40">{t("accounts.noLinked")}</div>
        ) : (
          links.map((link) => {
            const state = SYNC_STATES.includes(link.sync_state) ? link.sync_state : "error";
            const draft = targets[link.id] ?? (link.cpa_target_minor ? String(link.cpa_target_minor / currencyOffset(link.currency)) : "");
            return (
              <article key={link.id} className="glass-card p-5">
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div>
                    <div className="text-sm font-semibold text-white">{link.name}</div>
                    <div className="mt-1 text-xs text-white/40">
                      {link.currency} · {link.timezone_name} · {t(`sync.${state}`)}
                    </div>
                    <div className="mt-1 text-[11px] text-white/35">
                      {t("accounts.lastSync", { value: link.last_sync_at ? new Date(link.last_sync_at).toLocaleString(locale) : t("never") })}
                      {link.insights_synced_through ? ` · ${t("accounts.syncedThrough", { value: link.insights_synced_through })}` : ""}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={busy !== null}
                      onClick={() => void act(`sync:${link.id}`, () => requestAdAccountSync(link.id), t("accounts.syncRequested"))}
                    >
                      <RefreshCw className="h-3.5 w-3.5" /> {t("accounts.syncNow")}
                    </Button>
                    <Button size="sm" variant="danger" disabled={busy !== null} onClick={() => void act(`unlink:${link.id}`, () => unlinkAdAccount(link.id))}>
                      <Unlink className="h-3.5 w-3.5" /> {t("accounts.unlink")}
                    </Button>
                  </div>
                </div>
                <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-end">
                  <label className="space-y-1">
                    <span className="text-[11px] text-white/45">{t("accounts.cpaTarget", { currency: link.currency })}</span>
                    <input
                      inputMode="decimal"
                      value={draft}
                      onChange={(e) => setTargets((current) => ({ ...current, [link.id]: e.target.value }))}
                      className="glass-input w-40 rounded-xl px-3 py-2 text-sm text-white outline-none"
                    />
                  </label>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy !== null}
                    onClick={() =>
                      void act(`target:${link.id}`, () =>
                        updateAdAccountLink(link.id, { cpa_target_minor: draft.trim() ? toMinor(draft, link.currency) || null : null }),
                      )
                    }
                  >
                    {t("accounts.saveTarget")}
                  </Button>
                </div>
              </article>
            );
          })
        )}
      </section>
    </div>
  );
}
