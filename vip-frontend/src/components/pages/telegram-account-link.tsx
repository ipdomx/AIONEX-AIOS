"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  createUserTelegramLinkChallenge,
  getUserTelegramStatus,
  revokeUserTelegramLink,
} from "@/lib/api";
import type { UserTelegramChallenge, UserTelegramStatus } from "@/types";

export function TelegramAccountLink() {
  const t = useTranslations("notifications.telegramAccount");
  const [status, setStatus] = useState<UserTelegramStatus | null>(null);
  const [challenge, setChallenge] = useState<UserTelegramChallenge | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    try {
      setStatus(await getUserTelegramStatus());
    } catch {
      setMessage(t("loadError"));
    }
  }, [t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function createLink() {
    setBusy(true);
    setMessage("");
    try {
      const next = await createUserTelegramLinkChallenge();
      setChallenge(next);
      setStatus(await getUserTelegramStatus());
    } catch {
      setMessage(t("createError"));
    } finally {
      setBusy(false);
    }
  }

  async function unlink() {
    setBusy(true);
    setMessage("");
    try {
      await revokeUserTelegramLink();
      setChallenge(null);
      setStatus(await getUserTelegramStatus());
    } catch {
      setMessage(t("unlinkError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardContent>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold">{t("title")}</h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-white/45">
              {t("description")}
            </p>
          </div>
          <span className="rounded-full border border-white/10 px-3 py-1 text-xs text-white/55">
            {status?.linked && status.link_current ? t("linked") : t("notLinked")}
          </span>
        </div>

        <div className="mt-5 flex flex-wrap gap-2">
          <Button
            onClick={() => void createLink()}
            disabled={busy || status?.configured === false}
          >
            {t("createLink")}
          </Button>
          <Button variant="secondary" onClick={() => void refresh()} disabled={busy}>
            {t("refresh")}
          </Button>
          {status?.linked ? (
            <Button variant="secondary" onClick={() => void unlink()} disabled={busy}>
              {t("unlink")}
            </Button>
          ) : null}
        </div>

        {status?.configured === false ? (
          <p className="mt-4 text-sm text-amber-200/80">{t("inactive")}</p>
        ) : null}
        {status?.bot_username ? (
          <p className="mt-3 text-sm text-white/45">
            {t("bot", { username: status.bot_username })}
          </p>
        ) : null}
        {challenge ? (
          <div className="mt-5 rounded-2xl border border-white/10 bg-black/20 p-4">
            <p className="text-xs uppercase tracking-wider text-white/35">
              {t("oneTimeCode")}
            </p>
            <code className="mt-2 block break-all text-lg text-white">{challenge.code}</code>
            <p className="mt-2 text-xs text-white/40">{t("expires")}</p>
            {challenge.deep_link ? (
              <a
                href={challenge.deep_link}
                target="_blank"
                rel="noreferrer"
                className="mt-4 inline-flex rounded-xl border border-white/10 px-4 py-2 text-sm text-white hover:bg-white/5"
              >
                {t("openTelegram")}
              </a>
            ) : null}
          </div>
        ) : null}
        {message ? <p className="mt-4 text-sm text-amber-200/80">{message}</p> : null}
      </CardContent>
    </Card>
  );
}
