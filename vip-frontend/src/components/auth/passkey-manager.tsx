"use client";

import { Fingerprint, LoaderCircle, Plus, Trash2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { StatusMessage } from "@/components/ui/status-message";
import { deletePasskey, getPasskeyConfiguration, listPasskeys } from "@/lib/api";
import { passkeysSupported, registerPasskey } from "@/lib/passkeys";
import type { PasskeyCredentialSummary } from "@/types";

export function PasskeyManager() {
  const t = useTranslations("profile");
  const locale = useLocale();
  const [supported, setSupported] = useState(true);
  const [passkeys, setPasskeys] = useState<PasskeyCredentialSummary[]>([]);
  const [nickname, setNickname] = useState("");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    Promise.all([getPasskeyConfiguration(), listPasskeys()])
      .then(([configuration, items]) => {
        setSupported(configuration.enabled && passkeysSupported());
        setPasskeys(items);
      })
      .catch(() => setError(t("passkeyLoadError")))
      .finally(() => setLoading(false));
  }, [t]);

  async function addPasskey() {
    setError("");
    setSuccess("");
    setWorking(true);
    try {
      const created = await registerPasskey(nickname.trim() || t("passkeyDefaultName"));
      setPasskeys((current) => [created, ...current]);
      setNickname("");
      setSuccess(t("passkeyAdded"));
    } catch {
      setError(t("passkeyAddError"));
    } finally {
      setWorking(false);
    }
  }

  async function removePasskey(passkey: PasskeyCredentialSummary) {
    if (!window.confirm(t("passkeyDeleteConfirm", { name: passkey.nickname }))) return;
    setError("");
    setSuccess("");
    setWorking(true);
    try {
      await deletePasskey(passkey.id);
      setPasskeys((current) => current.filter((item) => item.id !== passkey.id));
      setSuccess(t("passkeyDeleted"));
    } catch {
      setError(t("passkeyDeleteError"));
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="glass-panel rounded-3xl p-6 sm:p-9 lg:col-span-2">
      <div className="flex items-center gap-3">
        <Fingerprint className="h-5 w-5 text-electric-200" aria-hidden="true" />
        <h2 className="text-xl font-semibold">{t("passkeyTitle")}</h2>
      </div>
      <p className="mt-3 text-sm leading-7 text-white/45">
        {t("passkeyDescription")}
      </p>

      {loading ? (
        <div className="mt-7 flex items-center gap-3 text-sm text-white/45">
          <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
          {t("passkeyLoading")}
        </div>
      ) : (
        <>
          <div className="mt-7 flex flex-col gap-3 sm:flex-row">
            <input
              value={nickname}
              onChange={(event) => setNickname(event.target.value)}
              className="field-control flex-1"
              maxLength={120}
              placeholder={t("passkeyNamePlaceholder")}
              aria-label={t("passkeyName")}
              disabled={!supported || working}
            />
            <Button
              type="button"
              onClick={() => void addPasskey()}
              disabled={!supported || working}
            >
              {working ? (
                <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Plus className="h-4 w-4" aria-hidden="true" />
              )}
              {t("addPasskey")}
            </Button>
          </div>
          {!supported && (
            <p className="mt-3 text-xs leading-6 text-amber-200/70">
              {t("passkeyUnsupported")}
            </p>
          )}

          <div className="mt-7 space-y-3">
            {passkeys.length === 0 ? (
              <p className="rounded-xl border border-white/[0.07] p-4 text-sm text-white/40">
                {t("passkeyEmpty")}
              </p>
            ) : (
              passkeys.map((passkey) => (
                <div
                  key={passkey.id}
                  className="flex flex-col gap-3 rounded-xl border border-white/[0.07] p-4 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div>
                    <p className="font-semibold">{passkey.nickname}</p>
                    <p className="mt-1 text-xs text-white/35">
                      {t("passkeyCreated", {
                        date: new Intl.DateTimeFormat(locale, {
                          dateStyle: "medium"
                        }).format(new Date(passkey.created_at))
                      })}
                    </p>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={working}
                    onClick={() => void removePasskey(passkey)}
                  >
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                    {t("deletePasskey")}
                  </Button>
                </div>
              ))
            )}
          </div>
        </>
      )}
      {error && <StatusMessage tone="error" className="mt-5">{error}</StatusMessage>}
      {success && <StatusMessage tone="success" className="mt-5">{success}</StatusMessage>}
    </div>
  );
}
